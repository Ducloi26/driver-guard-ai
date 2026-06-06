import unittest
from unittest.mock import patch

import app as webapp
from models import face_recognition_model
from utils import alert_manager


class _FakeThread:
    """Thread giả chạy target ngay khi start() để test escalation xác định."""
    def __init__(self, target=None, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self):
        if self._target:
            self._target(*self._args)


# Cấu hình alert_settings giả cho test escalation (người nhận + tham số GĐ2).
_FAST_SETTINGS = {
    "telegram_chat_id": "CHAT",
    "manager_email": "EMAIL",
    "high_fast_window_seconds": 60,
    "high_fast_count": 2,
    "high_escalation_cooldown_seconds": 120,
}


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
        empty_alert_stats = {
            "total": 0, "high_count": 0,
            "by_type": {"DROWSY": 0, "EYES_CLOSED": 0, "YAWNING": 0,
                        "HEAD_DOWN": 0, "UNKNOWN_DRIVER": 0},
            "by_day": [], "top_drivers": [],
        }
        with (
            patch.object(webapp, "get_all_drivers", return_value=[]),
            patch.object(webapp, "get_dashboard_stats", return_value=stats),
            patch.object(webapp, "get_all_alerts", return_value=[]),
            patch.object(webapp, "get_alert_statistics", return_value=empty_alert_stats),
            patch.object(webapp, "get_alert_settings", return_value=dict(webapp.ALERT_SETTINGS_DEFAULTS)),
        ):
            # Trang công khai (không cần đăng nhập).
            public_paths = ["/login", "/camera"]
            for path in public_paths:
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)

            # Trang quản lý: cần đăng nhập -> set session rồi mới truy cập.
            with self.client.session_transaction() as sess:
                sess["user"] = "admin"
            admin_paths = [
                "/dashboard", "/drivers", "/vehicles", "/shifts", "/alerts",
                "/stats", "/settings", "/profile", "/add-driver",
            ]
            for path in admin_paths:
                with self.subTest(path=path):
                    self.assertEqual(self.client.get(path).status_code, 200)

    def test_settings_get_renders_current_alert_settings(self):
        current = dict(webapp.ALERT_SETTINGS_DEFAULTS)
        current["ear_threshold"] = 0.222
        with patch.object(webapp, "get_alert_settings", return_value=current):
            with self.client.session_transaction() as sess:
                sess["user"] = "admin"
            response = self.client.get("/settings")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"0.222", response.data)

    def test_settings_post_saves_and_redirects(self):
        with patch.object(webapp, "update_alert_settings", return_value=(True, "Đã lưu cài đặt")) as save:
            with self.client.session_transaction() as sess:
                sess["user"] = "admin"
            response = self.client.post("/settings", data={
                "ear_threshold": "0.25", "mar_threshold": "0.6",
                "head_down_seconds": "2", "yawn_seconds": "2",
                "alert_window_minutes": "5", "max_alert_count": "3",
                "telegram_chat_id": "-100999", "manager_email": "m@x.vn",
            })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(save.call_count, 1)
        saved = save.call_args[0][0]
        self.assertEqual(saved["ear_threshold"], 0.25)
        self.assertEqual(saved["max_alert_count"], 3)
        self.assertEqual(saved["telegram_chat_id"], "-100999")

    @patch.object(webapp, "get_admin_by_username", return_value={
        "username": "admin", "full_name": "Nguyen Quan Tri", "role": "admin",
        "password_hash": "scrypt:should-not-leak",
    })
    def test_profile_shows_logged_in_admin_without_leaking_hash(self, _get_admin):
        with self.client.session_transaction() as sess:
            sess["user"] = "admin"
        response = self.client.get("/profile")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Nguyen Quan Tri".encode(), response.data)
        self.assertNotIn(b"scrypt:should-not-leak", response.data)

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

        with self.client.session_transaction() as sess:
            sess["user"] = "admin"
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
            with self.client.session_transaction() as sess:
                sess["user"] = "admin"
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

    def _seed_eyes_state(self):
        # Tạo state "mắt đang nhắm" từ mốc now=0.0 trong detector.
        webapp.detector.update(ear=0.10, mar=0.10, head_down=False, now=0.0)

    def _eyes_breaching_at(self, now):
        return webapp.detector.update(
            ear=0.10, mar=0.10, head_down=False, now=now)["eyes_breaching"]

    def test_detection_resets_when_driver_changes(self):
        webapp.current_driver_id = "driver-A"
        self._seed_eyes_state()

        result_b = {
            "status": "RECOGNIZED",
            "driver": {"id": "driver-B", "full_name": "B"},
            "similarity": 0.95,
            "shift": None,
        }
        for _ in range(webapp.RECOGNITION_CONFIRM_FRAMES):
            webapp.stabilize_recognition(result_b)

        self.assertEqual(webapp.current_driver_id, "driver-B")
        # Đổi tài xế -> detector.reset() -> state mắt bị xóa, tính lại từ 3.0.
        self.assertFalse(self._eyes_breaching_at(3.0))

    def test_detection_resets_on_unknown_driver(self):
        webapp.current_driver_id = "driver-A"
        self._seed_eyes_state()

        result_unknown = {
            "status": "UNKNOWN_DRIVER",
            "driver": None,
            "similarity": 0.3,
        }
        for _ in range(webapp.UNKNOWN_CONFIRM_FRAMES):
            webapp.stabilize_recognition(result_unknown)

        self.assertIsNone(webapp.current_driver_id)
        self.assertFalse(self._eyes_breaching_at(3.0))

    def test_same_driver_does_not_reset(self):
        webapp.current_driver_id = "driver-A"
        self._seed_eyes_state()

        result_a = {
            "status": "RECOGNIZED",
            "driver": {"id": "driver-A", "full_name": "A"},
            "similarity": 0.95,
            "shift": None,
        }
        for _ in range(webapp.RECOGNITION_CONFIRM_FRAMES):
            webapp.stabilize_recognition(result_a)

        self.assertEqual(webapp.current_driver_id, "driver-A")
        # Cùng tài xế -> không reset -> state giữ nguyên -> tại 3.0 đã vi phạm.
        self.assertTrue(self._eyes_breaching_at(3.0))


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
        self.assertEqual(data["driver_id"], "d1")
        self.assertEqual(data["ai"]["eye_status"], "EYES OPEN")


class DetectionMathTests(unittest.TestCase):
    def test_degenerate_points_do_not_stop_detection(self):
        degenerate_points = [(0, 0), (0, 1), (0, 1), (0, 0), (0, 1), (0, 1)]

        self.assertEqual(webapp.calculate_ear(degenerate_points), 0.0)
        self.assertEqual(webapp.calculate_mar(degenerate_points), 0.0)


class FaceEncodingFormatTests(unittest.TestCase):
    def test_extract_face_encoding_vectors_supports_legacy_vector(self):
        vector = [1.0] + [0.0] * 511

        vectors = face_recognition_model.extract_face_encoding_vectors(vector)

        self.assertEqual(vectors, [vector])

    def test_compare_face_embedding_supports_multi_encoding_payload(self):
        current = [1.0] + [0.0] * 511
        weak = [0.0, 1.0] + [0.0] * 510
        strong = [1.0] + [0.0] * 511
        known_faces = [
            {
                "id": "driver-a",
                "face_encoding": {
                    "model": "Facenet512",
                    "detector": "opencv",
                    "dim": 512,
                    "encodings": [weak, strong],
                },
            },
            {
                "id": "driver-b",
                "face_encoding": [0.0, 1.0] + [0.0] * 510,
            },
        ]

        match = face_recognition_model.compare_face_embedding(current, known_faces)

        self.assertEqual(match["driver"]["id"], "driver-a")
        self.assertAlmostEqual(match["similarity"], 1.0)


class AlertManagerTests(unittest.TestCase):
    def setUp(self):
        alert_manager._last_alert_time.clear()
        alert_manager._last_escalation_time.clear()

    @patch.object(alert_manager, "add_alert", return_value=(False, "db unavailable"))
    def test_failed_database_save_can_be_retried_immediately(self, add_alert):
        alert_manager.process_violation("driver-1", "DROWSY", "high")
        alert_manager.process_violation("driver-1", "DROWSY", "high")

        self.assertEqual(add_alert.call_count, 2)

    @patch.object(alert_manager, "get_alert_settings", return_value=dict(_FAST_SETTINGS))
    @patch.object(alert_manager, "count_recent_high_alerts", return_value=0)
    @patch.object(alert_manager, "count_recent_alerts", return_value=0)
    @patch.object(alert_manager, "add_alert", return_value=(True, "fake-alert-id"))
    def test_successful_save_starts_alert_cooldown(self, add_alert, _count_recent, _count_high, _settings):
        alert_manager.process_violation("driver-1", "DROWSY", "high")
        alert_manager.process_violation("driver-1", "DROWSY", "high")

        self.assertEqual(add_alert.call_count, 1)

    def test_high_fast_escalation_triggers_on_two_high_in_window(self):
        with (
            patch.object(alert_manager, "add_alert", return_value=(True, "aid")),
            patch.object(alert_manager, "get_alert_settings", return_value=dict(_FAST_SETTINGS)),
            patch.object(alert_manager, "count_recent_high_alerts", return_value=2),
            patch.object(alert_manager, "count_recent_alerts", return_value=0),
            patch.object(alert_manager, "get_driver_by_id", return_value={"full_name": "X"}),
            patch.object(alert_manager, "_send_notifications") as notify,
            patch.object(alert_manager.threading, "Thread", _FakeThread),
        ):
            alert_manager.process_violation("driver-1", "DROWSY", "high", frame=None)

        self.assertEqual(notify.call_count, 1)
        # _send_notifications nhận đúng người nhận từ alert_settings (vị trí 8, 9).
        args = notify.call_args[0]
        self.assertEqual(args[8], "CHAT")
        self.assertEqual(args[9], "EMAIL")

    def test_high_fast_escalation_not_triggered_on_single_high(self):
        with (
            patch.object(alert_manager, "add_alert", return_value=(True, "aid")),
            patch.object(alert_manager, "get_alert_settings", return_value=dict(_FAST_SETTINGS)),
            patch.object(alert_manager, "count_recent_high_alerts", return_value=1),
            patch.object(alert_manager, "count_recent_alerts", return_value=0),
            patch.object(alert_manager, "_send_notifications") as notify,
            patch.object(alert_manager.threading, "Thread", _FakeThread),
        ):
            alert_manager.process_violation("driver-1", "DROWSY", "high", frame=None)

        self.assertEqual(notify.call_count, 0)

    def test_high_fast_count_is_configurable_from_settings(self):
        # Đặt ngưỡng xác nhận = 3 từ cài đặt: 2 high không còn đủ để gửi.
        cfg = dict(_FAST_SETTINGS, high_fast_count=3)
        with (
            patch.object(alert_manager, "add_alert", return_value=(True, "aid")),
            patch.object(alert_manager, "get_alert_settings", return_value=cfg),
            patch.object(alert_manager, "count_recent_high_alerts", return_value=2),
            patch.object(alert_manager, "count_recent_alerts", return_value=0),
            patch.object(alert_manager, "_send_notifications") as notify,
            patch.object(alert_manager.threading, "Thread", _FakeThread),
        ):
            alert_manager.process_violation("driver-1", "DROWSY", "high", frame=None)

        self.assertEqual(notify.call_count, 0)

    def test_high_fast_escalation_respects_cooldown(self):
        with (
            patch.object(alert_manager, "_is_spam", return_value=False),
            patch.object(alert_manager, "add_alert", return_value=(True, "aid")),
            patch.object(alert_manager, "get_alert_settings", return_value=dict(_FAST_SETTINGS)),
            patch.object(alert_manager, "count_recent_high_alerts", return_value=2),
            patch.object(alert_manager, "count_recent_alerts", return_value=0),
            patch.object(alert_manager, "get_driver_by_id", return_value={"full_name": "X"}),
            patch.object(alert_manager, "_send_notifications") as notify,
            patch.object(alert_manager.threading, "Thread", _FakeThread),
        ):
            alert_manager.process_violation("driver-1", "DROWSY", "high", frame=None)
            alert_manager.process_violation("driver-1", "DROWSY", "high", frame=None)

        # Lần 2 nằm trong cooldown 120s -> chỉ gửi 1 lần.
        self.assertEqual(notify.call_count, 1)


class DetectorSettingsTests(unittest.TestCase):
    """4B: ngưỡng từ alert_settings được nạp vào detector và có hiệu lực."""

    def tearDown(self):
        # Khôi phục detector về default code gốc để không ảnh hưởng test khác.
        webapp.detector.ear_threshold = 0.22
        webapp.detector.mar_threshold = 0.30
        webapp.detector.mouth_seconds = 2.0
        webapp.detector.head_seconds = 2.0
        webapp.detector.eyes_seconds = 3.0
        webapp.detector.reset()

    def test_apply_alert_settings_updates_detector_thresholds(self):
        cfg = {"ear_threshold": 0.30, "mar_threshold": 0.50,
               "yawn_seconds": 4, "head_down_seconds": 5}
        with patch.object(webapp, "get_alert_settings", return_value=cfg):
            webapp.apply_alert_settings_to_detector()

        self.assertEqual(webapp.detector.ear_threshold, 0.30)
        self.assertEqual(webapp.detector.mar_threshold, 0.50)
        self.assertEqual(webapp.detector.mouth_seconds, 4.0)
        self.assertEqual(webapp.detector.head_seconds, 5.0)
        self.assertEqual(webapp.detector.eyes_seconds, 3.0)  # giữ cố định

    def test_detector_uses_applied_ear_threshold(self):
        # EAR 0.25 không vượt default 0.22, nhưng vượt ngưỡng 0.30 từ cài đặt.
        cfg = {"ear_threshold": 0.30, "mar_threshold": 0.50,
               "yawn_seconds": 2, "head_down_seconds": 2}
        with patch.object(webapp, "get_alert_settings", return_value=cfg):
            webapp.apply_alert_settings_to_detector()

        webapp.detector.reset()
        webapp.detector.update(ear=0.25, mar=0.0, head_down=False, now=0.0)
        result = webapp.detector.update(ear=0.25, mar=0.0, head_down=False, now=10.0)
        self.assertTrue(result["eyes_breaching"])

    def test_apply_settings_survives_db_error(self):
        # Lỗi đọc settings không được làm hỏng ngưỡng hiện có / không raise.
        with patch.object(webapp, "get_alert_settings", side_effect=Exception("db down")):
            webapp.apply_alert_settings_to_detector()  # không raise
        self.assertEqual(webapp.detector.ear_threshold, 0.22)


class HighFastFlowIntegrationTests(unittest.TestCase):
    """
    Kiểm tra ĐỒNG BỘ các luồng GĐ1 theo dòng thời gian thật:
    chống spam ↔ luồng nhanh (high) ↔ luồng chậm (medium) ↔ cooldown ↔ gửi.

    Dùng DB giả trong RAM (list alert có timestamp) + đồng hồ giả để mô phỏng
    vi phạm xảy ra theo mốc giây mà không cần Supabase/thread/telegram thật.
    """

    def setUp(self):
        import unittest.mock as mock

        alert_manager._last_alert_time.clear()
        alert_manager._last_escalation_time.clear()
        self.saved = []          # [(timestamp, alert_level)]
        self.now = [1000.0]      # đồng hồ giả (giây)

        def fake_add_alert(data):
            self.saved.append((self.now[0], data.get("alert_level")))
            return True, f"id-{len(self.saved)}"

        def fake_count_high(driver_id, seconds=60):
            return sum(1 for ts, lvl in self.saved
                       if lvl == "high" and self.now[0] - ts <= seconds)

        def fake_count_recent(driver_id, minutes=5):
            window = minutes * 60
            return sum(1 for ts, lvl in self.saved
                       if lvl in ("medium", "high") and self.now[0] - ts <= window)

        mock.patch.object(alert_manager, "add_alert", side_effect=fake_add_alert).start()
        mock.patch.object(alert_manager, "count_recent_high_alerts", side_effect=fake_count_high).start()
        mock.patch.object(alert_manager, "count_recent_alerts", side_effect=fake_count_recent).start()
        mock.patch.object(alert_manager, "get_driver_by_id", return_value={"full_name": "X"}).start()
        mock.patch.object(alert_manager, "get_alert_settings", return_value=dict(_FAST_SETTINGS)).start()
        mock.patch.object(alert_manager.threading, "Thread", _FakeThread).start()
        mock.patch.object(alert_manager.time, "time", side_effect=lambda: self.now[0]).start()
        self.notify = mock.patch.object(alert_manager, "_send_notifications").start()
        self.addCleanup(mock.patch.stopall)

    def _high(self):
        alert_manager.process_violation("driver-1", "DROWSY", "high", ear=0.1, mar=0.4, frame=None)

    def _medium(self):
        alert_manager.process_violation("driver-2", "YAWNING", "medium", frame=None)

    def test_high_fast_flow_synchronized_over_timeline(self):
        # t=1000: high #1 -> lưu, mới 1 high -> chưa gửi
        self.now[0] = 1000.0; self._high()
        self.assertEqual(self.notify.call_count, 0)

        # t=1031: high #2 (qua anti-spam 30s) -> 2 high/60s -> GỬI NGAY
        self.now[0] = 1031.0; self._high()
        self.assertEqual(self.notify.call_count, 1)
        args = self.notify.call_args[0]
        self.assertEqual((args[8], args[9]), ("CHAT", "EMAIL"))  # đúng người nhận

        # t=1061: vẫn 2 high/60s nhưng trong cooldown 120s -> CHẶN
        self.now[0] = 1061.0; self._high()
        self.assertEqual(self.notify.call_count, 1)

        # t=1095: vẫn trong cooldown -> CHẶN
        self.now[0] = 1095.0; self._high()
        self.assertEqual(self.notify.call_count, 1)

        # t=1152: qua cooldown (>1031+120) và vẫn 2 high/60s -> GỬI LẠI
        self.now[0] = 1152.0; self._high()
        self.assertEqual(self.notify.call_count, 2)

    def test_medium_uses_slow_flow_not_fast(self):
        # 2 medium trong 5' -> count=2 < 3 -> chưa gửi (và high path không kích hoạt)
        self.now[0] = 2000.0; self._medium()
        self.now[0] = 2031.0; self._medium()
        self.assertEqual(self.notify.call_count, 0)

        # medium #3 -> count=3 -> escalate qua LUỒNG CHẬM
        self.now[0] = 2062.0; self._medium()
        self.assertEqual(self.notify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
