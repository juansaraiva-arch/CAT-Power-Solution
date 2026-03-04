"""
auth_email.py — OTP email sender for CAT Power Solution
==========================================================
Sends verification codes via Gmail SMTP using credentials
from st.secrets["email"].
"""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import streamlit as st


def send_otp_email(
    recipient_email: str, otp_code: str, recipient_name: str = ""
) -> tuple[bool, str]:
    """
    Send OTP verification email via Gmail SMTP.
    Credentials loaded from st.secrets["email"].
    Returns (success: bool, error_message: str).
    """
    try:
        cfg = st.secrets["email"]
        sender = cfg["sender_address"]
        password = cfg["sender_password"]
        host = cfg["smtp_host"]
        port = int(cfg["smtp_port"])

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "CAT Power Solution — Your verification code"
        msg["From"] = f"CAT Power Solution <{sender}>"
        msg["To"] = recipient_email

        # Plain text fallback
        text_body = f"""
Your CAT Power Solution verification code is:

    {otp_code}

This code expires in 15 minutes.
If you did not request this, please ignore this email.

— CAT Power Solution System
"""

        # HTML body
        greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"
        html_body = f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:20px">
  <div style="max-width:480px;margin:0 auto;background:#fff;border-radius:8px;
              overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)">
    <!-- Header -->
    <div style="background:#12233A;padding:24px 32px">
      <span style="color:#FFCC00;font-size:22px;font-weight:bold">CAT</span>
      <span style="color:white;font-size:16px;margin-left:8px">Power Solution</span>
    </div>
    <!-- Body -->
    <div style="padding:32px">
      <p style="color:#333;font-size:16px;margin-top:0">{greeting}</p>
      <p style="color:#333;font-size:16px">Your verification code is:</p>
      <div style="background:#f8f8f8;border:2px solid #FFCC00;border-radius:6px;
                  padding:20px;text-align:center;margin:24px 0">
        <span style="font-size:36px;font-weight:bold;letter-spacing:12px;
                     color:#12233A;font-family:monospace">{otp_code}</span>
      </div>
      <p style="color:#666;font-size:14px">
        This code expires in <strong>15 minutes</strong>.
      </p>
      <p style="color:#666;font-size:14px">
        If you did not request this code, please ignore this email.
      </p>
    </div>
    <!-- Footer -->
    <div style="background:#f4f4f4;padding:16px 32px;border-top:1px solid #ddd">
      <p style="color:#999;font-size:12px;margin:0">
        CAT Power Solution — Internal Tool
      </p>
    </div>
  </div>
</body>
</html>
"""
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(sender, password)
            server.sendmail(sender, recipient_email, msg.as_string())

        return True, ""

    except smtplib.SMTPAuthenticationError:
        return False, "Email authentication failed. Check SMTP credentials in secrets."
    except smtplib.SMTPException as e:
        return False, f"Email send error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"
