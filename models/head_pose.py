"""Head Pose - phát hiện cúi đầu dựa trên tỉ lệ mũi-cằm / trán-cằm."""

# Chỉ số landmark MediaPipe FaceMesh dùng cho ước lượng góc đầu.
HEAD_POSE_INDEXES = [1, 152, 33, 263, 61, 291]


def detect_head_down(face_landmarks, width, height):
    nose = face_landmarks.landmark[1]
    chin = face_landmarks.landmark[152]
    forehead = face_landmarks.landmark[10]

    nose_chin = abs(chin.y - nose.y)
    forehead_y = abs(chin.y - forehead.y)
    if forehead_y == 0:
        return False
    ratio = nose_chin / forehead_y
    return ratio < 0.38
