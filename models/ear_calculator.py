"""Eye Aspect Ratio (EAR) - đo độ mở của mắt từ 6 điểm landmark."""

from utils.helper import distance

# Chỉ số landmark MediaPipe FaceMesh cho mắt trái/phải (theo thứ tự EAR).
LEFT_EYE_INDEXES = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_INDEXES = [362, 385, 387, 263, 373, 380]


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
