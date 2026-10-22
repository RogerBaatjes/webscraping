import argparse
import os
import time
from pathlib import Path

import certifi
import requests
import urllib3
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from webscraping.mailer import Mail

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
MONITORED_PATH = "/collections/all"


def cleanup_html(html):
    soup = BeautifulSoup(html, features="lxml")
    for element in soup.select("script,style,meta"):
        element.extract()
    return str(soup)


def get_ssl_verify_path():
    configured_bundle = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("SSL_CERT_FILE")
    if not configured_bundle:
        return certifi.where()

    bundle_path = Path(configured_bundle)
    if not bundle_path.is_absolute():
        bundle_path = PROJECT_ROOT / bundle_path
    return str(bundle_path)


def should_allow_insecure_ssl_fallback():
    return os.getenv("ALLOW_INSECURE_SSL_FALLBACK", "true").strip().lower() in ("1", "true", "yes")


def fetch_website(website_url, headers, timeout_seconds):
    verify_path = get_ssl_verify_path()
    try:
        return requests.get(
            website_url,
            headers=headers,
            timeout=timeout_seconds,
            verify=verify_path,
        )
    except requests.exceptions.SSLError as ssl_error:
        if not should_allow_insecure_ssl_fallback():
            print(f"SSL verification failed and insecure fallback is disabled: {ssl_error}")
            return None

        print(f"SSL verification failed using '{verify_path}'; retrying without certificate verification.")
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            return requests.get(
                website_url,
                headers=headers,
                timeout=timeout_seconds,
                verify=False,
            )
        except requests.exceptions.RequestException as request_error:
            print(f"Retry without certificate verification failed: {request_error}")
            return None
    except requests.exceptions.RequestException as request_error:
        print(f"Request failed: {request_error}")
        return None
    except OSError as os_error:
        print(f"TLS certificate path issue: {os_error}")
        return None


def products_not_marked_sold_out(html):
    """Return True when a product card is not marked as sold out."""
    soup = BeautifulSoup(html, features="lxml")
    product_cards = soup.select("#product-grid > li")
    if not product_cards:
        product_cards = soup.select(".grid-view-item")
    if not product_cards:
        product_cards = soup.select("#product-grid .grid__item, .product-grid .grid__item")

    return bool(product_cards) and any(
        "grid-view-item--sold-out" not in card.get("class", [])
        and not card.select_one(".grid-view-item--sold-out")
        for card in product_cards
    )


def has_website_changed(website_url, website_name, cache_dir, check_not_laptops=False):
    headers = {
        "User-Agent": "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; PIWEBMON)",
        "Cache-Control": "no-cache",
    }
    timeout_seconds = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    response = fetch_website(website_url, headers, timeout_seconds)

    if response is None or response.status_code < 200 or response.status_code > 299:
        return (-1, False) if check_not_laptops else -1

    response_text = cleanup_html(response.text)
    has_available_product = products_not_marked_sold_out(response.text)
    cache_file = cache_dir / f"{website_name}_cache.txt"

    if not cache_file.exists():
        cache_file.write_text(response_text, encoding="utf-8")
        return (0, has_available_product) if check_not_laptops else 0

    previous_response_text = cache_file.read_text(encoding="utf-8")
    if response_text == previous_response_text:
        return (0, has_available_product) if check_not_laptops else 0

    cache_file.write_text(response_text, encoding="utf-8")
    return (1, has_available_product) if check_not_laptops else 1


def notification_state_path(cache_dir, website_name):
    return cache_dir / f"{website_name}_notification_state.txt"


def notification_state_changed(cache_dir, website_name, is_active):
    state_file = notification_state_path(cache_dir, website_name)
    previous_state = state_file.read_text(encoding="utf-8").strip() if state_file.exists() else None
    current_state = "active" if is_active else "inactive"
    return previous_state != current_state


def save_notification_state(cache_dir, website_name, is_active):
    notification_state_path(cache_dir, website_name).write_text(
        "active" if is_active else "inactive",
        encoding="utf-8",
    )


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor a website and send email alerts on changes.")
    parser.add_argument("--website-url", dest="website_url")
    parser.add_argument("--website-name", dest="website_name")
    parser.add_argument("--private-email-mode", dest="private_email_mode")
    parser.add_argument("--interval-seconds", dest="interval_seconds", type=int)
    parser.add_argument("--cache-dir", dest="cache_dir")
    parser.add_argument("--once", action="store_true", help="Run one check and exit.")
    parser.add_argument("--send-test-email", action="store_true", help="Send an email using the configured SMTP settings and exit.")
    return parser.parse_args()


def resolve_runtime_config(args):
    website_base_url = args.website_url or os.getenv("WEBSITE_URL", "")
    website_name = args.website_name or os.getenv("WEBSITE_NAME", "")
    if not website_base_url or not website_name:
        raise ValueError("WEBSITE_URL and WEBSITE_NAME must be provided via args or environment variables.")

    website = f"{website_base_url.rstrip('/')}{MONITORED_PATH}"

    private_email_mode = (
        args.private_email_mode if args.private_email_mode is not None else os.getenv("PRIVATE_EMAIL_MODE", "")
    )
    interval_seconds = args.interval_seconds or int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
    cache_dir = Path(args.cache_dir or os.getenv("CACHE_DIR", PROJECT_ROOT / "cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)

    recipients = [email.strip() for email in os.getenv("EMAIL_RECIPIENTS", "").split(",") if email.strip()]
    private_recipients = [email.strip() for email in os.getenv("PRIVATE_EMAIL_RECIPIENTS", "").split(",") if email.strip()]
    private_trigger = os.getenv("PRIVATE_EMAIL_TRIGGER", "ACTIVATE_PRIVATE_EMAIL")
    not_laptops = os.getenv("NOT_LAPTOPS", "").strip().lower() in ("1", "true", "yes")
    subject = os.getenv("ALERT_SUBJECT", "Laptop Sales GO NOW!!!")
    content_template = os.getenv(
        "ALERT_MESSAGE_TEMPLATE",
        "BUY YOUR DEVICE NOW!!!! Navigate to\n\n{website}\n\n *** If you don't want, buy for RogerB ***",
    )

    return {
        "website": website,
        "website_name": website_name,
        "private_email_mode": private_email_mode,
        "interval_seconds": interval_seconds,
        "cache_dir": cache_dir,
        "recipients": recipients,
        "private_recipients": private_recipients,
        "private_trigger": private_trigger,
        "not_laptops": not_laptops,
        "subject": subject,
        "content_template": content_template,
    }


def run_monitor(config, run_once=False):
    mail = None
    while True:
        check_result = has_website_changed(
            config["website"],
            config["website_name"],
            config["cache_dir"],
            check_not_laptops=config["not_laptops"],
        )
        if config["not_laptops"]:
            website_status, has_available_product = check_result
        else:
            website_status, has_available_product = check_result, False
        recipients = (
            config["private_recipients"]
            if config["private_email_mode"] == config["private_trigger"] and config["private_recipients"]
            else config["recipients"]
        )
        content = config["content_template"].format(website=config["website"])

        if website_status == -1:
            print("Non 2XX response while fetching")
        else:
            notification_is_active = has_available_product or website_status == 1
            state_changed = notification_state_changed(
                config["cache_dir"], config["website_name"], notification_is_active
            )

            if not notification_is_active:
                if state_changed:
                    save_notification_state(config["cache_dir"], config["website_name"], False)
                print("Website is the same")
            elif not state_changed:
                print("Notification already sent for the current status")
            else:
                print(
                    "There is a product available to purchase"
                    if has_available_product
                    else "Website has changed"
                )
                if mail is None:
                    mail = Mail.from_env()
                mail.send(recipients, config["subject"], content)
                save_notification_state(config["cache_dir"], config["website_name"], True)

        if run_once:
            return

        time.sleep(config["interval_seconds"])


def send_test_email(config):
    recipients = (
        config["private_recipients"]
        if config["private_email_mode"] == config["private_trigger"] and config["private_recipients"]
        else config["recipients"]
    )
    content = "This is a test email from the website monitor. SMTP delivery is working."
    Mail.from_env().send(recipients, f"[TEST] {config['subject']}", content)
    print("Test email sent")


def main():
    load_dotenv(DEFAULT_ENV_PATH)
    args = parse_args()
    config = resolve_runtime_config(args)
    if args.send_test_email:
        send_test_email(config)
        return
    run_monitor(config, run_once=args.once)


if __name__ == "__main__":
    main()

