# ==============================================================
# utils/email_sender.py
# Gửi cảnh báo vi phạm qua Email (SMTP).
# Dùng smtplib + email (Python standard library, không cần cài thêm).
# ==============================================================

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

from dotenv import load_dotenv

from utils.logger import setup_logger

load_dotenv()

logger = setup_logger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
MANAGER_EMAIL = os.getenv("MANAGER_EMAIL")


def _check_config() -> bool:
    """Kiểm tra đã cấu hình SMTP trong .env chưa."""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, MANAGER_EMAIL]):
        logger.warning("Chưa cấu hình SMTP trong .env — bỏ qua gửi email")
        return False
    return True


def send_email_alert(subject: str, body: str) -> bool:
    """
    Gửi email text thuần đến quản lý.

    Args:
        subject: tiêu đề email
        body: nội dung email

    Returns:
        True nếu gửi thành công, False nếu lỗi
    """
    if not _check_config():
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = MANAGER_EMAIL
        msg["Subject"] = subject

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, MANAGER_EMAIL, msg.as_string())

        logger.info(f"Đã gửi email cảnh báo đến {MANAGER_EMAIL}")
        return True

    except Exception as e:
        logger.error(f"Gửi email thất bại: {e}")
        return False


def send_email_with_image(subject: str, body: str, image_path: str) -> bool:
    """
    Gửi email HTML kèm ảnh minh chứng đính kèm đến quản lý.

    Args:
        subject: tiêu đề email
        body: nội dung mô tả vi phạm
        image_path: đường dẫn file ảnh minh chứng

    Returns:
        True nếu gửi thành công, False nếu lỗi
    """
    if not _check_config():
        return False

    if not os.path.exists(image_path):
        logger.error(f"Không tìm thấy file ảnh: {image_path}")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = MANAGER_EMAIL
        msg["Subject"] = subject

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #e74c3c;">CANH BAO VI PHAM - DriverGuard AI</h2>
            <pre style="font-size: 14px; line-height: 1.6;">{body}</pre>
            <hr>
            <p><strong>Anh minh chung:</strong></p>
            <img src="cid:evidence" style="max-width: 640px; border: 2px solid #e74c3c; border-radius: 8px;">
            <hr>
            <p style="color: #888; font-size: 12px;">
                Email tu dong tu he thong DriverGuard AI. Vui long khong tra loi email nay.
            </p>
        </body>
        </html>
        """
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with open(image_path, "rb") as img_file:
            img = MIMEImage(img_file.read())
            img.add_header("Content-ID", "<evidence>")
            img.add_header(
                "Content-Disposition", "inline",
                filename=os.path.basename(image_path),
            )
            msg.attach(img)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, MANAGER_EMAIL, msg.as_string())

        logger.info(f"Đã gửi email + ảnh cảnh báo đến {MANAGER_EMAIL}")
        return True

    except Exception as e:
        logger.error(f"Gửi email + ảnh thất bại: {e}")
        return False
