from flask import Flask, render_template, Response, jsonify
import cv2
import os
import mediapipe as mp
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

def generate_frames():
    global camera_stream, camera_running, last_frame

    while camera_running:
        success, frame = camera_stream.read()

        if not success:
            break

        # Lật ảnh cho giống selfie
        frame = cv2.flip(frame, 1)

        # Ảnh gốc không vẽ landmark
        original_frame = frame.copy()

        # Ảnh dùng để vẽ landmark
        ai_frame = frame.copy()

        # Đổi BGR sang RGB cho MediaPipe
        rgb_frame = cv2.cvtColor(ai_frame, cv2.COLOR_BGR2RGB)

        results = face_mesh.process(rgb_frame)

        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
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

        # Resize 2 ảnh cho đều nhau
        original_frame = cv2.resize(original_frame, (480, 360))
        ai_frame = cv2.resize(ai_frame, (480, 360))

        # Ghi nhãn từng bên
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

        # Ghép 2 màn hình ngang
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