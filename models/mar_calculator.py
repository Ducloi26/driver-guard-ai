"""Mouth Aspect Ratio (MAR) - đo độ mở của miệng từ 6 điểm landmark."""

from utils.helper import distance

# Chỉ số landmark MediaPipe FaceMesh cho miệng (theo thứ tự MAR).
MOUTH_INDEXES = [61, 81, 13, 291, 311, 14]


def calculate_mar(mouth_points):
    vertical_1 = distance(mouth_points[1], mouth_points[5])
    vertical_2 = distance(mouth_points[2], mouth_points[4])

    horizontal = distance(mouth_points[0], mouth_points[3])

    if horizontal == 0:
        return 0.0

    mar = (vertical_1 + vertical_2) / (2.0 * horizontal)

    return mar
