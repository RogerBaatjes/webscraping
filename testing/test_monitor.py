import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from webscraping.monitor import (
    cleanup_html,
    get_ssl_verify_path,
    has_website_changed,
    notification_state_changed,
    parse_args,
    products_not_marked_sold_out,
    resolve_runtime_config,
    run_monitor,
    save_notification_state,
    send_test_email,
)
from webscraping.mailer import Mail


class TestHTMLCleanup(unittest.TestCase):
    """Test HTML cleaning functionality"""

    def test_removes_script_tags(self):
        html = "<html><body>Content<script>alert('hi');</script></body></html>"
        result = cleanup_html(html)
        self.assertNotIn("alert", result)

    def test_removes_style_tags(self):
        html = "<html><head><style>.class { color: red; }</style></head><body>Content</body></html>"
        result = cleanup_html(html)
        self.assertNotIn("color: red", result)

    def test_removes_meta_tags(self):
        html = '<html><head><meta name="viewport" content="width=device-width"></head><body>Content</body></html>'
        result = cleanup_html(html)
        self.assertNotIn("viewport", result)

    def test_preserves_body_content(self):
        html = "<html><body><h1>Test Heading</h1><p>Test paragraph</p></body></html>"
        result = cleanup_html(html)
        self.assertIn("Test Heading", result)
        self.assertIn("Test paragraph", result)


class TestSslConfiguration(unittest.TestCase):
    """Test CA-bundle selection without making network requests."""

    def test_resolves_relative_ca_bundle_from_project_root(self):
        with patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": "certificates/company-ca.pem"}, clear=True):
            self.assertEqual(
                get_ssl_verify_path(),
                str(PROJECT_ROOT / "certificates" / "company-ca.pem"),
            )

    def test_uses_certifi_when_no_ca_bundle_is_configured(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "webscraping.monitor.certifi.where", return_value="certifi-ca.pem"
        ):
            self.assertEqual(get_ssl_verify_path(), "certifi-ca.pem")


class TestArgumentParsing(unittest.TestCase):
    """Test argument parser"""

    def test_parse_website_url_argument(self):
        with patch("sys.argv", ["monitor.py", "--website-url", "https://example.com"]):
            args = parse_args()
            self.assertEqual(args.website_url, "https://example.com")

    def test_parse_website_name_argument(self):
        with patch("sys.argv", ["monitor.py", "--website-name", "example_pg1"]):
            args = parse_args()
            self.assertEqual(args.website_name, "example_pg1")

    def test_parse_private_email_mode_argument(self):
        with patch("sys.argv", ["monitor.py", "--private-email-mode", "ACTIVATE_PRIVATE_EMAIL"]):
            args = parse_args()
            self.assertEqual(args.private_email_mode, "ACTIVATE_PRIVATE_EMAIL")

    def test_parse_interval_seconds_argument(self):
        with patch("sys.argv", ["monitor.py", "--interval-seconds", "120"]):
            args = parse_args()
            self.assertEqual(args.interval_seconds, 120)

    def test_parse_once_flag(self):
        with patch("sys.argv", ["monitor.py", "--once"]):
            args = parse_args()
            self.assertTrue(args.once)

    def test_parse_send_test_email_flag(self):
        with patch("sys.argv", ["monitor.py", "--send-test-email"]):
            self.assertTrue(parse_args().send_test_email)

    def test_parse_cache_dir_argument(self):
        with patch("sys.argv", ["monitor.py", "--cache-dir", "/tmp/cache"]):
            args = parse_args()
            self.assertEqual(args.cache_dir, "/tmp/cache")


class TestRuntimeConfig(unittest.TestCase):
    """Test runtime configuration resolution"""

    def test_resolves_from_args(self):
        with patch("sys.argv", [
            "monitor.py",
            "--website-url", "https://example.com",
            "--website-name", "example_test"
        ]):
            args = parse_args()
            config = resolve_runtime_config(args)
            self.assertEqual(config["website"], "https://example.com/collections/all")
            self.assertEqual(config["website_name"], "example_test")

    def test_resolves_from_environment(self):
        with patch.dict(os.environ, {
            "WEBSITE_URL": "https://env-example.com",
            "WEBSITE_NAME": "env_test",
            "EMAIL_RECIPIENTS": "test@example.com",
            "CHECK_INTERVAL_SECONDS": "600"
        }):
            with patch("sys.argv", ["monitor.py"]):
                args = parse_args()
                config = resolve_runtime_config(args)
                self.assertEqual(config["website"], "https://env-example.com/collections/all")
                self.assertEqual(config["website_name"], "env_test")
                self.assertEqual(config["interval_seconds"], 600)

    def test_args_override_environment(self):
        with patch.dict(os.environ, {
            "WEBSITE_URL": "https://env-example.com",
            "WEBSITE_NAME": "env_test",
            "EMAIL_RECIPIENTS": "test@example.com"
        }):
            with patch("sys.argv", [
                "monitor.py",
                "--website-url", "https://args-example.com",
                "--website-name", "args_test"
            ]):
                args = parse_args()
                config = resolve_runtime_config(args)
                self.assertEqual(config["website"], "https://args-example.com/collections/all")
                self.assertEqual(config["website_name"], "args_test")

    def test_raises_error_when_required_config_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.argv", ["monitor.py"]):
                args = parse_args()
                with self.assertRaises(ValueError) as context:
                    resolve_runtime_config(args)
                self.assertIn("WEBSITE_URL", str(context.exception))


class TestMailConfiguration(unittest.TestCase):
    """Test SMTP configuration and email sending"""

    def test_mail_initialization_from_env(self):
        with patch.dict(os.environ, {
            "SMTP_SERVER": "smtp.gmail.com",
            "SMTP_PORT": "465",
            "SMTP_SENDER_EMAIL": "test@gmail.com",
            "SMTP_APP_PASSWORD": "testpassword123"
        }):
            mail = Mail.from_env()
            self.assertEqual(mail.smtp_server, "smtp.gmail.com")
            self.assertEqual(mail.smtp_port, 465)
            self.assertEqual(mail.sender_email, "test@gmail.com")
            self.assertEqual(mail.app_password, "testpassword123")

    def test_mail_raises_error_when_credentials_missing(self):
        with patch.dict(os.environ, {
            "SMTP_SERVER": "smtp.gmail.com",
            "SMTP_PORT": "465",
            "SMTP_SENDER_EMAIL": "",
            "SMTP_APP_PASSWORD": ""
        }, clear=True):
            with self.assertRaises(ValueError) as context:
                Mail.from_env()
            self.assertIn("SMTP_SENDER_EMAIL", str(context.exception))

    def test_mail_raises_error_when_no_recipients(self):
        with patch.dict(os.environ, {
            "SMTP_SERVER": "smtp.gmail.com",
            "SMTP_PORT": "465",
            "SMTP_SENDER_EMAIL": "test@gmail.com",
            "SMTP_APP_PASSWORD": "testpassword123"
        }):
            mail = Mail.from_env()
            with self.assertRaises(ValueError) as context:
                mail.send([], "Test Subject", "Test Content")
            self.assertIn("No recipient", str(context.exception))

    @patch("smtplib.SMTP_SSL")
    def test_mail_sends_one_message_to_all_recipients(self, mock_smtp):
        with patch.dict(os.environ, {
            "SMTP_SERVER": "smtp.gmail.com",
            "SMTP_PORT": "465",
            "SMTP_SENDER_EMAIL": "test@gmail.com",
            "SMTP_APP_PASSWORD": "testpassword123"
        }):
            mail = Mail.from_env()
            recipients = ["first@example.com", "second@example.com"]
            mail.send(recipients, "Test Subject", "Test Content")
            
            # Verify SMTP connection was attempted
            mock_smtp.assert_called_once()
            
            # Verify login was called
            mock_instance = mock_smtp.return_value.__enter__.return_value
            mock_instance.login.assert_called_once_with("test@gmail.com", "testpassword123")
            
            # One SMTP message is addressed to the full recipient list.
            mock_instance.sendmail.assert_called_once()
            sender, sent_recipients, message = mock_instance.sendmail.call_args.args
            self.assertEqual(sender, "test@gmail.com")
            self.assertEqual(sent_recipients, recipients)
            self.assertIn("To: test@gmail.com", message)


class TestWebsiteFetching(unittest.TestCase):
    """Test website fetching and caching"""

    def test_has_website_changed_new_cache(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "<html><body>Test Content</body></html>"
            
            with patch("webscraping.monitor.fetch_website", return_value=mock_response):
                result = has_website_changed("https://example.com", "test_site", cache_dir)
                # First run creates cache, should return 0 (no change detected)
                self.assertEqual(result, 0)
                
                # Verify cache file was created
                cache_file = cache_dir / "test_site_cache.txt"
                self.assertTrue(cache_file.exists())

    def test_has_website_changed_no_change(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            cache_file = cache_dir / "test_site_cache.txt"
            cache_file.write_text("<html><body>Test Content</body></html>", encoding="utf-8")
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "<html><body>Test Content</body></html>"
            
            with patch("webscraping.monitor.fetch_website", return_value=mock_response):
                result = has_website_changed("https://example.com", "test_site", cache_dir)
                # Content unchanged, should return 0
                self.assertEqual(result, 0)

    def test_has_website_changed_detected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            cache_file = cache_dir / "test_site_cache.txt"
            cache_file.write_text("<html><body>Old Content</body></html>", encoding="utf-8")
            
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "<html><body>New Content</body></html>"
            
            with patch("webscraping.monitor.fetch_website", return_value=mock_response):
                result = has_website_changed("https://example.com", "test_site", cache_dir)
                # Content changed, should return 1
                self.assertEqual(result, 1)

    def test_has_website_changed_failed_request(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            
            with patch("webscraping.monitor.fetch_website", return_value=None):
                result = has_website_changed("https://example.com", "test_site", cache_dir)
                # Request failed, should return -1
            self.assertEqual(result, -1)


class TestNotificationState(unittest.TestCase):
    def test_alert_is_only_new_after_status_changes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)

            self.assertTrue(notification_state_changed(cache_dir, "test_site", True))
            save_notification_state(cache_dir, "test_site", True)
            self.assertFalse(notification_state_changed(cache_dir, "test_site", True))

            self.assertTrue(notification_state_changed(cache_dir, "test_site", False))
            save_notification_state(cache_dir, "test_site", False)
            self.assertTrue(notification_state_changed(cache_dir, "test_site", True))


class TestNotLaptopsCheck(unittest.TestCase):
    def test_detects_product_without_sold_out_tag(self):
        html = """
        <ul id="product-grid">
          <li class="grid__item grid-view-item--sold-out"></li>
          <li class="grid__item"><div class="card-wrapper"></div></li>
        </ul>
        """
        self.assertTrue(products_not_marked_sold_out(html))

    def test_ignores_page_when_all_products_are_sold_out(self):
        html = """
        <ul id="product-grid">
          <li class="grid__item grid-view-item--sold-out"></li>
          <li class="grid__item grid-view-item--sold-out"></li>
        </ul>
        """
        self.assertFalse(products_not_marked_sold_out(html))

    def test_runtime_config_enables_check_from_environment(self):
        with patch.dict(os.environ, {
            "WEBSITE_URL": "https://example.com",
            "WEBSITE_NAME": "test_site",
            "NOT_LAPTOPS": "true",
        }, clear=True):
            with patch("sys.argv", ["monitor.py"]):
                self.assertTrue(resolve_runtime_config(parse_args())["not_laptops"])

    @patch("webscraping.monitor.Mail.from_env")
    @patch("webscraping.monitor.has_website_changed", return_value=(0, True))
    def test_sends_alert_for_available_product_without_page_change(self, mock_check, mock_mail):
        config = {
            "website": "https://example.com",
            "website_name": "test_site",
            "cache_dir": Path("cache"),
            "not_laptops": True,
            "private_email_mode": "",
            "private_trigger": "ACTIVATE_PRIVATE_EMAIL",
            "private_recipients": [],
            "recipients": ["recipient@example.com"],
            "subject": "Available",
            "content_template": "Visit {website}",
        }

        run_monitor(config, run_once=True)

        mock_check.assert_called_once_with(
            "https://example.com", "test_site", Path("cache"), check_not_laptops=True
        )
        mock_mail.return_value.send.assert_called_once_with(
            ["recipient@example.com"], "Available", "Visit https://example.com"
        )


class TestEmailDeliveryCheck(unittest.TestCase):
    @patch("webscraping.monitor.Mail.from_env")
    def test_send_test_email_uses_configured_recipients(self, mock_mail):
        config = {
            "private_email_mode": "",
            "private_trigger": "ACTIVATE_PRIVATE_EMAIL",
            "private_recipients": [],
            "recipients": ["recipient@example.com"],
            "subject": "Available",
        }

        send_test_email(config)

        mock_mail.return_value.send.assert_called_once_with(
            ["recipient@example.com"],
            "[TEST] Available",
            "This is a test email from the website monitor. SMTP delivery is working.",
        )

    def test_has_website_changed_bad_status_code(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            mock_response = MagicMock()
            mock_response.status_code = 500
            
            with patch("webscraping.monitor.fetch_website", return_value=mock_response):
                result = has_website_changed("https://example.com", "test_site", cache_dir)
                # Bad status code, should return -1
                self.assertEqual(result, -1)


class TestPrivateEmailMode(unittest.TestCase):
    """Test private email triggering logic"""

    def test_private_email_mode_matches_trigger(self):
        with patch.dict(os.environ, {
            "WEBSITE_URL": "https://example.com",
            "WEBSITE_NAME": "test_site",
            "EMAIL_RECIPIENTS": "public@example.com",
            "PRIVATE_EMAIL_RECIPIENTS": "private@example.com",
            "PRIVATE_EMAIL_TRIGGER": "ACTIVATE_PRIVATE_EMAIL"
        }):
            with patch("sys.argv", [
                "monitor.py",
                "--private-email-mode", "ACTIVATE_PRIVATE_EMAIL"
            ]):
                args = parse_args()
                config = resolve_runtime_config(args)
                self.assertEqual(config["private_email_mode"], config["private_trigger"])

    def test_private_email_recipients_when_triggered(self):
        with patch.dict(os.environ, {
            "WEBSITE_URL": "https://example.com",
            "WEBSITE_NAME": "test_site",
            "EMAIL_RECIPIENTS": "public1@example.com,public2@example.com",
            "PRIVATE_EMAIL_RECIPIENTS": "private1@example.com",
            "PRIVATE_EMAIL_TRIGGER": "ACTIVATE_PRIVATE_EMAIL",
            "PRIVATE_EMAIL_MODE": "ACTIVATE_PRIVATE_EMAIL"
        }):
            with patch("sys.argv", ["monitor.py"]):
                args = parse_args()
                config = resolve_runtime_config(args)
                
                # When mode matches trigger and private recipients exist, use private
                if config["private_email_mode"] == config["private_trigger"] and config["private_recipients"]:
                    recipients = config["private_recipients"]
                else:
                    recipients = config["recipients"]
                
                self.assertEqual(recipients, ["private1@example.com"])

    def test_default_recipients_when_not_triggered(self):
        with patch.dict(os.environ, {
            "WEBSITE_URL": "https://example.com",
            "WEBSITE_NAME": "test_site",
            "EMAIL_RECIPIENTS": "public1@example.com,public2@example.com",
            "PRIVATE_EMAIL_RECIPIENTS": "private1@example.com",
            "PRIVATE_EMAIL_TRIGGER": "ACTIVATE_PRIVATE_EMAIL",
            "PRIVATE_EMAIL_MODE": ""
        }):
            with patch("sys.argv", ["monitor.py"]):
                args = parse_args()
                config = resolve_runtime_config(args)
                
                # When mode doesn't match trigger, use public recipients
                if config["private_email_mode"] == config["private_trigger"] and config["private_recipients"]:
                    recipients = config["private_recipients"]
                else:
                    recipients = config["recipients"]
                
                self.assertEqual(recipients, ["public1@example.com", "public2@example.com"])


if __name__ == "__main__":
    unittest.main()
