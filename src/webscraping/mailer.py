import os
import smtplib
import ssl


class Mail:
    def __init__(self, smtp_server, smtp_port, sender_email, app_password):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.app_password = app_password

        if not self.sender_email or not self.app_password:
            raise ValueError("SMTP_SENDER_EMAIL and SMTP_APP_PASSWORD must be set in environment variables.")

    @classmethod
    def from_env(cls):
        return cls(
            smtp_server=os.getenv("SMTP_SERVER", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "465")),
            sender_email=os.getenv("SMTP_SENDER_EMAIL", ""),
            app_password=os.getenv("SMTP_APP_PASSWORD", ""),
        )

    def send(self, emails, subject, content):
        if not emails:
            raise ValueError("No recipient emails configured.")

        # Pass the complete recipient list to SMTP in one call.  The addresses are
        # envelope recipients only, so recipients do not see one another's email
        # addresses.
        message = f"Subject: {subject}\nTo: {self.sender_email}\nPriority: Urgent\n\n{content}"
        ssl_context = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=ssl_context) as service:
            service.login(self.sender_email, self.app_password)
            service.sendmail(self.sender_email, emails, message)
