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
import numpy as np

from database import (
    download_driver_image_bytes,
    get_drivers_for_face_encoding,
    update_driver_face_encoding,
)


logger = logging.getLogger(__name__)

DEEPFACE_MODEL_NAME = "Facenet512"
DEEPFACE_DETECTOR_BACKEND = "opencv"
DEEPFACE_EMBEDDING_DIM = 512
MAX_FACE_ENCODINGS_PER_DRIVER = 8


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


def preprocess_for_recognition(image_bgr):
    """
    Tiền xử lý ảnh trước khi đưa vào DeepFace:
      - Cân bằng sáng bằng CLAHE (tốt hơn equalizeHist trong điều kiện sáng không đều)
      - Giảm noise nhẹ
    """
    if image_bgr is None:
        return None

    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)

    lab = cv2.merge([l_channel, a_channel, b_channel])
    result = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    result = cv2.fastNlMeansDenoisingColored(result, None, 3, 3, 7, 21)

    return result


def normalize_vector(vector) -> list[float] | None:
    """
    Chuẩn hóa vector về độ dài 1 (L2 norm) để cosine similarity ổn định.
    """
    if vector is None:
        return None

    np_vector = np.array(vector, dtype="float32")
    norm = np.linalg.norm(np_vector)
    if norm == 0:
        return None

    return (np_vector / norm).astype(float).tolist()


def extract_deepface_embedding(image_bgr, retry_with_preprocess: bool = True) -> list[float] | None:
    """
    Tạo face embedding bằng DeepFace Facenet512 + RetinaFace detector.

    Pipeline:
      1. Thử nhận diện trực tiếp (enforce_detection=True)
      2. Nếu lỗi và retry_with_preprocess=True → tiền xử lý ảnh rồi thử lại
      3. Nếu vẫn lỗi → thử enforce_detection=False (chấp nhận ảnh không rõ mặt)
         nhưng kiểm tra confidence của detector trước khi chấp nhận
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

        if representations:
            face_confidence = representations[0].get("face_confidence", 0)
            if face_confidence >= 0.90:
                return normalize_vector(representations[0].get("embedding"))

            logger.info(f"DeepFace face_confidence thấp: {face_confidence:.2f}, bỏ qua")

    except Exception as e:
        logger.debug(f"DeepFace lần 1 thất bại: {e}")

    if retry_with_preprocess:
        try:
            from deepface import DeepFace

            preprocessed = preprocess_for_recognition(image_bgr)
            if preprocessed is None:
                return None

            representations = DeepFace.represent(
                img_path=preprocessed,
                model_name=DEEPFACE_MODEL_NAME,
                detector_backend=DEEPFACE_DETECTOR_BACKEND,
                enforce_detection=True,
            )

            if representations:
                face_confidence = representations[0].get("face_confidence", 0)
                if face_confidence >= 0.85:
                    return normalize_vector(representations[0].get("embedding"))

                logger.info(f"DeepFace sau preprocess, confidence vẫn thấp: {face_confidence:.2f}")

        except Exception as e:
            logger.debug(f"DeepFace lần 2 (preprocess) thất bại: {e}")

    try:
        from deepface import DeepFace

        representations = DeepFace.represent(
            img_path=image_bgr,
            model_name=DEEPFACE_MODEL_NAME,
            detector_backend=DEEPFACE_DETECTOR_BACKEND,
            enforce_detection=False,
        )

        if representations:
            face_confidence = representations[0].get("face_confidence", 0)
            if face_confidence >= 0.80:
                return normalize_vector(representations[0].get("embedding"))

            logger.warning(f"DeepFace enforce_detection=False nhưng confidence quá thấp: {face_confidence:.2f}")

    except Exception as e:
        logger.warning(f"DeepFace hoàn toàn thất bại: {e}")

    return None


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """
    Tính độ giống nhau giữa 2 face embedding bằng numpy (nhanh hơn pure Python).

    Kết quả càng gần 1 nghĩa là càng giống nhau.
    Trả -1.0 nếu vector không hợp lệ hoặc khác kích thước.
    """
    if not vector_a or not vector_b or len(vector_a) != len(vector_b):
        return -1.0

    a = np.array(vector_a, dtype="float32")
    b = np.array(vector_b, dtype="float32")

    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return -1.0

    return float(np.dot(a, b) / (norm_a * norm_b))


def is_numeric_vector(value, expected_dim: int | None = None) -> bool:
    if not isinstance(value, list):
        return False

    if expected_dim is not None and len(value) != expected_dim:
        return False

    return all(isinstance(item, (int, float)) for item in value)


def extract_face_encoding_vectors(face_encoding) -> list[list[float]]:
    """
    Read face_encoding from the legacy single-vector format or the newer
    multi-vector JSON format stored in the same drivers.face_encoding column.
    """
    if not face_encoding:
        return []

    if is_numeric_vector(face_encoding, DEEPFACE_EMBEDDING_DIM):
        return [face_encoding]

    if isinstance(face_encoding, dict):
        encodings = face_encoding.get("encodings") or []
        return [
            encoding
            for encoding in encodings
            if is_numeric_vector(encoding, DEEPFACE_EMBEDDING_DIM)
        ]

    if isinstance(face_encoding, list):
        return [
            encoding
            for encoding in face_encoding
            if is_numeric_vector(encoding, DEEPFACE_EMBEDDING_DIM)
        ]

    return []


def build_multi_face_encoding_payload(encodings: list[list[float]]) -> dict:
    clean_encodings = [
        encoding
        for encoding in encodings
        if is_numeric_vector(encoding, DEEPFACE_EMBEDDING_DIM)
    ]

    return {
        "model": DEEPFACE_MODEL_NAME,
        "detector": DEEPFACE_DETECTOR_BACKEND,
        "dim": DEEPFACE_EMBEDDING_DIM,
        "encodings": clean_encodings[-MAX_FACE_ENCODINGS_PER_DRIVER:],
    }


def compare_face_embedding(current_embedding: list[float], known_faces: list[dict]) -> dict:
    """
    So sánh khuôn mặt hiện tại với danh sách tài xế đã có encoding.
    Chỉ so sánh với embedding cùng kích thước (cùng loại model).
    """
    best_match = {
        "driver": None,
        "similarity": -1.0,
    }

    for driver in known_faces or []:
        saved_embeddings = extract_face_encoding_vectors(driver.get("face_encoding"))

        for saved_embedding in saved_embeddings:
            similarity = cosine_similarity(current_embedding, saved_embedding)

            if similarity > best_match["similarity"]:
                best_match = {
                    "driver": driver,
                    "similarity": similarity,
                }

    return best_match


def extract_face_embedding(image_bgr) -> list[float] | None:
    """
    Tạo face embedding chỉ bằng DeepFace Facenet512.

    Không fallback sang loại embedding khác (landmark/pixel) vì vector khác
    kích thước sẽ không so sánh được với nhau → gây false negative.
    """
    return extract_deepface_embedding(image_bgr, retry_with_preprocess=True)


def recognize_driver_from_frame(frame_bgr, known_faces: list[dict], threshold: float = 0.87) -> dict:
    """
    Nhận diện tài xế từ một frame camera.

    Args:
        frame_bgr: frame từ OpenCV camera.
        known_faces: danh sách tài xế đã có face_encoding.
        threshold: ngưỡng cosine similarity cho Facenet512.
                   0.87 cân bằng giữa chính xác và không quá khắt khe.

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
    similarity = best_match["similarity"]

    if best_match["driver"] and similarity >= threshold:
        return {
            "status": "RECOGNIZED",
            "driver": best_match["driver"],
            "similarity": similarity,
        }

    return {
        "status": "UNKNOWN_DRIVER",
        "driver": None,
        "similarity": max(similarity, 0.0),
    }


def build_face_encoding_for_driver(driver: dict) -> tuple[bool, str]:
    """
    Tạo và lưu face_encoding cho một tài xế từ avatar_path.
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

    if len(face_encoding) != DEEPFACE_EMBEDDING_DIM:
        return False, f"Embedding sai kích thước: {len(face_encoding)} (cần {DEEPFACE_EMBEDDING_DIM})"

    payload = build_multi_face_encoding_payload([face_encoding])
    return update_driver_face_encoding(driver_id, payload)


def append_face_encoding_from_frame(driver: dict, frame_bgr) -> tuple[bool, str]:
    """
    Add one camera-captured face encoding to the existing driver.face_encoding
    JSONB value without changing the database schema.
    """
    driver_id = driver.get("id")
    if not driver_id:
        return False, "Thiếu driver_id"

    new_encoding = extract_face_embedding(frame_bgr)
    if new_encoding is None:
        return False, "Không phát hiện được khuôn mặt rõ ràng từ camera"

    existing_encodings = extract_face_encoding_vectors(driver.get("face_encoding"))
    payload = build_multi_face_encoding_payload(existing_encodings + [new_encoding])
    ok, message = update_driver_face_encoding(driver_id, payload)

    if not ok:
        return ok, message

    return True, f"{message}. Tổng mẫu khuôn mặt: {len(payload['encodings'])}"


def build_missing_face_encodings() -> dict:
    """
    Tạo face_encoding cho các tài xế đã có ảnh nhưng chưa có encoding.
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
    BẮT BUỘC chạy khi đổi model hoặc detector backend.
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
