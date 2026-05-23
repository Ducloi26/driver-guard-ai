from flask import Flask, render_template, Response, jsonify, request, redirect, url_for, flash
import cv2
import os
import mediapipe as mp
import time
from datetime import datetime
from database import (
    clean_form_data,
    clean_vehicle_form_data,
    clean_shift_form_data,
    upload_driver_image,
    get_all_drivers,
    attach_current_shift_to_drivers,
    add_driver as add_driver_record,
    get_all_vehicles,
    attach_current_shift_to_vehicles,
    get_vehicle_stats,
    add_vehicle as add_vehicle_record,
    get_all_shifts,
    get_shift_stats,
    add_shift as add_shift_record,
    get_all_alerts,
    get_dashboard_stats,
)
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "driver-guard-ai-dev-secret")

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
def calculate_mar(mouth_points):
    vertical_1 = distance(mouth_points[1], mouth_points[5])
    vertical_2 = distance(mouth_points[2], mouth_points[4])

    horizontal = distance(mouth_points[0], mouth_points[3])

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
def generate_frames():
    global camera_stream, camera_running, last_frame
    global closed_counter, blink_counter, tired_event_counter, blink_start_time
    global mouth_open_detected, mouth_open_time, yawn_counter
    global head_down_start_time, head_down_detected
    global alert_triggered

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
                            else:
                                if current_time - mouth_open_time < YAWN_CONFIRM_TIME:
                                    mouth_open_time = current_time
                        else:
                            mouth_status = "NORMAL"

                        if mouth_open_detected:
                            if current_time - mouth_open_time >= YAWN_CONFIRM_TIME:
                                yawn_counter += 1
                                mouth_status = "YAWNING"
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
    stats = get_dashboard_stats()
    return render_template("dashboard.html", stats=stats)


@app.route("/drivers")
def drivers():
    drivers_list = get_all_drivers()
    drivers_list = attach_current_shift_to_drivers(drivers_list)
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
    if request.method == "POST":
        form_data = clean_form_data(request.form)
        upload_success, avatar_path, upload_message = upload_driver_image(
            request.files.get("driver_image")
        )

        if not upload_success:
            flash(upload_message, "error")
            return render_template("add_driver.html", form_data=form_data)

        if avatar_path:
            form_data["avatar_path"] = avatar_path

        success, message = add_driver_record(form_data)

        if success:
            flash(message, "success")
            return redirect(url_for("drivers"))

        flash(message, "error")
        return render_template("add_driver.html", form_data=form_data)

    return render_template("add_driver.html")


if __name__ == "__main__":
    app.run(debug=True)
