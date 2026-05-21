from flask import Flask, render_template, Response, jsonify
import cv2
import os
import mediapipe as mp
import time
from datetime import datetime
app = Flask(__name__)

camera_stream = None
camera_running = False
last_frame = None
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

    # Công thức EAR
    ear = (vertical_1 + vertical_2) / (2.0 * horizontal)

    return ear
LEFT_EYE_INDEXES = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_INDEXES = [362, 385, 387, 263, 373, 380]
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
def generate_frames():
    global camera_stream, camera_running, last_frame
    global closed_counter, blink_counter, tired_event_counter, blink_start_time

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

            rgb_frame = cv2.cvtColor(ai_frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb_frame)

            left_ear = None
            right_ear = None
            ear = None
            eye_status = "NO FACE"
            drowsy_status = "NORMAL"
            send_alert = False

            if results.multi_face_landmarks:
                for face_landmarks in results.multi_face_landmarks:
                    height, width, _ = ai_frame.shape

                    left_eye = []
                    right_eye = []

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

                    if len(left_eye) == 6 and len(right_eye) == 6:
                        left_ear = calculate_ear(left_eye)
                        right_ear = calculate_ear(right_eye)
                        ear = (left_ear + right_ear) / 2.0

                        current_time = time.time()

                        if ear < EAR_THRESHOLD:
                            eye_status = "EYES CLOSED"
                            closed_counter += 1
                        else:
                            eye_status = "EYES OPEN"

                            if 0 < closed_counter <= BLINK_FRAME_THRESHOLD:
                                blink_counter += 1

                            closed_counter = 0

                        # 15 lần blink trong 40 giây = 1 dấu hiệu buồn ngủ
                        if current_time - blink_start_time >= 40:
                            if blink_counter >= BLINK_WARNING_THRESHOLD:
                                tired_event_counter += 1

                            blink_counter = 0
                            blink_start_time = current_time

                        # Nhắm mắt liên tục 30 giây → gửi cảnh báo ngay
                        if closed_counter >= DROWSY_FRAME_THRESHOLD:
                            drowsy_status = "DROWSY"
                            send_alert = True

                        # Có dấu hiệu buồn ngủ 2 lần → gửi cảnh báo
                        elif tired_event_counter >= 2:
                            drowsy_status = "TIRED"
                            send_alert = True

                        else:
                            drowsy_status = "NORMAL"
                            send_alert = False

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

            cv2.putText(
                original_frame,
                "CAMERA GOC",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2
            )

            cv2.putText(
                ai_frame,
                "FACE MESH AI",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            if ear is not None:
                cv2.putText(
                    ai_frame,
                    f"L-EAR: {left_ear:.2f}",
                    (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2
                )

                cv2.putText(
                    ai_frame,
                    f"R-EAR: {right_ear:.2f}",
                    (20, 100),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2
                )

                cv2.putText(
                    ai_frame,
                    f"AVG-EAR: {ear:.2f}",
                    (20, 130),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (255, 255, 0),
                    2
                )

                cv2.putText(
                    ai_frame,
                    f"STATUS: {eye_status}",
                    (20, 160),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255) if eye_status == "EYES CLOSED" else (0, 255, 0),
                    2
                )

                cv2.putText(
                    ai_frame,
                    f"DROWSY: {drowsy_status}",
                    (20, 190),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255) if send_alert else (0, 255, 0),
                    2
                )

                cv2.putText(
                    ai_frame,
                    f"BLINKS/30S: {blink_counter}",
                    (20, 220),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )

                cv2.putText(
                    ai_frame,
                    f"TIRED EVENTS: {tired_event_counter}/2",
                    (20, 250),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2
                )

                if send_alert:
                    cv2.putText(
                        ai_frame,
                        "SEND ALERT TO MANAGER",
                        (20, 290),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        (0, 0, 255),
                        2
                    )
            else:
                cv2.putText(
                    ai_frame,
                    "NO FACE DETECTED",
                    (20, 80),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2
                )

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
            print("Lỗi generate_frames:", e)
            break
@app.route("/")
@app.route("/login")
def login():
    return render_template("login.html")


@app.route("/camera")
def camera():
    return render_template("camera.html")


@app.route("/start_camera", methods=["POST"])
def start_camera():
    global camera_stream, camera_running

    if not camera_running:
        camera_stream = cv2.VideoCapture(0)
        camera_running = True

    return jsonify({"status": "started"})


@app.route("/stop_camera", methods=["POST"])
def stop_camera():
    global camera_stream, camera_running

    camera_running = False

    if camera_stream is not None:
        camera_stream.release()
        camera_stream = None

    return jsonify({"status": "stopped"})


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
    return render_template("dashboard.html")


@app.route("/drivers")
def drivers():
    return render_template("drivers.html")


@app.route("/vehicles")
def vehicles():
    return render_template("vehicles.html")


@app.route("/shifts")
def shifts():
    return render_template("shifts.html")


@app.route("/alerts")
def alerts():
    return render_template("alerts.html")


@app.route("/stats")
def stats():
    return render_template("stats.html")


@app.route("/settings")
def settings():
    return render_template("settings.html")


@app.route("/profile")
def profile():
    return render_template("profile.html")


@app.route("/add-driver")
def add_driver():
    return render_template("add_driver.html")


if __name__ == "__main__":
    app.run(debug=True)