import jwt
import datetime
from flask import current_app
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time

# ===============================
# 1️⃣ Generate Verification Token
# ===============================
def generate_verification_token(email):
    """Generate JWT token that expires in 1 hour for email verification."""
    try:
        payload = {
            "email": email,
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1),
            "iat": datetime.datetime.utcnow()
        }
        token = jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")
        return token
    except Exception as e:
        current_app.logger.error(f"Token generation failed: {e}")
        return None


# ===============================
# 2️⃣ Verify Token
# ===============================
def verify_token(token):
    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        return payload.get("email")
    except jwt.ExpiredSignatureError:
        current_app.logger.warning("Verification token expired.")
        return None
    except jwt.InvalidTokenError:
        current_app.logger.warning("Invalid verification token.")
        return None
    except Exception as e:
        current_app.logger.warning(f"Token verification error: {str(e)}")
        return None

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "oluwaseyiogunsola90@gmail.com"
SMTP_PASS = "jbjd kpab wsok fugr"  # Gmail App Password
SENDER = SMTP_USER


def send_verification_email(to_email, verification_url, retries=3, delay=2):
    subject = "Verify Your Email - StudyHub ✅"  # UTF-8 safe

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background-color: #f4f8fb; padding: 20px;">
        <div style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 10px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
            <h2 style="color: #0d6efd; text-align: center;">Welcome to StudyHub!</h2>
            <p style="font-size: 16px;">Thank you for joining StudyHub! Please verify your email by clicking the button below:</p>
            <div style="text-align: center; margin: 25px 0;">
                <a href="{verification_url}" 
                   style="background-color: #0d6efd; color: #ffffff; text-decoration: none; padding: 12px 25px; border-radius: 5px; font-weight: bold; display: inline-block;">
                   Verify Email
                </a>
            </div>
            <p style="font-size: 13px; color: #555; text-align: center;">
              This verification link expires in 1 hour.<br>
              If you didn’t request this, you can ignore this message.
            </p>
        </div>
      </body>
    </html>
    """

    text_content = f"Please verify your email by clicking this link: {verification_url}"

    # ✅ Combine message with UTF-8 encoding
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = to_email
    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # 🔄 Retry loop
    for attempt in range(1, retries + 1):
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SENDER, [to_email], msg.as_string().encode("utf-8"))
                print(f"✅ Verification email sent to {to_email}")
                return  # success, exit function
        except Exception as e:
            print(f"❌ Attempt {attempt} failed: {e}")
            if attempt < retries:
                print(f"⏳ Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                print("⚠️ All retry attempts failed. Email not sent.")            