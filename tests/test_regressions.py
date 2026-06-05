import unittest
from unittest.mock import patch

import app as webapp
from utils import alert_manager


class FakeCamera:
    def __init__(self, opened=True):
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def release(self):
        self.released = True

    def read(self):
        return False, None


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        webapp.camera_running = False
        webapp.camera_stream = None
        webapp.current_driver_id = None
        webapp.last_frame = None
        webapp.reset_detection_state()
        self.client = webapp.app.test_client()

    def tearDown(self):
        webapp.camera_running = False
        webapp.camera_stream = None

    def test_all_page_routes_render_without_database_services(self):
        stats = {
            "total_drivers": 0,
            "total_alerts_today": 0,
            "high_alerts_today": 0,
            "active_shifts": 0,
        }
        with (
            patch.object(webapp, "get_all_drivers", return_value=[]),
            patch.object(webapp, "get_dashboard_stats", return_value=stats),
            patch.object(webapp, "get_all_alerts", return_value=[]),
        ):
            paths = [
                "/", "/login", "/register", "/dashboard", "/drivers",
                "/vehicles", "/shifts", "/camera", "/alerts", "/stats",
                "/settings", "/profile", "/add-driver",
            ]
            for path in paths:
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)

    @patch.object(webapp, "get_all_alerts")
    def test_alerts_page_handles_missing_alert_time(self, get_all_alerts):
        get_all_alerts.return_value = [{
            "alert_type": "DROWSY",
            "alert_level": "high",
            "alert_time": None,
            "drivers": None,
            "vehicles": None,
            "ear_value": None,
            "mar_value": None,
            "head_status": None,
        }]

        response = self.client.get("/alerts")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Traceback", response.data)

    def test_dashboard_uses_live_summary_and_recent_alert_data(self):
        stats = {
            "total_drivers": 3,
            "total_alerts_today": 2,
            "high_alerts_today": 1,
            "active_shifts": 1,
        }
        recent_alert = {
            "alert_type": "DROWSY",
            "alert_level": "high",
            "alert_time": "2026-05-24T08:21:02",
            "drivers": {"full_name": "Driver Live"},
            "vehicles": None,
        }
        with (
            patch.object(webapp, "get_dashboard_stats", return_value=stats),
            patch.object(webapp, "get_all_alerts", return_value=[recent_alert]),
        ):
            response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Driver Live", response.data)
        self.assertIn(b">3</div>", response.data)

    @patch.object(webapp, "refresh_known_face_drivers")
    @patch.object(webapp, "start_recognition_worker")
    @patch.object(webapp.cv2, "VideoCapture")
    def test_start_camera_succeeds_without_driver_id(self, video_capture, _worker, _refresh):
        video_capture.return_value = FakeCamera(opened=True)

        response = self.client.post("/start_camera")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(webapp.camera_running)

    @patch.object(webapp, "refresh_known_face_drivers")
    @patch.object(webapp.cv2, "VideoCapture")
    def test_start_camera_reports_unavailable_device(self, video_capture, _refresh):
        video_capture.return_value = FakeCamera(opened=False)

        response = self.client.post("/start_camera")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(webapp.camera_running)

    @patch.object(webapp, "refresh_known_face_drivers")
    @patch.object(webapp, "start_recognition_worker")
    @patch.object(webapp.cv2, "VideoCapture")
    def test_start_camera_idempotent_when_already_running(self, video_capture, _worker, _refresh):
        video_capture.return_value = FakeCamera(opened=True)

        first = self.client.post("/start_camera")
        second = self.client.post("/start_camera")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        video_capture.assert_called_once()


class DetectionResetTests(unittest.TestCase):
    def setUp(self):
        webapp.camera_running = True
        webapp.current_driver_id = None
        webapp.pending_recognition_key = None
        webapp.pending_recognition_count = 0
        webapp.reset_detection_state()

    def test_detection_resets_when_driver_changes(self):
        webapp.current_driver_id = "driver-A"
        webapp.closed_counter = 50
        webapp.blink_counter = 10

        result_b = {
            "status": "RECOGNIZED",
            "driver": {"id": "driver-B", "full_name": "B"},
            "similarity": 0.95,
            "shift": None,
        }
        for _ in range(webapp.RECOGNITION_CONFIRM_FRAMES):
            webapp.stabilize_recognition(result_b)

        self.assertEqual(webapp.current_driver_id, "driver-B")
        self.assertEqual(webapp.closed_counter, 0)
        self.assertEqual(webapp.blink_counter, 0)

    def test_detection_resets_on_unknown_driver(self):
        webapp.current_driver_id = "driver-A"
        webapp.closed_counter = 30

        result_unknown = {
            "status": "UNKNOWN_DRIVER",
            "driver": None,
            "similarity": 0.3,
        }
        for _ in range(webapp.UNKNOWN_CONFIRM_FRAMES):
            webapp.stabilize_recognition(result_unknown)

        self.assertIsNone(webapp.current_driver_id)
        self.assertEqual(webapp.closed_counter, 0)

    def test_same_driver_does_not_reset(self):
        webapp.current_driver_id = "driver-A"
        webapp.closed_counter = 50

        result_a = {
            "status": "RECOGNIZED",
            "driver": {"id": "driver-A", "full_name": "A"},
            "similarity": 0.95,
            "shift": None,
        }
        for _ in range(webapp.RECOGNITION_CONFIRM_FRAMES):
            webapp.stabilize_recognition(result_a)

        self.assertEqual(webapp.current_driver_id, "driver-A")
        self.assertEqual(webapp.closed_counter, 50)


class CameraStatusAITests(unittest.TestCase):
    def setUp(self):
        webapp.camera_running = False
        webapp.camera_stream = None
        webapp.current_driver_id = None
        webapp.reset_detection_state()
        webapp.last_recognition_result = {
            "status": "NOT_READY",
            "driver": None,
            "similarity": 0.0,
            "shift": None,
        }
        self.client = webapp.app.test_client()

    def test_camera_status_includes_ai_state(self):
        response = self.client.get("/camera_status")
        data = response.get_json()

        self.assertIn("ai", data)
        ai = data["ai"]
        self.assertIn("eye_status", ai)
        self.assertIn("mouth_status", ai)
        self.assertIn("head_status", ai)
        self.assertIn("drowsy_status", ai)
        self.assertIn("ear", ai)
        self.assertIn("mar", ai)

    def test_ai_state_default_values_after_reset(self):
        webapp.reset_detection_state()
        response = self.client.get("/camera_status")
        ai = response.get_json()["ai"]

        self.assertEqual(ai["eye_status"], "NO FACE")
        self.assertEqual(ai["mouth_status"], "NORMAL")
        self.assertEqual(ai["head_status"], "NORMAL")
        self.assertEqual(ai["drowsy_status"], "NORMAL")
        self.assertIsNone(ai["ear"])
        self.assertIsNone(ai["mar"])

    def test_ai_state_reflects_updated_values(self):
        webapp.latest_ai_state = {
            "eye_status": "EYES CLOSED",
            "mouth_status": "YAWNING",
            "head_status": "HEAD DOWN",
            "drowsy_status": "DROWSY",
            "ear": 0.18,
            "mar": 0.45,
            "blink_counter": 5,
            "tired_event_counter": 2,
            "yawn_counter": 3,
        }

        response = self.client.get("/camera_status")
        ai = response.get_json()["ai"]

        self.assertEqual(ai["eye_status"], "EYES CLOSED")
        self.assertEqual(ai["mouth_status"], "YAWNING")
        self.assertEqual(ai["head_status"], "HEAD DOWN")
        self.assertEqual(ai["drowsy_status"], "DROWSY")
        self.assertEqual(ai["ear"], 0.18)
        self.assertEqual(ai["mar"], 0.45)

    def test_ai_state_present_when_recognized(self):
        webapp.last_recognition_result = {
            "status": "RECOGNIZED",
            "driver": {"id": "d1", "full_name": "Test", "driver_code": "T1", "phone": "123"},
            "similarity": 0.95,
            "shift": {"shift_name": "Ca 1", "start_time": "08:00", "end_time": "17:00", "vehicles": {"plate_number": "51A-111"}},
        }
        webapp.latest_ai_state["eye_status"] = "EYES OPEN"

        response = self.client.get("/camera_status")
        data = response.get_json()

        self.assertEqual(data["status"], "RECOGNIZED")
        self.assertEqual(data["ai"]["eye_status"], "EYES OPEN")


class DetectionMathTests(unittest.TestCase):
    def test_degenerate_points_do_not_stop_detection(self):
        degenerate_points = [(0, 0), (0, 1), (0, 1), (0, 0), (0, 1), (0, 1)]

        self.assertEqual(webapp.calculate_ear(degenerate_points), 0.0)
        self.assertEqual(webapp.calculate_mar(degenerate_points), 0.0)


class AlertManagerTests(unittest.TestCase):
    def setUp(self):
        alert_manager._last_alert_time.clear()
        alert_manager._last_escalation_time.clear()

    @patch.object(alert_manager, "add_alert", return_value=(False, "db unavailable"))
    def test_failed_database_save_can_be_retried_immediately(self, add_alert):
        alert_manager.process_violation("driver-1", "DROWSY", "high")
        alert_manager.process_violation("driver-1", "DROWSY", "high")

        self.assertEqual(add_alert.call_count, 2)

    @patch.object(alert_manager, "count_recent_alerts", return_value=0)
    @patch.object(alert_manager, "add_alert", return_value=(True, "fake-alert-id"))
    def test_successful_save_starts_alert_cooldown(self, add_alert, _count_recent):
        alert_manager.process_violation("driver-1", "DROWSY", "high")
        alert_manager.process_violation("driver-1", "DROWSY", "high")

        self.assertEqual(add_alert.call_count, 1)


if __name__ == "__main__":
    unittest.main()
