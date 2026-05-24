# ==============================================================
# utils/telegram_bot.py
# Gửi cảnh báo vi phạm qua Telegram Bot API.
# Dùng requests gọi trực tiếp API, không cần thư viện bên thứ 3.
# ==============================================================

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from utils.logger import setup_logger

load_dotenv()

logger = setup_logger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

ALERT_TYPE_LABELS = {
    "EYES_CLOSED": "Nhắm mắt liên tục",
    "YAWNING": "Ngáp nhiều lần",
    "HEAD_DOWN": "Gục đầu",
    "DROWSY": "Buồn ngủ",
    "UNKNOWN_DRIVER": "Tài xế không xác định",
}


def _check_config() -> bool:
    """Kiểm tra đã cấu hình token và chat_id trong .env chưa."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong .env")
        return False
    return True


def format_alert_message(
    driver_name: str,
    alert_type: str,
    count: int,
    vehicle: str = None,
    ear: float = None,
    mar: float = None,
) -> str:
    """
    Tạo nội dung tin nhắn cảnh báo chuẩn.

    Args:
        driver_name: tên tài xế
        alert_type: loại vi phạm (EYES_CLOSED, YAWNING, HEAD_DOWN, DROWSY, UNKNOWN_DRIVER)
        count: số lần vi phạm trong 5 phút
        vehicle: biển số xe (optional)
        ear: giá trị EAR tại thời điểm vi phạm (optional)
        mar: giá trị MAR tại thời điểm vi phạm (optional)

    Returns:
        str: tin nhắn đã format sẵn
    """
    now_vn = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    type_label = ALERT_TYPE_LABELS.get(alert_type, alert_type)

    lines = [
        "🚨 CẢNH BÁO VI PHẠM - DriverGuard AI",
        "",
        f"👤 Tài xế: {driver_name or 'Không xác định'}",
    ]

    if vehicle:
        lines.append(f"🚗 Xe: {vehicle}")

    lines.append(f"⚠️ Loại: {type_label} ({alert_type})")

    metrics = []
    if ear is not None:
        metrics.append(f"EAR: {ear:.2f}")
    if mar is not None:
        metrics.append(f"MAR: {mar:.2f}")
    if metrics:
        lines.append(f"📊 {' | '.join(metrics)}")

    lines.extend([
        f"🔄 Số lần trong 5 phút: {count}",
        f"🕐 Thời gian: {now_vn}",
    ])

    return "\n".join(lines)


def send_text_alert(message: str) -> bool:
    """
    Gửi tin nhắn text qua Telegram.

    Args:
        message: nội dung tin nhắn

    Returns:
        True nếu gửi thành công, False nếu lỗi
    """
    if not _check_config():
        return False

    try:
        response = requests.post(
            f"{BASE_URL}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

        if response.ok:
            logger.info(f"Đã gửi Telegram text alert thành công")
            return True

        logger.error(f"Telegram API lỗi: {response.status_code} - {response.text}")
        return False

    except requests.RequestException as e:
        logger.error(f"Gửi Telegram thất bại: {e}")
        return False


def send_photo_alert(image_path: str, caption: str = None) -> bool:
    """
    Gửi ảnh minh chứng kèm caption qua Telegram.

    Args:
        image_path: đường dẫn file ảnh (vd: static/captures/abc.jpg)
        caption: mô tả đi kèm ảnh (optional, tối đa 1024 ký tự)

    Returns:
        True nếu gửi thành công, False nếu lỗi
    """
    if not _check_config():
        return False

    if not os.path.exists(image_path):
        logger.error(f"Không tìm thấy file ảnh: {image_path}")
        return False

    try:
        with open(image_path, "rb") as photo:
            data = {"chat_id": TELEGRAM_CHAT_ID}
            if caption:
                data["caption"] = caption[:1024]

            response = requests.post(
                f"{BASE_URL}/sendPhoto",
                data=data,
                files={"photo": photo},
                timeout=30,
            )

        if response.ok:
            logger.info(f"Đã gửi Telegram photo alert: {image_path}")
            return True

        logger.error(f"Telegram API lỗi: {response.status_code} - {response.text}")
        return False

    except requests.RequestException as e:
        logger.error(f"Gửi Telegram photo thất bại: {e}")
        return False
