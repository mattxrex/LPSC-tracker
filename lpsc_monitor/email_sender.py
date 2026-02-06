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
    EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECIPIENTS, EMAIL_ADMIN,
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


def send_admin_alert(subject: str, message: str) -> bool:
    """
    Send an alert email to the admin only (not all recipients).

    Used for system warnings like API credit exhaustion. Sent to
    EMAIL_ADMIN (falls back to EMAIL_SENDER if not set).

    Args:
        subject: Email subject line
        message: Plain-text message body

    Returns:
        True if sent successfully, False otherwise
    """
    if not EMAIL_SENDER or not EMAIL_APP_PASSWORD or not EMAIL_ADMIN:
        print("WARNING: Cannot send admin alert — email not configured")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"[LPSC Monitor Alert] {subject}"
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_ADMIN

    # Simple HTML body with the alert message
    html = f"""<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #c53030; color: white; padding: 16px 20px; border-radius: 8px 8px 0 0;">
    <h2 style="margin: 0; font-size: 18px;">LPSC Monitor Alert</h2>
  </div>
  <div style="padding: 20px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px;">
    <p style="font-size: 14px; color: #333; line-height: 1.6; white-space: pre-line;">{message}</p>
  </div>
  <p style="text-align: center; font-size: 12px; color: #a0aec0; margin-top: 16px;">
    Sent by LPSC Bulletin Monitor</p>
</div>"""

    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.sendmail(EMAIL_SENDER, [EMAIL_ADMIN], msg.as_string())

        print(f"Admin alert sent to: {EMAIL_ADMIN}")
        return True

    except Exception as e:
        print(f"WARNING: Failed to send admin alert: {e}")
        return False
