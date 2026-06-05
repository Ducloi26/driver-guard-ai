"""
WP5 - Tổng hợp số liệu thống kê cảnh báo (hàm thuần, test không cần DB).

aggregate_alert_stats nhận list alert (như get_all_alerts trả về) + mốc ngày
'today' để chia cửa sổ N ngày, trả về dữ liệu cho trang /stats.
"""
import unittest
from datetime import date
from unittest.mock import patch

import app as webapp
from database import aggregate_alert_stats


def A(alert_type, level, time_, name):
    return {
        "alert_type": alert_type,
        "alert_level": level,
        "alert_time": time_,
        "drivers": {"full_name": name} if name else None,
    }


TODAY = date(2026, 6, 5)


class AggregateAlertStatsTests(unittest.TestCase):
    def setUp(self):
        # Dùng giờ 02:00 UTC -> 09:00 VN cùng ngày, tránh lệch ngày khi +7.
        self.alerts = [
            A("DROWSY", "high", "2026-06-05T02:00:00+00:00", "Tài xế A"),
            A("DROWSY", "high", "2026-06-05T03:00:00+00:00", "Tài xế A"),
            A("YAWNING", "low", "2026-06-04T02:00:00+00:00", "Tài xế B"),
            A("EYES_CLOSED", "low", "2026-05-01T02:00:00+00:00", "Tài xế C"),  # ngoài cửa sổ 7 ngày
        ]
        self.stats = aggregate_alert_stats(self.alerts, days=7, today=TODAY)

    def test_total_counts_all_alerts(self):
        self.assertEqual(self.stats["total"], 4)

    def test_by_type(self):
        self.assertEqual(self.stats["by_type"]["DROWSY"], 2)
        self.assertEqual(self.stats["by_type"]["YAWNING"], 1)
        self.assertEqual(self.stats["by_type"]["EYES_CLOSED"], 1)
        self.assertEqual(self.stats["by_type"]["HEAD_DOWN"], 0)

    def test_high_count(self):
        self.assertEqual(self.stats["high_count"], 2)

    def test_by_day_has_window_length_and_buckets(self):
        self.assertEqual(len(self.stats["by_day"]), 7)
        last = self.stats["by_day"][-1]   # hôm nay 05/06
        self.assertEqual(last["label"], "05/06")
        self.assertEqual(last["count"], 2)
        self.assertEqual(self.stats["by_day"][-2]["count"], 1)  # 04/06

    def test_by_day_excludes_out_of_window(self):
        total_in_window = sum(d["count"] for d in self.stats["by_day"])
        self.assertEqual(total_in_window, 3)  # 4 alert nhưng 1 nằm ngoài 7 ngày

    def test_top_drivers_sorted(self):
        top = self.stats["top_drivers"]
        self.assertEqual(top[0]["name"], "Tài xế A")
        self.assertEqual(top[0]["count"], 2)

    def test_pct_present_for_chart(self):
        # mỗi cột có pct để dựng chiều cao CSS
        for d in self.stats["by_day"]:
            self.assertIn("pct", d)
        self.assertEqual(self.stats["by_day"][-1]["pct"], 100)  # cột cao nhất

    def test_empty_alerts(self):
        s = aggregate_alert_stats([], days=7, today=TODAY)
        self.assertEqual(s["total"], 0)
        self.assertEqual(len(s["by_day"]), 7)
        self.assertEqual(s["top_drivers"], [])
        self.assertEqual(s["by_type"]["DROWSY"], 0)


class ExportAlertsRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user"] = "admin"

    def test_export_requires_login(self):
        self.assertEqual(self.client.get("/export-alerts").status_code, 302)

    def test_export_returns_csv(self):
        self._login()
        fake = [{
            "alert_time": "2026-06-05T02:00:00+00:00",
            "alert_type": "DROWSY", "alert_level": "high",
            "ear_value": 0.1, "mar_value": 0.2, "head_status": "NORMAL",
            "drivers": {"full_name": "Tài xế A"},
            "vehicles": {"plate_number": "51A-1"},
        }]
        with patch.object(webapp, "get_all_alerts", return_value=fake):
            resp = self.client.get("/export-alerts")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["Content-Type"])
        self.assertIn("attachment", resp.headers["Content-Disposition"])
        body = resp.data.decode("utf-8")
        self.assertIn("DROWSY", body)
        self.assertIn("Tài xế A", body)


if __name__ == "__main__":
    unittest.main()
