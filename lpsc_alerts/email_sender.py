"""
Email Sender for LPSC Alerts

Sends HTML alert emails via Gmail SMTP. Adapted from lpsc_monitor
to send one email at a time to individual users.

Setup:
1. Enable 2FA on your Gmail account
2. Generate an App Password at https://myaccount.google.com/apppasswords
3. Add EMAIL_SENDER and EMAIL_APP_PASSWORD to your .env file
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import SMTP_SERVER, SMTP_PORT, EMAIL_SENDER, EMAIL_APP_PASSWORD, log


def send_alert_email(recipient: str, subject: str, html_content: str) -> bool:
    """
    Send an HTML email to a single recipient.

    Args:
        recipient: Email address to send to
        subject: Email subject line
        html_content: Full HTML email body

    Returns:
        True if sent successfully, False otherwise
    """
    if not EMAIL_SENDER:
        print("ERROR: EMAIL_SENDER not set in .env file")
        return False

    if not EMAIL_APP_PASSWORD:
        print("ERROR: EMAIL_APP_PASSWORD not set in .env file")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = EMAIL_SENDER
    msg['To'] = recipient

    msg.attach(MIMEText(html_content, 'html'))

    try:
        log(f"Sending email to {recipient}...")
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, [recipient], msg.as_string())

        print(f"  Email sent to: {recipient}")
        return True

    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail authentication failed.")
        print("  Check EMAIL_SENDER and EMAIL_APP_PASSWORD in .env")
        return False
    except smtplib.SMTPException as e:
        print(f"ERROR: Failed to send email: {e}")
        return False
    except Exception as e:
        print(f"ERROR: Unexpected error sending email: {e}")
        return False
