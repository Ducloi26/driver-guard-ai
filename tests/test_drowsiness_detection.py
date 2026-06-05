"""
WP2 - Logic phát hiện buồn ngủ theo luật >=2/3 chỉ số (Phương án A).

Quy tắc:
  - Mỗi chỉ số (mắt/miệng/đầu) "vi phạm" khi vượt ngưỡng LIÊN TỤC đủ lâu
    (mắt >=3s, miệng >=2s, đầu >=2s).
  - >=2/3 chỉ số vi phạm  -> DROWSY (high), có cảnh báo.
  - đúng 1/3 và là MẮT     -> EYES_CLOSED (low), cảnh báo nhẹ.
  - đúng 1/3 là miệng/đầu  -> chỉ hiển thị, KHÔNG cảnh báo.
  - 0 chỉ số               -> bình thường.

Thời gian được tiêm qua tham số `now` để test không phụ thuộc đồng hồ thật.
"""
import unittest

from models.drowsiness_detection import DrowsinessDetector


class DrowsinessDetectorTests(unittest.TestCase):
    def setUp(self):
        self.d = DrowsinessDetector()  # ear<0.22, mar>0.3, eyes 3s, mouth 2s, head 2s

    def test_all_normal_no_breach_no_alert(self):
        r = self.d.update(ear=0.40, mar=0.10, head_down=False, now=0.0)
        self.assertEqual(r["count"], 0)
        self.assertIsNone(r["alert_type"])

    def test_eyes_need_sustain_before_breaching(self):
        # mắt nhắm nhưng chưa đủ 3s -> chưa vi phạm
        r0 = self.d.update(ear=0.10, mar=0.10, head_down=False, now=0.0)
        self.assertFalse(r0["eyes_breaching"])
        r1 = self.d.update(ear=0.10, mar=0.10, head_down=False, now=2.9)
        self.assertFalse(r1["eyes_breaching"])

    def test_eyes_alone_triggers_light_alert_after_3s(self):
        self.d.update(ear=0.10, mar=0.10, head_down=False, now=0.0)
        r = self.d.update(ear=0.10, mar=0.10, head_down=False, now=3.0)
        self.assertTrue(r["eyes_breaching"])
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["alert_type"], "EYES_CLOSED")
        self.assertEqual(r["alert_level"], "low")

    def test_eyes_open_resets_sustain(self):
        self.d.update(ear=0.10, mar=0.10, head_down=False, now=0.0)
        self.d.update(ear=0.40, mar=0.10, head_down=False, now=1.0)  # mở mắt -> reset
        r = self.d.update(ear=0.10, mar=0.10, head_down=False, now=3.5)
        self.assertFalse(r["eyes_breaching"])  # tính lại từ 3.5, chưa đủ 3s

    def test_yawn_alone_no_alert(self):
        self.d.update(ear=0.40, mar=0.50, head_down=False, now=0.0)
        r = self.d.update(ear=0.40, mar=0.50, head_down=False, now=2.0)
        self.assertTrue(r["mouth_breaching"])
        self.assertEqual(r["count"], 1)
        self.assertIsNone(r["alert_type"])  # miệng đơn lẻ không cảnh báo

    def test_head_down_alone_no_alert(self):
        self.d.update(ear=0.40, mar=0.10, head_down=True, now=0.0)
        r = self.d.update(ear=0.40, mar=0.10, head_down=True, now=2.0)
        self.assertTrue(r["head_breaching"])
        self.assertEqual(r["count"], 1)
        self.assertIsNone(r["alert_type"])

    def test_two_indicators_trigger_drowsy_high(self):
        # mắt + đầu cùng vi phạm tại t=3.0 (mắt cần 3s, đầu cần 2s)
        self.d.update(ear=0.10, mar=0.10, head_down=True, now=0.0)
        r = self.d.update(ear=0.10, mar=0.10, head_down=True, now=3.0)
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["alert_type"], "DROWSY")
        self.assertEqual(r["alert_level"], "high")

    def test_three_indicators_drowsy_high(self):
        self.d.update(ear=0.10, mar=0.50, head_down=True, now=0.0)
        r = self.d.update(ear=0.10, mar=0.50, head_down=True, now=3.0)
        self.assertEqual(r["count"], 3)
        self.assertEqual(r["alert_type"], "DROWSY")

    def test_reset_clears_state(self):
        self.d.update(ear=0.10, mar=0.10, head_down=False, now=0.0)
        self.d.reset()
        r = self.d.update(ear=0.10, mar=0.10, head_down=False, now=3.0)
        self.assertFalse(r["eyes_breaching"])  # sau reset phải tính lại từ đầu


if __name__ == "__main__":
    unittest.main()
