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


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        webapp.camera_running = False
        webapp.camera_stream = None
        webapp.current_driver_id = None
        webapp.last_frame = None
        webapp.reset_detection_state()
        self.client = webapp.app.test_client()

    def tearDown(self):
        self.client.post("/stop_camera")

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
        self.assertIn(b"--:-- - --/--", response.data)

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

    @patch.object(webapp.cv2, "VideoCapture")
    def test_start_camera_requires_driver(self, video_capture):
        response = self.client.post("/start_camera", json={})

        self.assertEqual(response.status_code, 400)
        video_capture.assert_not_called()

    @patch.object(webapp.cv2, "VideoCapture")
    def test_start_camera_reports_unavailable_device(self, video_capture):
        video_capture.return_value = FakeCamera(opened=False)

        response = self.client.post("/start_camera", json={"driver_id": "driver-1"})

        self.assertEqual(response.status_code, 503)
        self.assertFalse(webapp.camera_running)

    @patch.object(webapp.cv2, "VideoCapture")
    def test_active_camera_cannot_be_switched_to_another_driver(self, video_capture):
        video_capture.return_value = FakeCamera()

        first = self.client.post("/start_camera", json={"driver_id": "driver-1"})
        second = self.client.post("/start_camera", json={"driver_id": "driver-2"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertEqual(webapp.current_driver_id, "driver-1")


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
    @patch.object(alert_manager, "add_alert", return_value=(True, "saved"))
    def test_successful_save_starts_alert_cooldown(self, add_alert, _count_recent):
        alert_manager.process_violation("driver-1", "DROWSY", "high")
        alert_manager.process_violation("driver-1", "DROWSY", "high")

        self.assertEqual(add_alert.call_count, 1)


if __name__ == "__main__":
    unittest.main()
