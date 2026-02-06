"""
Email Sender for LPSC Bulletin Monitor

Sends HTML email reports via Gmail SMTP using Python's built-in
smtplib and email.mime modules — no extra dependencies needed.

Setup required:
1. Enable 2-Factor Authentication on your Gmail account
2. Generate an App Password at https://myaccount.google.com/apppasswords
3. Add EMAIL_SENDER, EMAIL_APP_PASSWORD, and EMAIL_RECIPIENTS to your .env file
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import (
    SMTP_SERVER, SMTP_PORT,
    EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECIPIENTS,
    log
)


def send_report_email(html_content: str, bulletin_number: int,
                      bulletin_date: str = None) -> bool:
    """
    Send an HTML email report to all configured recipients.

    Uses Gmail SMTP with TLS (port 587) and App Password authentication.

    Args:
        html_content: The full HTML email body
        bulletin_number: Used in the subject line
        bulletin_date: Used in the subject line (optional)

    Returns:
        True if sent successfully, False otherwise
    """
    # Validate email configuration
    if not EMAIL_SENDER:
        print("ERROR: EMAIL_SENDER not set in .env file")
        print("  Add: EMAIL_SENDER=your.email@gmail.com")
        return False

    if not EMAIL_APP_PASSWORD:
        print("ERROR: EMAIL_APP_PASSWORD not set in .env file")
        print("  Set up an App Password at https://myaccount.google.com/apppasswords")
        return False

    if not EMAIL_RECIPIENTS:
        print("ERROR: EMAIL_RECIPIENTS not set in .env file")
        print("  Add: EMAIL_RECIPIENTS=recipient1@example.com,recipient2@example.com")
        return False

    # Build the email
    msg = MIMEMultipart('alternative')

    date_part = f" ({bulletin_date})" if bulletin_date else ""
    msg['Subject'] = f"LPSC Bulletin #{bulletin_number}{date_part} - Relevant Dockets"
    msg['From'] = EMAIL_SENDER
    msg['To'] = ", ".join(EMAIL_RECIPIENTS)

    # Attach the HTML body
    html_part = MIMEText(html_content, 'html')
    msg.attach(html_part)

    # Send via Gmail SMTP
    try:
        log(f"Connecting to {SMTP_SERVER}:{SMTP_PORT}...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENTS, msg.as_string())

        print(f"Email sent to: {', '.join(EMAIL_RECIPIENTS)}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail authentication failed.")
        print("  Check your EMAIL_SENDER and EMAIL_APP_PASSWORD in .env")
        print("  Make sure you're using an App Password, not your regular password")
        return False
    except smtplib.SMTPException as e:
        print(f"ERROR: Failed to send email: {e}")
        return False
    except Exception as e:
        print(f"ERROR: Unexpected error sending email: {e}")
        return False
