# ==============================================================
# utils/alert_manager.py
# Bộ não trung tâm xử lý cảnh báo vi phạm.
# Kết nối: camera → chống spam → lưu DB → đếm → chụp ảnh → Telegram/Email
# ==============================================================

import os
import time
import threading
import cv2
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from database import (
    add_alert,
    count_recent_alerts,
    count_recent_high_alerts,
    get_driver_by_id,
    update_alert_sent_status,
    get_alert_settings,
)
from utils.logger import setup_logger
from utils.telegram_bot import format_alert_message, send_text_alert, send_photo_alert
from utils.email_sender import send_email_alert, send_email_with_image

load_dotenv()

logger = setup_logger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

CAPTURES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "captures")

ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "30"))
ESCALATION_COOLDOWN_SECONDS = int(os.getenv("ESCALATION_COOLDOWN_SECONDS", "300"))
ESCALATION_THRESHOLD_COUNT = int(os.getenv("ESCALATION_THRESHOLD_COUNT", "3"))
ESCALATION_THRESHOLD_MINUTES = int(os.getenv("ESCALATION_THRESHOLD_MINUTES", "5"))

# --- Luồng escalation NHANH cho mức cao (high) ---
# Khi tài xế đang ở mức nguy hiểm cao, chỉ cần HIGH_FAST_COUNT sự kiện high
# trong cửa sổ ngắn HIGH_FAST_WINDOW_SECONDS là gửi ngay (không chờ tích lũy 5').
# Cooldown riêng cho high ngắn hơn để nhắc lại nhanh mà vẫn không spam.
# GĐ1: hardcode. GĐ2 (gộp 4B) sẽ cho chỉnh window từ trang Cài đặt.
HIGH_FAST_WINDOW_SECONDS = int(os.getenv("HIGH_FAST_WINDOW_SECONDS", "60"))
HIGH_FAST_COUNT = int(os.getenv("HIGH_FAST_COUNT", "2"))
HIGH_ESCALATION_COOLDOWN_SECONDS = int(os.getenv("HIGH_ESCALATION_COOLDOWN_SECONDS", "120"))

# Lưu timestamp lần cuối alert và escalation cho mỗi driver
# Key: "driver_id_alert_type" → Value: timestamp
_last_alert_time = {}
# Key: "driver_id" → Value: timestamp lần cuối escalation
_last_escalation_time = {}


def _is_spam(driver_id: str, alert_type: str) -> bool:
    """Kiểm tra alert này có bị spam không (cùng driver + loại trong 30s)."""
    key = f"{driver_id}_{alert_type}"
    now = time.time()
    last_time = _last_alert_time.get(key, 0)

    return now - last_time < ALERT_COOLDOWN_SECONDS


def _mark_alert_saved(driver_id: str, alert_type: str) -> None:
    """Bắt đầu cooldown sau khi cảnh báo đã thực sự được lưu."""
    _last_alert_time[f"{driver_id}_{alert_type}"] = time.time()


def _is_escalation_cooldown(driver_id: str, cooldown_seconds: int = ESCALATION_COOLDOWN_SECONDS) -> bool:
    """
    Kiểm tra driver này đang trong cooldown sau escalation không.

    cooldown_seconds khác nhau theo luồng: high dùng 120s (nhắc lại nhanh),
    luồng thường dùng 300s. Dùng chung một mốc thời gian _last_escalation_time.
    """
    now = time.time()
    last_time = _last_escalation_time.get(driver_id, 0)
    return now - last_time < cooldown_seconds


def _cfg_int(value, default: int) -> int:
    """Ép cấu hình về int dương; sai/thiếu → dùng default (hằng số GĐ1)."""
    try:
        result = int(value)
        return result if result > 0 else default
    except (TypeError, ValueError):
        return default


def _capture_evidence(frame, driver_id: str, alert_type: str) -> str | None:
    """
    Chụp ảnh minh chứng từ frame camera hiện tại.

    Returns:
        str: đường dẫn file ảnh nếu thành công, None nếu lỗi
    """
    try:
        os.makedirs(CAPTURES_DIR, exist_ok=True)
        timestamp = datetime.now(VN_TZ).strftime("%Y%m%d_%H%M%S")
        filename = f"{driver_id[:8]}_{alert_type}_{timestamp}.jpg"
        filepath = os.path.join(CAPTURES_DIR, filename)
        cv2.imwrite(filepath, frame)
        logger.info(f"Đã chụp ảnh minh chứng: {filename}")
        return filepath
    except Exception as e:
        logger.error(f"Chụp ảnh minh chứng thất bại: {e}")
        return None


def _send_notifications(driver_name: str, alert_type: str, count: int,
                        vehicle: str, ear: float, mar: float, image_path: str,
                        alert_id: str = None, chat_id: str = None, to_email: str = None):
    """
    Gửi Telegram + Email trong thread riêng.
    Hàm này được gọi từ threading.Thread, không block camera.
    Sau khi gửi thành công, cập nhật sent_to_manager = true trong DB.

    chat_id / to_email: người nhận lấy từ alert_settings; None → fallback .env.
    """
    message = format_alert_message(
        driver_name=driver_name,
        alert_type=alert_type,
        count=count,
        vehicle=vehicle,
        ear=ear,
        mar=mar,
    )

    subject = f"[DriverGuard AI] Canh bao vi pham - {driver_name}"

    telegram_ok = False
    email_ok = False
    try:
        if image_path:
            telegram_ok = bool(send_photo_alert(image_path, message, chat_id=chat_id))
            email_ok = bool(send_email_with_image(subject=subject, body=message, image_path=image_path, to_email=to_email))
        else:
            telegram_ok = bool(send_text_alert(message, chat_id=chat_id))
            email_ok = bool(send_email_alert(subject=subject, body=message, to_email=to_email))
    except Exception as e:
        logger.error(f"Gửi thông báo thất bại cho {driver_name}: {e}")

    sent_ok = telegram_ok or email_ok
    if sent_ok:
        logger.info(f"Đã gửi thông báo escalation cho {driver_name} (telegram={telegram_ok}, email={email_ok})")
    else:
        logger.error(f"Gửi thông báo thất bại hoàn toàn cho {driver_name} (telegram={telegram_ok}, email={email_ok})")

    if alert_id:
        update_alert_sent_status(alert_id, sent_ok)


def _escalate(driver_id: str, alert_type: str, ear: float, mar: float,
              frame, alert_id: str, count: int, cooldown_seconds: int,
              chat_id: str = None, to_email: str = None) -> None:
    """
    Thực hiện escalation: tôn trọng cooldown → chụp ảnh → gửi cho người nhận
    đã đăng ký (chat_id/to_email từ alert_settings; token/SMTP vẫn từ .env),
    chạy thread riêng.

    Dùng chung cho cả luồng nhanh (high, cooldown ngắn) và luồng chậm.
    """
    if _is_escalation_cooldown(driver_id, cooldown_seconds):
        logger.info(f"Driver {driver_id[:8]} đang trong cooldown escalation, bỏ qua")
        return

    _last_escalation_time[driver_id] = time.time()

    driver = get_driver_by_id(driver_id)
    driver_name = driver.get("full_name", "Không xác định") if driver else "Không xác định"
    vehicle = None

    logger.critical(
        f"ESCALATION: driver={driver_name} | type={alert_type} | count={count}"
    )

    image_path = None
    if frame is not None:
        image_path = _capture_evidence(frame, driver_id, alert_type)

    notify_thread = threading.Thread(
        target=_send_notifications,
        args=(driver_name, alert_type, count, vehicle, ear, mar, image_path,
              alert_id, chat_id, to_email),
        daemon=True,
    )
    notify_thread.start()


def process_violation(
    driver_id: str,
    alert_type: str,
    alert_level: str,
    ear: float = None,
    mar: float = None,
    head_status: str = None,
    frame=None,
    vehicle_id: str = None,
    shift_id: str = None,
) -> None:
    """
    Xử lý 1 vi phạm từ camera AI.
    Luồng: chống spam → lưu DB → đếm → chụp ảnh → gửi Telegram/Email.

    Args:
        driver_id: UUID tài xế
        alert_type: EYES_CLOSED | YAWNING | HEAD_DOWN | DROWSY | UNKNOWN_DRIVER
        alert_level: low | medium | high
        ear: giá trị EAR tại thời điểm vi phạm
        mar: giá trị MAR tại thời điểm vi phạm
        head_status: trạng thái đầu (NORMAL / HEAD DOWN)
        frame: frame ảnh từ camera (numpy array) để chụp minh chứng
        vehicle_id: UUID xe (optional)
        shift_id: UUID ca làm (optional)
    """
    # --- 1. Chống spam ---
    if _is_spam(driver_id, alert_type):
        return

    logger.warning(
        f"Vi phạm: driver={driver_id[:8]} | type={alert_type} | level={alert_level}"
    )

    # --- 2. Lưu DB ---
    alert_data = {
        "driver_id": driver_id,
        "alert_type": alert_type,
        "alert_level": alert_level,
        "alert_message": f"Phát hiện {alert_type}",
    }
    if ear is not None:
        alert_data["ear_value"] = round(ear, 4)
    if mar is not None:
        alert_data["mar_value"] = round(mar, 4)
    if head_status:
        alert_data["head_status"] = head_status
    if vehicle_id:
        alert_data["vehicle_id"] = vehicle_id
    if shift_id:
        alert_data["shift_id"] = shift_id

    success, result_msg = add_alert(alert_data)
    if not success:
        logger.error(f"Lưu alert DB thất bại: {result_msg}")
        return

    alert_id = result_msg if success else None
    _mark_alert_saved(driver_id, alert_type)

    # --- 3. Đọc cấu hình (GĐ2: chỉnh từ trang Cài đặt; thiếu → hằng số GĐ1) ---
    settings = get_alert_settings()
    fast_window = _cfg_int(settings.get("high_fast_window_seconds"), HIGH_FAST_WINDOW_SECONDS)
    fast_count = _cfg_int(settings.get("high_fast_count"), HIGH_FAST_COUNT)
    high_cooldown = _cfg_int(settings.get("high_escalation_cooldown_seconds"), HIGH_ESCALATION_COOLDOWN_SECONDS)
    chat_id = settings.get("telegram_chat_id")
    to_email = settings.get("manager_email")

    # --- 4. LUỒNG NHANH: mức high, >= fast_count trong cửa sổ ngắn ---
    if alert_level == "high":
        high_count = count_recent_high_alerts(driver_id, fast_window)
        logger.info(f"Số high trong {fast_window}s: {high_count}")
        if high_count >= fast_count:
            _escalate(driver_id, alert_type, ear, mar, frame, alert_id,
                      high_count, high_cooldown, chat_id, to_email)
            return

    # --- 5. LUỒNG CHẬM: tích lũy medium+high trong cửa sổ phút ---
    count = count_recent_alerts(driver_id, ESCALATION_THRESHOLD_MINUTES)
    logger.info(f"Số vi phạm trong {ESCALATION_THRESHOLD_MINUTES} phút: {count}")
    if count >= ESCALATION_THRESHOLD_COUNT:
        _escalate(driver_id, alert_type, ear, mar, frame, alert_id,
                  count, ESCALATION_COOLDOWN_SECONDS, chat_id, to_email)
