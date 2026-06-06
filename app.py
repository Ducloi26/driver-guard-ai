from flask import Flask, render_template, Response, jsonify, request, redirect, url_for, flash, session
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
import cv2
import csv
import io
import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import mediapipe as mp
import time
import threading
import unicodedata
from datetime import datetime
from database import (
    clean_form_data,
    clean_vehicle_form_data,
    clean_shift_form_data,
    upload_driver_image,
    get_all_drivers,
    attach_current_shift_to_drivers,
    attach_avatar_urls_to_drivers,
    add_driver_and_get_id,
    get_all_vehicles,
    attach_current_shift_to_vehicles,
    get_vehicle_stats,
    add_vehicle as add_vehicle_record,
    get_vehicle_by_id,
    update_vehicle,
    delete_vehicle,
    get_all_shifts,
    get_shift_stats,
    add_shift as add_shift_record,
    get_all_alerts,
    get_alert_statistics,
    get_dashboard_stats,
    get_drivers_with_face_encoding,
    get_current_shift_by_driver,
    get_admin_by_username,
    update_admin_password,
    get_driver_by_id,
    update_driver,
    delete_driver,
    get_driver_stats,
    clean_settings_form_data,
    get_alert_settings,
    update_alert_settings,
    ALERT_SETTINGS_DEFAULTS,
)
from models.ear_calculator import calculate_ear, LEFT_EYE_INDEXES, RIGHT_EYE_INDEXES
from models.mar_calculator import calculate_mar, MOUTH_INDEXES
from models.head_pose import detect_head_down
from models.drowsiness_detection import DrowsinessDetector
from models.face_recognition_model import (
    recognize_driver_from_frame,
    rebuild_all_face_encodings,
    build_face_encoding_for_driver,
    append_face_encoding_from_frame,
)
from utils.alert_manager import process_violation
from utils.logger import setup_logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "frontend"),
    static_folder=os.path.join(BASE_DIR, "frontend", "static")
)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "driver-guard-ai-dev-secret")
logger = setup_logger(__name__)
detector = DrowsinessDetector()


def check_admin_credentials(username: str, password: str) -> bool:
    """So khớp tài khoản admin với hồ sơ trong DB (bảng profiles)."""
    admin = get_admin_by_username(username)
    if not admin or not admin.get("password_hash"):
        return False
    return check_password_hash(admin["password_hash"], password)


def login_required(view):
    """Chặn route quản lý nếu chưa đăng nhập. Trang tài xế (/camera) không dùng."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

camera_stream = None
camera_running = False
last_frame = None
last_original_camera_frame = None
known_face_drivers = []
face_recognition_frame_counter = 0
FACE_RECOGNITION_THRESHOLD = 0.8
RECOGNITION_CONFIRM_FRAMES = 2
UNKNOWN_CONFIRM_FRAMES = 5
FACE_RECOGNITION_INTERVAL_SECONDS = 0.8
pending_recognition_key = None
pending_recognition_count = 0
recognition_worker_thread = None
recognition_worker_running = False
latest_recognition_frame = None
latest_recognition_frame_lock = threading.Lock()
last_recognition_result = {
    "status": "NOT_READY",
    "driver": None,
    "similarity": 0.0,
    "shift": None,
}
mp_face_mesh = mp.solutions.face_mesh
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)
EYES_CLOSED_ALERT_SECONDS = 3.0
BLINK_MAX_SECONDS = 0.5

BLINK_WARNING_THRESHOLD = 15

eyes_closed_start_time = None
blink_counter = 0
tired_event_counter = 0
blink_start_time = time.time()

YAWN_CONFIRM_TIME = 10

mouth_open_detected = False
mouth_open_time = 0
yawn_counter = 0
HEAD_DOWN_THRESHOLD = 2

head_down_start_time = 0
head_down_detected = False
alert_triggered = False
current_driver_id = None

latest_ai_state = {
    "eye_status": "NO FACE",
    "mouth_status": "NORMAL",
    "head_status": "NORMAL",
    "drowsy_status": "NORMAL",
    "ear": None,
    "mar": None,
}


def reset_detection_state():
    global eyes_closed_start_time, blink_counter, tired_event_counter, blink_start_time
    global mouth_open_detected, mouth_open_time, yawn_counter
    global head_down_start_time, head_down_detected, alert_triggered
    global latest_ai_state

    eyes_closed_start_time = None
    blink_counter = 0
    tired_event_counter = 0
    blink_start_time = time.time()
    mouth_open_detected = False
    mouth_open_time = 0
    yawn_counter = 0
    head_down_start_time = 0
    head_down_detected = False
    alert_triggered = False
    detector.reset()
    latest_ai_state = {
        "eye_status": "NO FACE",
        "mouth_status": "NORMAL",
        "head_status": "NORMAL",
        "drowsy_status": "NORMAL",
        "ear": None,
        "mar": None,
    }


def apply_alert_settings_to_detector():
    """
    Nạp ngưỡng AI từ alert_settings vào detector (đọc 1 lần, cập nhật tại chỗ).

    Gọi khi bắt đầu camera và sau khi lưu Cài đặt — KHÔNG gọi trong vòng lặp
    frame (tránh query DB liên tục). Cập nhật thuộc tính tại chỗ để giữ nguyên
    state đếm thời gian của detector. eyes_seconds giữ cố định theo thiết kế
    (alert_settings không có cột này).
    """
    try:
        s = get_alert_settings()
        detector.ear_threshold = float(s.get("ear_threshold") or detector.ear_threshold)
        detector.mar_threshold = float(s.get("mar_threshold") or detector.mar_threshold)
        detector.mouth_seconds = float(s.get("yawn_seconds") or detector.mouth_seconds)
        detector.head_seconds = float(s.get("head_down_seconds") or detector.head_seconds)
        logger.info(
            f"Áp dụng ngưỡng AI: EAR<{detector.ear_threshold} MAR>{detector.mar_threshold} "
            f"yawn={detector.mouth_seconds}s head={detector.head_seconds}s"
        )
    except Exception as e:
        logger.error(f"apply_alert_settings_to_detector() lỗi: {e}")


def refresh_known_face_drivers():
    """
    Load danh sách tài xế đã có face_encoding vào RAM.

    Camera không nên query Supabase trong từng frame. Hàm này được gọi khi
    bắt đầu camera để nhận diện nhanh hơn và giảm request lên cloud.
    """
    global known_face_drivers
    known_face_drivers = get_drivers_with_face_encoding()
    return known_face_drivers


def get_recognition_key(result: dict) -> str:
    """
    Tạo key ổn định cho một kết quả nhận diện.

    Dùng để đếm số lần liên tiếp camera nhận ra cùng một tài xế. Nếu chỉ dựa
    vào từng frame riêng lẻ, UI sẽ dễ nhảy giữa RECOGNIZED/UNKNOWN khi tài xế
    quay đầu hoặc ánh sáng thay đổi.
    """
    driver = result.get("driver")
    if result.get("status") == "RECOGNIZED" and driver:
        return f"driver:{driver.get('id')}"

    return result.get("status") or "NOT_READY"


def stabilize_recognition(raw_result: dict) -> dict:
    """
    Làm mượt kết quả nhận diện qua nhiều lần đọc liên tiếp.

    Quy tắc:
      - Cùng một tài xế phải xuất hiện nhiều lần liên tiếp mới được xác nhận.
      - UNKNOWN/NO_FACE cũng phải lặp lại nhiều lần mới xóa trạng thái cũ.
      - Nhờ vậy panel không bị nhảy loạn khi tài xế quay mặt hoặc chớp sáng.
    """
    global pending_recognition_key, pending_recognition_count, last_recognition_result
    global current_driver_id

    current_key = get_recognition_key(raw_result)

    if current_key == pending_recognition_key:
        pending_recognition_count += 1
    else:
        pending_recognition_key = current_key
        pending_recognition_count = 1

    if raw_result.get("status") == "RECOGNIZED":
        if pending_recognition_count >= RECOGNITION_CONFIRM_FRAMES:
            last_recognition_result = raw_result
            driver = raw_result.get("driver")
            if driver:
                new_id = driver.get("id")
                if new_id != current_driver_id:
                    reset_detection_state()
                current_driver_id = new_id
        return last_recognition_result

    if raw_result.get("status") in ("UNKNOWN_DRIVER", "NO_FACE"):
        if pending_recognition_count >= UNKNOWN_CONFIRM_FRAMES:
            last_recognition_result = raw_result
            if current_driver_id is not None:
                reset_detection_state()
            current_driver_id = None
        return last_recognition_result

    last_recognition_result = raw_result
    return last_recognition_result


def resize_frame_for_recognition(frame):
    """
    Giảm kích thước frame trước khi đưa vào DeepFace.

    DeepFace chạy nặng hơn MediaPipe. Resize frame giúp nhận diện nhanh hơn,
    trong khi vẫn đủ rõ để detect khuôn mặt ở webcam laptop.
    """
    if frame is None:
        return None

    height, width = frame.shape[:2]
    max_width = 640

    if width <= max_width:
        return frame.copy()

    scale = max_width / width
    new_size = (max_width, int(height * scale))
    return cv2.resize(frame, new_size)


def update_latest_recognition_frame(frame):
    """
    Lưu frame mới nhất cho thread nhận diện nền.

    Video stream không gọi DeepFace trực tiếp nữa, chỉ đưa frame mới nhất vào
    biến dùng chung. Thread nền sẽ tự lấy frame này để nhận diện định kỳ.
    """
    global latest_recognition_frame

    prepared_frame = resize_frame_for_recognition(frame)
    if prepared_frame is None:
        return

    with latest_recognition_frame_lock:
        latest_recognition_frame = prepared_frame


def get_latest_recognition_frame():
    """
    Lấy bản copy frame mới nhất để thread nền xử lý an toàn.
    """
    with latest_recognition_frame_lock:
        if latest_recognition_frame is None:
            return None
        return latest_recognition_frame.copy()


def recognition_worker_loop():
    """
    Thread nền nhận diện tài xế liên tục nhưng không chặn video stream.

    Nếu tài xế đổi người, worker vẫn phát hiện ở lần quét kế tiếp. Khoảng quét
    hiện tại là FACE_RECOGNITION_INTERVAL_SECONDS để cân bằng giữa mượt và realtime.
    """
    global recognition_worker_running

    while recognition_worker_running:
        try:
            frame_for_recognition = get_latest_recognition_frame()

            if known_face_drivers and frame_for_recognition is not None:
                raw_recognition = recognize_driver_from_frame(
                    frame_for_recognition,
                    known_face_drivers,
                    threshold=FACE_RECOGNITION_THRESHOLD
                )

                if raw_recognition.get("driver"):
                    raw_recognition["shift"] = get_current_shift_by_driver(
                        raw_recognition["driver"].get("id")
                    )
                else:
                    raw_recognition["shift"] = None

                stabilize_recognition(raw_recognition)

        except Exception as e:
            print("Lỗi recognition_worker_loop:", e)

        time.sleep(FACE_RECOGNITION_INTERVAL_SECONDS)


def start_recognition_worker():
    """
    Khởi động thread nhận diện nền nếu chưa chạy.
    """
    global recognition_worker_thread, recognition_worker_running

    if recognition_worker_thread is not None and recognition_worker_thread.is_alive():
        return

    recognition_worker_running = True
    recognition_worker_thread = threading.Thread(
        target=recognition_worker_loop,
        daemon=True
    )
    recognition_worker_thread.start()


def stop_recognition_worker():
    """
    Dừng thread nhận diện nền.
    """
    global recognition_worker_running
    recognition_worker_running = False


def format_recognition_text(result: dict) -> tuple[str, str, str]:
    """
    Chuyển kết quả nhận diện thành text ngắn để vẽ lên frame camera.

    Returns:
        tuple: (driver_text, vehicle_text, shift_text)
    """
    status = result.get("status")
    driver = result.get("driver")
    similarity = result.get("similarity", 0.0)
    shift = result.get("shift")

    if status == "RECOGNIZED" and driver:
        driver_text = f"DRIVER: {driver.get('full_name', 'Unknown')} ({similarity * 100:.1f}%)"
        vehicle = shift.get("vehicles") if shift else None
        vehicle_text = f"VEHICLE: {vehicle.get('plate_number') if vehicle else 'Not assigned'}"
        shift_text = f"SHIFT: {shift.get('shift_name') if shift else 'Not assigned'}"
        return driver_text, vehicle_text, shift_text

    if status == "UNKNOWN_DRIVER":
        return f"DRIVER: UNKNOWN ({similarity * 100:.1f}%)", "VEHICLE: --", "SHIFT: --"

    if status == "NO_FACE":
        return "DRIVER: NO FACE", "VEHICLE: --", "SHIFT: --"

    return "DRIVER: NOT READY", "VEHICLE: --", "SHIFT: --"


def build_camera_status_payload() -> dict:
    """
    Tạo JSON trạng thái camera cho UI bên phải.

    Hàm này đọc last_recognition_result đang được cập nhật trong generate_frames().
    Frontend gọi /camera_status định kỳ để panel Camera AI đổi theo tài xế thật.
    """
    status = last_recognition_result.get("status")
    driver = last_recognition_result.get("driver")
    similarity = last_recognition_result.get("similarity", 0.0)
    shift = last_recognition_result.get("shift")
    vehicle = shift.get("vehicles") if shift else None

    if status == "RECOGNIZED" and driver:
        start_time = shift.get("start_time") if shift else None
        end_time = shift.get("end_time") if shift else None
        shift_time = "--"
        if start_time or end_time:
            shift_time = f"{start_time or '--:--'} - {end_time or '--:--'}"

        return {
            "status": "RECOGNIZED",
            "driver_id": driver.get("id"),
            "driver_name": driver.get("full_name") or "Không xác định",
            "driver_code": driver.get("driver_code"),
            "phone": driver.get("phone") or "--",
            "confidence": round(similarity * 100, 1),
            "vehicle_plate": vehicle.get("plate_number") if vehicle else "Chưa gán",
            "shift_name": shift.get("shift_name") if shift else "Chưa gán",
            "shift_time": shift_time,
            "known_faces": len(known_face_drivers),
            "ai": latest_ai_state,
        }

    if status == "UNKNOWN_DRIVER":
        return {
            "status": "UNKNOWN_DRIVER",
            "driver_id": None,
            "driver_name": "Không xác định",
            "driver_code": None,
            "phone": "--",
            "confidence": round(similarity * 100, 1),
            "vehicle_plate": "--",
            "shift_name": "--",
            "shift_time": "--",
            "known_faces": len(known_face_drivers),
            "ai": latest_ai_state,
        }

    return {
        "status": status or "NOT_READY",
        "driver_id": None,
        "driver_name": "Đang chờ nhận diện",
        "driver_code": None,
        "phone": "--",
        "confidence": 0.0,
        "vehicle_plate": "--",
        "shift_name": "--",
        "shift_time": "--",
        "known_faces": len(known_face_drivers),
        "ai": latest_ai_state,
    }


def to_camera_text(value) -> str:
    """
    Chuyển text tiếng Việt sang ASCII trước khi vẽ bằng cv2.putText.

    OpenCV Hershey font không hỗ trợ Unicode, nên nếu vẽ trực tiếp
    "Nguyễn Đức Khang" sẽ bị thành "Nguy???". Dữ liệu gốc vẫn giữ tiếng Việt,
    chỉ phần chữ trên frame camera được đổi thành không dấu.
    """
    text = str(value).replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return ascii_text


def generate_frames():
    global camera_stream, camera_running, last_frame, last_original_camera_frame
    global eyes_closed_start_time, blink_counter, tired_event_counter, blink_start_time
    global mouth_open_detected, mouth_open_time, yawn_counter
    global head_down_start_time, head_down_detected
    global alert_triggered
    global face_recognition_frame_counter, last_recognition_result
    global latest_ai_state

    while camera_running:
        if camera_stream is None or not camera_stream.isOpened():
            break

        success, frame = camera_stream.read()

        if not success or frame is None:
            break

        try:
            frame = cv2.flip(frame, 1)

            original_frame = frame.copy()
            ai_frame = frame.copy()
            last_original_camera_frame = original_frame.copy()

            # Chỉ cập nhật frame mới nhất cho thread nhận diện nền.
            # DeepFace không chạy trực tiếp trong vòng lặp video để tránh lag.
            update_latest_recognition_frame(frame)

            rgb_frame = cv2.cvtColor(ai_frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb_frame)

            left_ear = None
            right_ear = None
            ear = None
            mar = None

            eye_status = "NO FACE"
            mouth_status = "NORMAL"
            head_status = "NORMAL"
            drowsy_status = "NORMAL"
            send_alert = False

            if results.multi_face_landmarks:
                for face_landmarks in results.multi_face_landmarks:
                    height, width, _ = ai_frame.shape
                    current_time = time.time()

                    head_down_now = detect_head_down(face_landmarks, width, height)
                    head_status = "HEAD DOWN" if head_down_now else "NORMAL"

                    left_eye = []
                    right_eye = []
                    mouth_points = []

                    for index in LEFT_EYE_INDEXES:
                        landmark = face_landmarks.landmark[index]
                        x = int(landmark.x * width)
                        y = int(landmark.y * height)

                        left_eye.append((x, y))
                        cv2.circle(ai_frame, (x, y), 3, (0, 255, 0), -1)

                    for index in RIGHT_EYE_INDEXES:
                        landmark = face_landmarks.landmark[index]
                        x = int(landmark.x * width)
                        y = int(landmark.y * height)

                        right_eye.append((x, y))
                        cv2.circle(ai_frame, (x, y), 3, (0, 255, 255), -1)

                    for index in MOUTH_INDEXES:
                        landmark = face_landmarks.landmark[index]
                        x = int(landmark.x * width)
                        y = int(landmark.y * height)

                        mouth_points.append((x, y))
                        cv2.circle(ai_frame, (x, y), 3, (255, 0, 255), -1)

                    if len(left_eye) == 6 and len(right_eye) == 6:
                        left_ear = calculate_ear(left_eye)
                        right_ear = calculate_ear(right_eye)
                        ear = (left_ear + right_ear) / 2.0
                        eye_status = "EYES CLOSED" if ear < detector.ear_threshold else "EYES OPEN"

                    if len(mouth_points) == 6:
                        mar = calculate_mar(mouth_points)

                    # --- Quyết định buồn ngủ tập trung (luật >=2/3 chỉ số) ---
                    if ear is not None:
                        result = detector.update(
                            ear,
                            mar if mar is not None else 0.0,
                            head_down_now,
                            current_time,
                        )
                        if mar is not None:
                            mouth_status = "YAWNING" if result["mouth_breaching"] else (
                                "MOUTH OPEN" if mar > detector.mar_threshold else "NORMAL")
                        if result["alert_type"] is not None:
                            send_alert = True
                            alert_type = result["alert_type"]
                            alert_level = result["alert_level"]
                            drowsy_status = "DROWSY" if alert_level == "high" else "TIRED"

                    mp_drawing.draw_landmarks(
                        image=ai_frame,
                        landmark_list=face_landmarks,
                        connections=mp_face_mesh.FACEMESH_TESSELATION,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_tesselation_style()
                    )

                    mp_drawing.draw_landmarks(
                        image=ai_frame,
                        landmark_list=face_landmarks,
                        connections=mp_face_mesh.FACEMESH_CONTOURS,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_contours_style()
                    )

            original_frame = cv2.resize(original_frame, (480, 360))
            ai_frame = cv2.resize(ai_frame, (480, 360))

            cv2.putText(original_frame, "CAMERA GOC", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            cv2.putText(ai_frame, "FACE MESH AI", (20, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            driver_text, vehicle_text, shift_text = format_recognition_text(last_recognition_result)
            cv2.putText(original_frame, to_camera_text(driver_text), (20, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
            cv2.putText(original_frame, to_camera_text(vehicle_text), (20, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
            cv2.putText(original_frame, to_camera_text(shift_text), (20, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)

            if ear is not None:
                cv2.putText(ai_frame, f"L-EAR: {left_ear:.2f}", (20, 70),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                cv2.putText(ai_frame, f"R-EAR: {right_ear:.2f}", (20, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                cv2.putText(ai_frame, f"AVG-EAR: {ear:.2f}", (20, 130),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)

                cv2.putText(ai_frame, f"STATUS: {eye_status}", (20, 160),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (0, 0, 255) if eye_status == "EYES CLOSED" else (0, 255, 0), 2)

                cv2.putText(ai_frame, f"DROWSY: {drowsy_status}", (20, 190),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (0, 0, 255) if send_alert else (0, 255, 0), 2)

                if mar is not None:
                    cv2.putText(ai_frame, f"MAR: {mar:.2f}", (20, 280),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)

                    cv2.putText(ai_frame, f"MOUTH: {mouth_status}", (20, 310),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (0, 0, 255) if mouth_status == "YAWNING" else (0, 255, 0), 2)

                cv2.putText(ai_frame, f"HEAD: {head_status}", (20, 370),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 0, 255) if head_status == "HEAD DOWN" else (0, 255, 0), 2)

                if send_alert:
                    cv2.putText(ai_frame, "SEND ALERT TO MANAGER", (20, 340),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

                    if current_driver_id and last_recognition_result.get("status") == "RECOGNIZED":
                        shift = last_recognition_result.get("shift")

                        process_violation(
                            driver_id=current_driver_id,
                            alert_type=alert_type,
                            alert_level=alert_level,
                            ear=ear,
                            mar=mar,
                            head_status=head_status,
                            frame=original_frame,
                            vehicle_id=shift.get("vehicle_id") if shift else None,
                            shift_id=shift.get("id") if shift else None,
                        )
                latest_ai_state = {
                    "eye_status": eye_status,
                    "mouth_status": mouth_status,
                    "head_status": head_status,
                    "drowsy_status": drowsy_status,
                    "ear": round(ear, 3) if ear is not None else None,
                    "mar": round(mar, 3) if mar is not None else None,
                }

            else:
                latest_ai_state = {
                    "eye_status": "NO FACE",
                    "mouth_status": "NORMAL",
                    "head_status": "NORMAL",
                    "drowsy_status": "NORMAL",
                    "ear": None,
                    "mar": None,
                }
                cv2.putText(ai_frame, "NO FACE DETECTED", (20, 80),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

            combined_frame = cv2.hconcat([original_frame, ai_frame])
            last_frame = combined_frame.copy()

            ret, buffer = cv2.imencode(".jpg", combined_frame)

            if not ret:
                continue

            frame_bytes = buffer.tobytes()

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )

        except Exception as e:
            logger.error(f"Lỗi generate_frames: {e}")
            break
@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
@app.route("/login.html", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if check_admin_credentials(username, password):
            session["user"] = username
            return redirect(url_for("dashboard"))
        flash("Sai tên đăng nhập hoặc mật khẩu", "error")
        return render_template("login.html")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/start_camera", methods=["POST"])
def start_camera():
    global camera_stream, camera_running, face_recognition_frame_counter, last_recognition_result
    global pending_recognition_key, pending_recognition_count
    global latest_recognition_frame

    if camera_running:
        return jsonify({
            "status": "already_running",
            "known_faces": len(known_face_drivers),
        })

    refresh_known_face_drivers()
    apply_alert_settings_to_detector()
    face_recognition_frame_counter = 0
    pending_recognition_key = None
    pending_recognition_count = 0
    latest_recognition_frame = None
    last_recognition_result = {
        "status": "NOT_READY" if known_face_drivers else "NO_REGISTERED_FACE",
        "driver": None,
        "similarity": 0.0,
        "shift": None,
    }
    camera_stream = cv2.VideoCapture(0)
    if not camera_stream.isOpened():
        camera_stream.release()
        camera_stream = None
        return jsonify({"status": "error", "message": "Không thể mở camera"}), 503

    camera_running = True
    start_recognition_worker()

    return jsonify({
        "status": "started",
        "known_faces": len(known_face_drivers),
    })


@app.route("/stop_camera", methods=["POST"])
def stop_camera():
    global camera_stream, camera_running, current_driver_id, last_original_camera_frame

    camera_running = False
    stop_recognition_worker()

    if camera_stream is not None:
        camera_stream.release()
        camera_stream = None

    current_driver_id = None
    last_original_camera_frame = None
    reset_detection_state()

    return jsonify({"status": "stopped"})


@app.route("/camera_status")
def camera_status():
    return jsonify(build_camera_status_payload())


@app.route("/video_feed")
def video_feed():
    if not camera_running:
        return ""

    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


@app.route("/capture_image", methods=["POST"])
def capture_image():
    global last_frame

    if last_frame is None:
        return jsonify({
            "status": "error",
            "message": "Chưa có hình ảnh để chụp"
        })

    save_dir = os.path.join(BASE_DIR, "frontend", "static", "captures")
    os.makedirs(save_dir, exist_ok=True)

    filename = datetime.now().strftime("capture_%Y%m%d_%H%M%S.jpg")
    path = os.path.join(save_dir, filename)

    cv2.imwrite(path, last_frame)

    return jsonify({
        "status": "success",
        "message": "Đã chụp ảnh minh chứng",
        "file": f"/static/captures/{filename}"
    })


@app.route("/drivers/<driver_id>/enroll_face_from_camera", methods=["POST"])
@login_required
def enroll_face_from_camera(driver_id):
    global last_original_camera_frame

    if not camera_running or last_original_camera_frame is None:
        return jsonify({
            "status": "error",
            "message": "Camera chưa có frame mới để ghi khuôn mặt"
        }), 400

    driver = get_driver_by_id(driver_id)
    if not driver:
        return jsonify({
            "status": "error",
            "message": "Không tìm thấy tài xế"
        }), 404

    ok, message = append_face_encoding_from_frame(
        driver,
        last_original_camera_frame.copy()
    )

    if ok:
        refresh_known_face_drivers()

    return jsonify({
        "status": "success" if ok else "error",
        "message": message,
        "known_faces": len(known_face_drivers),
    }), 200 if ok else 400


@app.route("/dashboard")
@app.route("/dashboard.html")
@login_required
def dashboard():
    stats = get_dashboard_stats()
    recent_alerts = get_all_alerts(limit=3)
    return render_template("dashboard.html", stats=stats, recent_alerts=recent_alerts)


@app.route("/camera")
@app.route("/camera.html")
def camera():
    return render_template("camera.html")


@app.route("/drivers")
@app.route("/drivers.html")
@login_required
def drivers():
    drivers_list = get_all_drivers()
    drivers_list = attach_current_shift_to_drivers(drivers_list)
    drivers_list = attach_avatar_urls_to_drivers(drivers_list)
    driver_stats = get_driver_stats(drivers_list)
    return render_template("drivers.html", drivers=drivers_list, driver_stats=driver_stats)


@app.route("/vehicles")
@app.route("/vehicles.html")
@login_required
def vehicles():
    vehicles_list = get_all_vehicles()
    vehicles_list = attach_current_shift_to_vehicles(vehicles_list)
    vehicle_stats = get_vehicle_stats(vehicles_list)
    return render_template("vehicles.html", vehicles=vehicles_list, vehicle_stats=vehicle_stats)


@app.route("/shifts")
@app.route("/shifts.html")
@login_required
def shifts():
    shifts_list = get_all_shifts()
    shift_stats = get_shift_stats(shifts_list)
    return render_template("shifts.html", shifts=shifts_list, shift_stats=shift_stats)


@app.route("/alerts")
@app.route("/alerts.html")
@login_required
def alerts():
    alerts_list = get_all_alerts()
    return render_template("alerts.html", alerts=alerts_list)


@app.route("/export-alerts")
@login_required
def export_alerts():
    alerts_list = get_all_alerts()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "alert_time",
        "driver",
        "vehicle",
        "alert_type",
        "alert_level",
        "ear",
        "mar",
        "head_status",
    ])

    for alert in alerts_list or []:
        driver = alert.get("drivers") or {}
        vehicle = alert.get("vehicles") or {}
        writer.writerow([
            alert.get("alert_time") or "",
            driver.get("full_name") or "",
            vehicle.get("plate_number") or "",
            alert.get("alert_type") or "",
            alert.get("alert_level") or "",
            alert.get("ear_value") if alert.get("ear_value") is not None else "",
            alert.get("mar_value") if alert.get("mar_value") is not None else "",
            alert.get("head_status") or "",
        ])

    filename = datetime.now().strftime("alerts_%Y%m%d_%H%M%S.csv")
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/export-drivers")
@login_required
def export_drivers():
    drivers_list = get_all_drivers()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "driver_code",
        "full_name",
        "phone",
        "email",
        "license_number",
        "status",
    ])

    for d in drivers_list or []:
        writer.writerow([
            d.get("driver_code") or "",
            d.get("full_name") or "",
            d.get("phone") or "",
            d.get("email") or "",
            d.get("license_number") or "",
            d.get("status") or "",
        ])

    filename = datetime.now().strftime("drivers_%Y%m%d_%H%M%S.csv")
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/stats")
@app.route("/stats.html")
@login_required
def stats():
    days = request.args.get("days", default=7, type=int)
    if days not in (7, 30):
        days = 7
    alert_stats = get_alert_statistics(days=days)
    return render_template("stats.html", stats=alert_stats, alert_stats=alert_stats, days=days)


@app.route("/stats-data")
@login_required
def stats_data():
    days = request.args.get("days", default=7, type=int)
    if days not in (7, 30):
        days = 7
    return jsonify(get_alert_statistics(days=days))


@app.route("/settings", methods=["GET", "POST"])
@app.route("/settings.html", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        settings_data = clean_settings_form_data(request.form)
        ok, msg = update_alert_settings(settings_data)
        if ok:
            apply_alert_settings_to_detector()  # có hiệu lực ngay, không cần restart camera

        # Đổi mật khẩu (chỉ khi có nhập mật khẩu mới)
        new_pw = request.form.get("new_password", "").strip()
        if new_pw:
            current_pw = request.form.get("current_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not check_admin_credentials(session.get("user"), current_pw):
                flash("Mật khẩu hiện tại không đúng", "error")
            elif new_pw != confirm_pw:
                flash("Mật khẩu nhập lại không khớp", "error")
            elif len(new_pw) < 6:
                flash("Mật khẩu mới tối thiểu 6 ký tự", "error")
            else:
                pw_ok, pw_msg = update_admin_password(
                    session.get("user"), generate_password_hash(new_pw))
                flash(pw_msg, "success" if pw_ok else "error")
        else:
            flash(msg, "success" if ok else "error")

        return redirect(url_for("settings"))

    alert_settings = get_alert_settings()
    return render_template("settings.html", settings=alert_settings)


@app.route("/profile")
@app.route("/profile.html")
@login_required
def profile():
    admin = get_admin_by_username(session.get("user")) or {}
    return render_template("profile.html", admin=admin)


@app.route("/add-vehicle", methods=["GET", "POST"])
@app.route("/add_vehicle", methods=["GET", "POST"])
@app.route("/add_vehicle.html", methods=["GET", "POST"])
@login_required
def add_vehicle():
    if request.method == "POST":
        form_data = clean_vehicle_form_data(request.form)
        success, message = add_vehicle_record(form_data)

        if success:
            flash(message, "success")
            return redirect(url_for("vehicles"))

        flash(message, "error")
        return render_template("add_vehicle.html", form_data=form_data)

    return render_template("add_vehicle.html")


@app.route("/add-shift", methods=["GET", "POST"])
@app.route("/add_shift", methods=["GET", "POST"])
@app.route("/add_shift.html", methods=["GET", "POST"])
@login_required
def add_shift():
    drivers_list = get_all_drivers()
    vehicles_list = get_all_vehicles()

    if request.method == "POST":
        form_data = clean_shift_form_data(request.form)
        success, message = add_shift_record(form_data)

        if success:
            flash(message, "success")
            return redirect(url_for("shifts"))

        flash(message, "error")
        return render_template(
            "add_shift.html",
            form_data=form_data,
            drivers=drivers_list,
            vehicles=vehicles_list
        )

    return render_template(
        "add_shift.html",
        drivers=drivers_list,
        vehicles=vehicles_list
    )

@app.route("/add-driver", methods=["GET", "POST"])
@app.route("/add_driver", methods=["GET", "POST"])
@app.route("/add_driver.html", methods=["GET", "POST"])
@login_required
def add_driver():
    vehicles_list = get_all_vehicles()

    if request.method == "POST":
        form_data = clean_form_data(request.form)
        upload_success, avatar_path, upload_message = upload_driver_image(
            request.files.get("driver_image")
        )

        if not upload_success:
            flash(upload_message, "error")
            return render_template("add_driver.html", form_data=form_data, vehicles=vehicles_list)

        if avatar_path:
            form_data["avatar_path"] = avatar_path

        success, message, driver_id = add_driver_and_get_id(form_data)

        if success:
            if avatar_path:
                enc_ok, enc_msg = build_face_encoding_for_driver(
                    {"id": driver_id, "avatar_path": avatar_path}
                )
                if enc_ok:
                    message = f"{message}. Đã tạo face encoding"
                else:
                    message = f"{message}. Chưa tạo được face encoding: {enc_msg}"

            shift_data = {
                "driver_id": driver_id,
                "vehicle_id": request.form.get("vehicle_id"),
                "shift_name": request.form.get("shift_name"),
                "work_date": request.form.get("work_date"),
                "start_time": request.form.get("start_time"),
                "end_time": request.form.get("end_time"),
                "status": "active",
            }

            if shift_data.get("vehicle_id"):
                if not shift_data.get("work_date"):
                    shift_data["work_date"] = datetime.now().date().isoformat()

                shift_success, shift_message = add_shift_record(shift_data)
                if shift_success:
                    message = f"{message}. Đã gán xe/ca làm việc"
                else:
                    message = f"{message}. Chưa gán được xe/ca: {shift_message}"

            flash(message, "success")
            return redirect(url_for("drivers"))

        flash(message, "error")
        return render_template("add_driver.html", form_data=form_data, vehicles=vehicles_list)

    return render_template("add_driver.html", vehicles=vehicles_list)


@app.route("/drivers/<driver_id>")
@app.route("/driver_detail/<driver_id>")
@login_required
def driver_detail(driver_id):
    driver = get_driver_by_id(driver_id)
    if not driver:
        flash("Không tìm thấy tài xế", "error")
        return redirect(url_for("drivers"))

    driver = attach_avatar_urls_to_drivers([driver])[0]
    shift = get_current_shift_by_driver(driver_id)
    return render_template("driver_detail.html", driver=driver, shift=shift)


@app.route("/drivers/<driver_id>/edit", methods=["GET", "POST"])
@login_required
def edit_driver(driver_id):
    driver = get_driver_by_id(driver_id)
    if not driver:
        flash("Không tìm thấy tài xế", "error")
        return redirect(url_for("drivers"))

    if request.method == "POST":
        form_data = clean_form_data(request.form)
        success, message = update_driver(driver_id, form_data)

        if success:
            flash(message, "success")
            return redirect(url_for("drivers"))

        flash(message, "error")
        return render_template("edit_driver.html", driver={**driver, **form_data})

    return render_template("edit_driver.html", driver=driver)


@app.route("/drivers/<driver_id>/delete", methods=["POST"])
@login_required
def remove_driver(driver_id):
    success, message = delete_driver(driver_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("drivers"))


@app.route("/vehicles/<vehicle_id>")
@login_required
def vehicle_detail(vehicle_id):
    vehicle = get_vehicle_by_id(vehicle_id)
    if not vehicle:
        flash("Không tìm thấy xe", "error")
        return redirect(url_for("vehicles"))
    return render_template("vehicle_detail.html", vehicle=vehicle)


@app.route("/vehicles/<vehicle_id>/edit", methods=["GET", "POST"])
@login_required
def edit_vehicle(vehicle_id):
    vehicle = get_vehicle_by_id(vehicle_id)
    if not vehicle:
        flash("Không tìm thấy xe", "error")
        return redirect(url_for("vehicles"))

    if request.method == "POST":
        form_data = clean_vehicle_form_data(request.form)
        success, message = update_vehicle(vehicle_id, form_data)
        if success:
            flash(message, "success")
            return redirect(url_for("vehicles"))
        flash(message, "error")
        return render_template("edit_vehicle.html", vehicle={**vehicle, **form_data})

    return render_template("edit_vehicle.html", vehicle=vehicle)


@app.route("/vehicles/<vehicle_id>/delete", methods=["POST"])
@login_required
def remove_vehicle(vehicle_id):
    success, message = delete_vehicle(vehicle_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("vehicles"))


@app.route("/rebuild_face_encodings", methods=["POST"])
def rebuild_face_encodings():
    admin_key = os.getenv("ADMIN_SECRET_KEY", "")
    request_key = request.headers.get("X-Admin-Key", "")
    if not admin_key or request_key != admin_key:
        return jsonify({"error": "Unauthorized"}), 401

    result = rebuild_all_face_encodings()
    return jsonify(result)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
