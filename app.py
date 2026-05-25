from flask import Flask, render_template, Response, jsonify, request, redirect, url_for, flash
import cv2
import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

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
    get_all_shifts,
    get_shift_stats,
    add_shift as add_shift_record,
    get_all_alerts,
    get_dashboard_stats,
    get_drivers_with_face_encoding,
    get_current_shift_by_driver,
)
from models.face_recognition_model import recognize_driver_from_frame

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "driver-guard-ai-dev-secret")
logger = setup_logger(__name__)

camera_stream = None
camera_running = False
last_frame = None
known_face_drivers = []
face_recognition_frame_counter = 0
FACE_RECOGNITION_THRESHOLD = 0.72
RECOGNITION_CONFIRM_FRAMES = 3
UNKNOWN_CONFIRM_FRAMES = 5
FACE_RECOGNITION_INTERVAL_SECONDS = 1.5
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
def distance(point1, point2):
    x1, y1 = point1
    x2, y2 = point2

    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
def calculate_ear(eye_points):
    # Khoảng cách dọc
    vertical_1 = distance(eye_points[1], eye_points[5])
    vertical_2 = distance(eye_points[2], eye_points[4])

    # Khoảng cách ngang
    horizontal = distance(eye_points[0], eye_points[3])

    if horizontal == 0:
        return 0.0

    # Công thức EAR
    ear = (vertical_1 + vertical_2) / (2.0 * horizontal)

    return ear
def calculate_mar(mouth_points):
    vertical_1 = distance(mouth_points[1], mouth_points[5])
    vertical_2 = distance(mouth_points[2], mouth_points[4])

    horizontal = distance(mouth_points[0], mouth_points[3])

    if horizontal == 0:
        return 0.0

    mar = (vertical_1 + vertical_2) / (2.0 * horizontal)

    return mar
def detect_head_down(face_landmarks, width, height):
    nose = face_landmarks.landmark[1]
    chin = face_landmarks.landmark[152]

    nose_y = int(nose.y * height)
    chin_y = int(chin.y * height)

    distance_nose_chin = chin_y - nose_y

    if distance_nose_chin < 70:
        return True
    else:
        return False
LEFT_EYE_INDEXES = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_INDEXES = [362, 385, 387, 263, 373, 380]
MOUTH_INDEXES = [61, 81, 13, 291, 311, 14]
HEAD_POSE_INDEXES = [1, 152, 33, 263, 61, 291]
MAR_THRESHOLD = 0.3
EAR_THRESHOLD = 0.22

# Nhắm mắt liên tục khoảng 30 giây nếu camera ~20 FPS
DROWSY_FRAME_THRESHOLD = 600

# Nhắm/mở mắt ngắn thì tính là 1 lần blink
BLINK_FRAME_THRESHOLD = 3

# 20 lần blink trong 30 giây = 1 dấu hiệu buồn ngủ
BLINK_WARNING_THRESHOLD = 15

closed_counter = 0
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

    current_key = get_recognition_key(raw_result)

    if current_key == pending_recognition_key:
        pending_recognition_count += 1
    else:
        pending_recognition_key = current_key
        pending_recognition_count = 1

    if raw_result.get("status") == "RECOGNIZED":
        if pending_recognition_count >= RECOGNITION_CONFIRM_FRAMES:
            last_recognition_result = raw_result
        return last_recognition_result

    if raw_result.get("status") in ("UNKNOWN_DRIVER", "NO_FACE"):
        if pending_recognition_count >= UNKNOWN_CONFIRM_FRAMES:
            last_recognition_result = raw_result
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
            "driver_name": driver.get("full_name") or "Không xác định",
            "driver_code": driver.get("driver_code"),
            "phone": driver.get("phone") or "--",
            "confidence": round(similarity * 100, 1),
            "vehicle_plate": vehicle.get("plate_number") if vehicle else "Chưa gán",
            "shift_name": shift.get("shift_name") if shift else "Chưa gán",
            "shift_time": shift_time,
            "known_faces": len(known_face_drivers),
        }

    if status == "UNKNOWN_DRIVER":
        return {
            "status": "UNKNOWN_DRIVER",
            "driver_name": "Không xác định",
            "driver_code": None,
            "phone": "--",
            "confidence": round(similarity * 100, 1),
            "vehicle_plate": "--",
            "shift_name": "--",
            "shift_time": "--",
            "known_faces": len(known_face_drivers),
        }

    return {
        "status": status or "NOT_READY",
        "driver_name": "Đang chờ nhận diện",
        "driver_code": None,
        "phone": "--",
        "confidence": 0.0,
        "vehicle_plate": "--",
        "shift_name": "--",
        "shift_time": "--",
        "known_faces": len(known_face_drivers),
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
    global camera_stream, camera_running, last_frame
    global closed_counter, blink_counter, tired_event_counter, blink_start_time
    global mouth_open_detected, mouth_open_time, yawn_counter
    global head_down_start_time, head_down_detected
    global alert_triggered
    global face_recognition_frame_counter, last_recognition_result

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

                    if detect_head_down(face_landmarks, width, height):
                        head_status = "HEAD DOWN"

                        if not head_down_detected:
                            head_down_detected = True
                            head_down_start_time = current_time
                        else:
                            if current_time - head_down_start_time >= HEAD_DOWN_THRESHOLD:
                                send_alert = True
                                alert_triggered = True
                                drowsy_status = "HEAD DOWN ALERT"
                    else:
                        head_status = "NORMAL"
                        head_down_detected = False

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

                        if ear < EAR_THRESHOLD:
                            eye_status = "EYES CLOSED"
                            closed_counter += 1
                        else:
                            eye_status = "EYES OPEN"

                            if 0 < closed_counter <= BLINK_FRAME_THRESHOLD:
                                blink_counter += 1

                            closed_counter = 0

                        if current_time - blink_start_time >= 30:
                            if blink_counter >= BLINK_WARNING_THRESHOLD:
                                tired_event_counter += 1

                            blink_counter = 0
                            blink_start_time = current_time

                        if closed_counter >= DROWSY_FRAME_THRESHOLD:
                            drowsy_status = "DROWSY"
                            send_alert = True
                            alert_triggered = True

                        elif tired_event_counter >= 2 or yawn_counter >= 3:
                            drowsy_status = "TIRED"
                            send_alert = True
                            alert_triggered = True

                    if len(mouth_points) == 6:
                        mar = calculate_mar(mouth_points)

                        if mar > MAR_THRESHOLD:
                            mouth_status = "MOUTH OPEN"

                            if not mouth_open_detected:
                                mouth_open_detected = True
                                mouth_open_time = current_time
                            elif current_time - mouth_open_time >= YAWN_CONFIRM_TIME:
                                yawn_counter += 1
                                mouth_status = "YAWNING"
                                mouth_open_detected = False
                                send_alert = True
                                alert_triggered = True
                        else:
                            mouth_status = "NORMAL"
                            mouth_open_detected = False

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

                cv2.putText(ai_frame, f"BLINKS/30S: {blink_counter}", (20, 220),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                cv2.putText(ai_frame, f"TIRED EVENTS: {tired_event_counter}/2", (20, 250),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                if mar is not None:
                    cv2.putText(ai_frame, f"MAR: {mar:.2f}", (20, 280),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)

                    cv2.putText(ai_frame, f"MOUTH: {mouth_status}", (20, 310),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (0, 0, 255) if mouth_status == "YAWNING" else (0, 255, 0), 2)

                    cv2.putText(ai_frame, f"YAWNS: {yawn_counter}", (20, 340),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)

                cv2.putText(ai_frame, f"HEAD: {head_status}", (20, 370),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 0, 255) if head_status == "HEAD DOWN" else (0, 255, 0), 2)

                if send_alert or alert_triggered:
                    cv2.putText(ai_frame, "SEND ALERT TO MANAGER", (20, 340),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

                    if send_alert and current_driver_id:
                        if drowsy_status == "HEAD DOWN ALERT":
                            alert_type = "HEAD_DOWN"
                            alert_level = "medium"
                        elif drowsy_status == "DROWSY":
                            alert_type = "DROWSY"
                            alert_level = "high"
                        elif drowsy_status == "TIRED":
                            alert_type = "EYES_CLOSED"
                            alert_level = "medium"
                        elif mouth_status == "YAWNING":
                            alert_type = "YAWNING"
                            alert_level = "low"
                        else:
                            alert_type = "DROWSY"
                            alert_level = "medium"

                        process_violation(
                            driver_id=current_driver_id,
                            alert_type=alert_type,
                            alert_level=alert_level,
                            ear=ear,
                            mar=mar,
                            head_status=head_status,
                            frame=original_frame,
                        )
            else:
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
@app.route("/")
@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/camera")
def camera():
    drivers_list = get_all_drivers()
    return render_template("camera.html", drivers=drivers_list)


@app.route("/start_camera", methods=["POST"])
def start_camera():
    global camera_stream, camera_running, face_recognition_frame_counter, last_recognition_result
    global pending_recognition_key, pending_recognition_count
    global latest_recognition_frame

    if not camera_running:
        refresh_known_face_drivers()
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
        camera_running = True
        start_recognition_worker()

    return jsonify({
        "status": "started",
        "known_faces": len(known_face_drivers),
    })


@app.route("/stop_camera", methods=["POST"])
def stop_camera():
    global camera_stream, camera_running, current_driver_id

    camera_running = False
    stop_recognition_worker()

    if camera_stream is not None:
        camera_stream.release()
        camera_stream = None

    current_driver_id = None
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

    save_dir = "static/captures"
    os.makedirs(save_dir, exist_ok=True)

    filename = datetime.now().strftime("capture_%Y%m%d_%H%M%S.jpg")
    path = os.path.join(save_dir, filename)

    cv2.imwrite(path, last_frame)

    return jsonify({
        "status": "success",
        "message": "Đã chụp ảnh minh chứng",
        "file": path
    })


@app.route("/register")
def register():
    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    stats = get_dashboard_stats()
    recent_alerts = get_all_alerts(limit=3)
    return render_template("dashboard.html", stats=stats, recent_alerts=recent_alerts)


@app.route("/drivers")
def drivers():
    drivers_list = get_all_drivers()
    drivers_list = attach_current_shift_to_drivers(drivers_list)
    drivers_list = attach_avatar_urls_to_drivers(drivers_list)
    return render_template("drivers.html", drivers=drivers_list)


@app.route("/vehicles")
def vehicles():
    vehicles_list = get_all_vehicles()
    vehicles_list = attach_current_shift_to_vehicles(vehicles_list)
    vehicle_stats = get_vehicle_stats(vehicles_list)
    return render_template("vehicles.html", vehicles=vehicles_list, vehicle_stats=vehicle_stats)


@app.route("/add-vehicle", methods=["GET", "POST"])
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


@app.route("/shifts")
def shifts():
    shifts_list = get_all_shifts()
    shift_stats = get_shift_stats(shifts_list)
    return render_template("shifts.html", shifts=shifts_list, shift_stats=shift_stats)


@app.route("/add-shift", methods=["GET", "POST"])
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


@app.route("/alerts")
def alerts():
    alerts_list = get_all_alerts()
    return render_template("alerts.html", alerts=alerts_list)


@app.route("/stats")
def stats():
    return render_template("stats.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/profile")
def profile():
    return render_template("profile.html")


@app.route("/add-driver", methods=["GET", "POST"])
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
            # Nếu form có chọn xe, tạo luôn một ca làm việc để gán tài xế với xe.
            # Thông tin gán ca nằm ở bảng shifts, không lưu trực tiếp trong drivers.
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


if __name__ == "__main__":
    app.run(debug=True)
