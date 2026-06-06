"""
N4 - CRUD xe (Xem/Sửa/Xóa), mirror pattern CRUD tài xế.
Mock các hàm DB ở tầng webapp để test route không cần Supabase/mạng.
"""
import unittest
from unittest.mock import patch

import app as webapp

FAKE_VEHICLE = {
    "id": "v1",
    "plate_number": "51A-12345",
    "vehicle_type": "Xe khách",
    "brand": "Hyundai",
    "status": "active",
}


class VehicleCrudTests(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()

    def _login(self):
        with self.client.session_transaction() as sess:
            sess["user"] = "admin"

    def test_routes_require_login(self):
        self.assertEqual(self.client.get("/vehicles/v1").status_code, 302)
        self.assertEqual(self.client.get("/vehicles/v1/edit").status_code, 302)
        self.assertEqual(self.client.post("/vehicles/v1/delete").status_code, 302)

    def test_detail_renders(self):
        self._login()
        with patch.object(webapp, "get_vehicle_by_id", return_value=FAKE_VEHICLE):
            resp = self.client.get("/vehicles/v1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("51A-12345", resp.get_data(as_text=True))

    def test_detail_not_found_redirects(self):
        self._login()
        with patch.object(webapp, "get_vehicle_by_id", return_value=None):
            resp = self.client.get("/vehicles/v1")
        self.assertEqual(resp.status_code, 302)

    def test_edit_get_renders(self):
        self._login()
        with patch.object(webapp, "get_vehicle_by_id", return_value=FAKE_VEHICLE):
            resp = self.client.get("/vehicles/v1/edit")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("51A-12345", resp.get_data(as_text=True))

    def test_edit_post_updates_and_redirects(self):
        self._login()
        with (
            patch.object(webapp, "get_vehicle_by_id", return_value=FAKE_VEHICLE),
            patch.object(webapp, "update_vehicle", return_value=(True, "ok")) as upd,
        ):
            resp = self.client.post(
                "/vehicles/v1/edit",
                data={"plate_number": "51A-99999", "status": "active"},
            )
        self.assertEqual(resp.status_code, 302)
        upd.assert_called_once()

    def test_delete_redirects(self):
        self._login()
        with patch.object(webapp, "delete_vehicle", return_value=(True, "ok")) as dele:
            resp = self.client.post("/vehicles/v1/delete")
        self.assertEqual(resp.status_code, 302)
        dele.assert_called_once()


if __name__ == "__main__":
    unittest.main()
