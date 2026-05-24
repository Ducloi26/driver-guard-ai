"""
Module nhận diện khuôn mặt tài xế.

File này chỉ xử lý logic AI/ảnh:
  - đọc ảnh từ bytes hoặc frame camera
  - phát hiện khuôn mặt
  - tạo face_embedding dạng list số để lưu vào drivers.face_encoding
  - so sánh khuôn mặt hiện tại với danh sách tài xế đã lưu

database.py vẫn là tầng duy nhất nói chuyện với Supabase.
"""

import logging
from math import sqrt

import cv2
import mediapipe as mp
import numpy as np

from database import (
    download_driver_image_bytes,
    get_drivers_for_face_encoding,
    update_driver_face_encoding,
)


logger = logging.getLogger(__name__)

# Haar Cascade có sẵn trong OpenCV, không cần cài thêm thư viện nặng.
# Đây là lựa chọn ổn cho demo local; sau này có thể thay bằng DeepFace/ArcFace.
FACE_CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
face_detector = cv2.CascadeClassifier(FACE_CASCADE_PATH)
mp_face_mesh = mp.solutions.face_mesh
face_mesh_encoder = mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
)

# Kích thước chuẩn để biến khuôn mặt thành vector cố định.
# 64x64 = 4096 chiều, đủ nhẹ để lưu JSONB trong Supabase cho demo.
EMBEDDING_SIZE = (64, 64)
DEEPFACE_MODEL_NAME = "Facenet512"
DEEPFACE_DETECTOR_BACKEND = "opencv"


def decode_image_bytes(image_bytes: bytes):
    """
    Chuyển bytes ảnh tải từ Supabase Storage thành ảnh OpenCV BGR.

    Args:
        image_bytes (bytes): nội dung file ảnh.

    Returns:
        numpy.ndarray | None: ảnh BGR nếu đọc được, None nếu file lỗi.
    """
    if not image_bytes:
        return None

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(image_array, cv2.IMREAD_COLOR)


def detect_face(image_bgr):
    """
    Phát hiện và cắt khuôn mặt lớn nhất trong ảnh.

    Với ảnh đăng ký tài xế, thường chỉ có một khuôn mặt. Nếu có nhiều mặt,
    lấy mặt lớn nhất vì đó thường là chủ thể chính.

    Args:
        image_bgr: ảnh OpenCV dạng BGR.

    Returns:
        numpy.ndarray | None: vùng ảnh khuôn mặt, hoặc None nếu không thấy mặt.
    """
    if image_bgr is None:
        return None

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    faces = face_detector.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(80, 80),
    )

    if len(faces) == 0:
        return None

    x, y, w, h = max(faces, key=lambda face: face[2] * face[3])

    # Nới khung một chút để lấy đủ vùng mặt, tránh crop quá sát mắt/cằm.
    padding = int(0.18 * max(w, h))
    x1 = max(x - padding, 0)
    y1 = max(y - padding, 0)
    x2 = min(x + w + padding, image_bgr.shape[1])
    y2 = min(y + h + padding, image_bgr.shape[0])

    return image_bgr[y1:y2, x1:x2]


def normalize_vector(vector) -> list[float] | None:
    """
    Chuẩn hóa vector về độ dài 1 để cosine similarity ổn định hơn.
    """
    if vector is None:
        return None

    np_vector = np.array(vector, dtype="float32")
    norm = np.linalg.norm(np_vector)
    if norm == 0:
        return None

    return (np_vector / norm).astype(float).tolist()


def extract_deepface_embedding(image_bgr) -> list[float] | None:
    """
    Tạo face embedding bằng DeepFace Facenet512.

    DeepFace cho vector nhận diện khuôn mặt tốt hơn nhiều so với pixel/landmark
    thủ công. Import DeepFace trong hàm để app.py không bị khởi động chậm nếu
    chưa dùng đến nhận diện.
    """
    if image_bgr is None:
        return None

    try:
        from deepface import DeepFace

        representations = DeepFace.represent(
            img_path=image_bgr,
            model_name=DEEPFACE_MODEL_NAME,
            detector_backend=DEEPFACE_DETECTOR_BACKEND,
            enforce_detection=True,
        )

        if not representations:
            return None

        return normalize_vector(representations[0].get("embedding"))

    except Exception as e:
        logger.warning(f"extract_deepface_embedding() fallback vì lỗi: {e}")
        return None


def extract_landmark_embedding(image_bgr) -> list[float] | None:
    """
    Tạo vector hình học khuôn mặt bằng MediaPipe FaceMesh.

    Vector này dựa trên vị trí landmark, đã chuẩn hóa theo tâm mũi và khoảng
    cách hai mắt. Nó ổn hơn pixel thô khi ảnh đăng ký và webcam khác ánh sáng,
    khác crop hoặc hơi lệch góc.
    """
    if image_bgr is None:
        return None

    rgb_image = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    results = face_mesh_encoder.process(rgb_image)

    if not results.multi_face_landmarks:
        return None

    landmarks = results.multi_face_landmarks[0].landmark
    if len(landmarks) < 264:
        return None

    nose = landmarks[1]
    left_eye = landmarks[33]
    right_eye = landmarks[263]

    eye_distance = sqrt(
        (right_eye.x - left_eye.x) ** 2
        + (right_eye.y - left_eye.y) ** 2
        + (right_eye.z - left_eye.z) ** 2
    )

    if eye_distance == 0:
        return None

    vector = []
    # Dùng 468 landmark chuẩn. Nếu refine_landmarks trả thêm iris landmarks,
    # bỏ phần thêm để vector đăng ký và vector webcam luôn cùng chiều.
    for point in landmarks[:468]:
        vector.extend([
            (point.x - nose.x) / eye_distance,
            (point.y - nose.y) / eye_distance,
            (point.z - nose.z) / eye_distance,
        ])

    np_vector = np.array(vector, dtype="float32")
    norm = np.linalg.norm(np_vector)
    if norm == 0:
        return None

    return (np_vector / norm).astype(float).tolist()


def extract_pixel_embedding(image_bgr) -> list[float] | None:
    """
    Tạo vector khuôn mặt từ pixel ảnh.

    Bản demo dùng OpenCV:
      - detect khuôn mặt
      - chuyển grayscale
      - resize 64x64
      - cân bằng sáng bằng equalizeHist
      - chuẩn hóa vector về độ dài 1

    Sau này nếu nhóm dùng DeepFace/ArcFace, chỉ cần thay logic trong hàm này,
    các hàm còn lại và database.py vẫn giữ nguyên.
    """
    face = detect_face(image_bgr)
    if face is None:
        return None

    gray_face = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray_face, EMBEDDING_SIZE)
    equalized = cv2.equalizeHist(resized)

    vector = equalized.astype("float32").flatten()
    vector = (vector - np.mean(vector)) / (np.std(vector) + 1e-6)

    norm = np.linalg.norm(vector)
    if norm == 0:
        return None

    normalized = vector / norm
    return normalized.astype(float).tolist()


def extract_face_embedding(image_bgr) -> list[float] | None:
    """
    Tạo face embedding ưu tiên bằng DeepFace Facenet512.

    Fallback:
      - FaceMesh landmark embedding nếu DeepFace lỗi.
      - Pixel embedding nếu cả DeepFace và FaceMesh đều không tìm được mặt.
    """
    deepface_embedding = extract_deepface_embedding(image_bgr)
    if deepface_embedding is not None:
        return deepface_embedding

    landmark_embedding = extract_landmark_embedding(image_bgr)
    if landmark_embedding is not None:
        return landmark_embedding

    return extract_pixel_embedding(image_bgr)


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """
    Tính độ giống nhau giữa 2 face embedding.

    Kết quả càng gần 1 nghĩa là càng giống nhau.
    """
    if not vector_a or not vector_b or len(vector_a) != len(vector_b):
        return -1.0

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b))
    norm_a = sqrt(sum(a * a for a in vector_a))
    norm_b = sqrt(sum(b * b for b in vector_b))

    if norm_a == 0 or norm_b == 0:
        return -1.0

    return dot_product / (norm_a * norm_b)


def compare_face_embedding(current_embedding: list[float], known_faces: list[dict]) -> dict:
    """
    So sánh khuôn mặt hiện tại với danh sách tài xế đã có encoding.

    Args:
        current_embedding: vector khuôn mặt từ frame camera.
        known_faces: list tài xế từ get_drivers_with_face_encoding().

    Returns:
        dict: tài xế giống nhất và điểm similarity.
    """
    best_match = {
        "driver": None,
        "similarity": -1.0,
    }

    for driver in known_faces or []:
        saved_embedding = driver.get("face_encoding")
        similarity = cosine_similarity(current_embedding, saved_embedding)

        if similarity > best_match["similarity"]:
            best_match = {
                "driver": driver,
                "similarity": similarity,
            }

    return best_match


def recognize_driver_from_frame(frame_bgr, known_faces: list[dict], threshold: float = 0.93) -> dict:
    """
    Nhận diện tài xế từ một frame camera.

    Args:
        frame_bgr: frame từ OpenCV camera.
        known_faces: danh sách tài xế đã có face_encoding.
        threshold: ngưỡng nhận diện. Dưới ngưỡng sẽ trả UNKNOWN_DRIVER.
                   Với FaceMesh landmark embedding, ngưỡng nên cao hơn pixel
                   embedding vì nhiều khuôn mặt có hình học tổng thể khá giống.

    Returns:
        dict: trạng thái nhận diện và thông tin tài xế nếu match.
    """
    current_embedding = extract_face_embedding(frame_bgr)
    if current_embedding is None:
        return {
            "status": "NO_FACE",
            "driver": None,
            "similarity": 0.0,
        }

    best_match = compare_face_embedding(current_embedding, known_faces)
    if best_match["driver"] and best_match["similarity"] >= threshold:
        return {
            "status": "RECOGNIZED",
            "driver": best_match["driver"],
            "similarity": best_match["similarity"],
        }

    return {
        "status": "UNKNOWN_DRIVER",
        "driver": None,
        "similarity": best_match["similarity"],
    }


def build_face_encoding_for_driver(driver: dict) -> tuple[bool, str]:
    """
    Tạo và lưu face_encoding cho một tài xế từ avatar_path.

    Args:
        driver (dict): một record từ get_drivers_for_face_encoding().

    Returns:
        tuple[bool, str]: kết quả xử lý và thông báo.
    """
    driver_id = driver.get("id")
    avatar_path = driver.get("avatar_path")

    if not driver_id or not avatar_path:
        return False, "Thiếu driver_id hoặc avatar_path"

    image_bytes = download_driver_image_bytes(avatar_path)
    image_bgr = decode_image_bytes(image_bytes)
    face_encoding = extract_face_embedding(image_bgr)

    if face_encoding is None:
        return False, "Không phát hiện được khuôn mặt rõ ràng trong ảnh"

    return update_driver_face_encoding(driver_id, face_encoding)


def build_missing_face_encodings() -> dict:
    """
    Tạo face_encoding cho các tài xế đã có ảnh nhưng chưa có encoding.

    Hàm này dùng để chạy thủ công khi quản lý vừa upload ảnh tài xế.
    """
    drivers = get_drivers_for_face_encoding()
    result = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "details": [],
    }

    for driver in drivers:
        if driver.get("face_encoding"):
            continue

        result["total"] += 1
        ok, message = build_face_encoding_for_driver(driver)

        if ok:
            result["success"] += 1
        else:
            result["failed"] += 1

        result["details"].append({
            "driver_id": driver.get("id"),
            "full_name": driver.get("full_name"),
            "success": ok,
            "message": message,
        })

    return result


def rebuild_all_face_encodings() -> dict:
    """
    Tạo lại face_encoding cho tất cả tài xế có ảnh đăng ký.

    Dùng khi nhóm thay đổi thuật toán embedding. Ví dụ: từ pixel embedding
    sang FaceMesh landmark embedding. Hàm này sẽ ghi đè face_encoding cũ.
    """
    drivers = get_drivers_for_face_encoding()
    result = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "details": [],
    }

    for driver in drivers:
        result["total"] += 1
        ok, message = build_face_encoding_for_driver(driver)

        if ok:
            result["success"] += 1
        else:
            result["failed"] += 1

        result["details"].append({
            "driver_id": driver.get("id"),
            "full_name": driver.get("full_name"),
            "success": ok,
            "message": message,
        })

    return result
