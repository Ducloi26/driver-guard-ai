"""
WP1 - Vision Core tách khỏi app.py.
Test các hàm tính số thuần sau khi chuyển sang models/ và utils/helper.py.
Các hàm này không phụ thuộc Flask/MediaPipe/camera nên test trực tiếp bằng số.
"""
import unittest

from utils.helper import distance
from models.ear_calculator import calculate_ear, LEFT_EYE_INDEXES, RIGHT_EYE_INDEXES
from models.mar_calculator import calculate_mar, MOUTH_INDEXES
from models.head_pose import detect_head_down, HEAD_POSE_INDEXES


class DistanceTests(unittest.TestCase):
    def test_distance_basic(self):
        self.assertAlmostEqual(distance((0, 0), (3, 4)), 5.0)

    def test_distance_zero(self):
        self.assertEqual(distance((2, 2), (2, 2)), 0.0)


class EarTests(unittest.TestCase):
    def test_open_eye_has_high_ear(self):
        # ngang=10, dọc=4 mỗi cặp -> ear = (4+4)/(2*10) = 0.4
        points = [(0, 0), (2, 2), (7, 2), (10, 0), (7, -2), (2, -2)]
        self.assertAlmostEqual(calculate_ear(points), 0.4)

    def test_closed_eye_has_low_ear(self):
        points = [(0, 0), (2, 0.2), (7, 0.2), (10, 0), (7, -0.2), (2, -0.2)]
        self.assertLess(calculate_ear(points), 0.22)

    def test_degenerate_horizontal_returns_zero(self):
        points = [(0, 0), (0, 1), (0, 1), (0, 0), (0, 1), (0, 1)]
        self.assertEqual(calculate_ear(points), 0.0)

    def test_index_constants_have_six_points(self):
        self.assertEqual(len(LEFT_EYE_INDEXES), 6)
        self.assertEqual(len(RIGHT_EYE_INDEXES), 6)


class MarTests(unittest.TestCase):
    def test_open_mouth_has_high_mar(self):
        points = [(0, 0), (2, 4), (7, 4), (10, 0), (7, -4), (2, -4)]
        self.assertAlmostEqual(calculate_mar(points), 0.8)

    def test_closed_mouth_has_low_mar(self):
        points = [(0, 0), (2, 0.2), (7, 0.2), (10, 0), (7, -0.2), (2, -0.2)]
        self.assertLess(calculate_mar(points), 0.3)

    def test_degenerate_horizontal_returns_zero(self):
        points = [(0, 0), (0, 1), (0, 1), (0, 0), (0, 1), (0, 1)]
        self.assertEqual(calculate_mar(points), 0.0)

    def test_index_constants_have_six_points(self):
        self.assertEqual(len(MOUTH_INDEXES), 6)


class _FakeLandmark:
    def __init__(self, y):
        self.y = y


class _FakeFace:
    """Giả lập face_landmarks của MediaPipe: chỉ cần .landmark[idx].y."""
    def __init__(self, nose_y, chin_y, forehead_y):
        self.landmark = {1: _FakeLandmark(nose_y),
                         152: _FakeLandmark(chin_y),
                         10: _FakeLandmark(forehead_y)}


class HeadPoseTests(unittest.TestCase):
    def test_normal_head_is_not_down(self):
        # nose ở giữa: ratio = 0.3/0.6 = 0.5 >= 0.38
        face = _FakeFace(nose_y=0.5, chin_y=0.8, forehead_y=0.2)
        self.assertFalse(detect_head_down(face, 640, 480))

    def test_head_down_when_nose_near_chin(self):
        # cúi đầu: ratio = 0.05/0.6 ~ 0.083 < 0.38
        face = _FakeFace(nose_y=0.75, chin_y=0.8, forehead_y=0.2)
        self.assertTrue(detect_head_down(face, 640, 480))

    def test_zero_forehead_distance_returns_false(self):
        face = _FakeFace(nose_y=0.5, chin_y=0.5, forehead_y=0.5)
        self.assertFalse(detect_head_down(face, 640, 480))

    def test_index_constant_present(self):
        self.assertEqual(len(HEAD_POSE_INDEXES), 6)


if __name__ == "__main__":
    unittest.main()
