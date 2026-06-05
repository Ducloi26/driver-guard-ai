"""
WP4 - Cổng đăng nhập admin, xác thực qua DATABASE (bảng profiles).

Tài khoản admin lưu ở profiles (username + password_hash). Test mock hàm
get_admin_by_username để không phụ thuộc Supabase/mạng. Dùng /settings cho
kiểm tra phân quyền vì route này chỉ render template.
"""
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import app as webapp

FAKE_ADMIN = {
    "id": "admin-id",
    "company_id": "company-1",
    "username": "admin",
    "full_name": "Admin Demo",
    "password_hash": generate_password_hash("secret123"),
    "role": "admin",
}


def fake_lookup(username):
    return FAKE_ADMIN if username == "admin" else None


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()

    def tearDown(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    def _login(self, username, password):
        with patch.object(webapp, "get_admin_by_username", side_effect=fake_lookup):
            return self.client.post(
                "/login", data={"username": username, "password": password})

    # --- Khu admin: phải đăng nhập ---
    def test_admin_route_redirects_when_not_logged_in(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_admin_route_accessible_after_login(self):
        self._login("admin", "secret123")
        self.assertEqual(self.client.get("/settings").status_code, 200)

    # --- Khu tài xế: công khai ---
    def test_camera_page_is_public(self):
        self.assertEqual(self.client.get("/camera").status_code, 200)

    def test_camera_status_is_public(self):
        self.assertEqual(self.client.get("/camera_status").status_code, 200)

    # --- Luồng đăng nhập qua DB ---
    def test_login_wrong_password_fails(self):
        resp = self._login("admin", "wrong")
        self.assertEqual(resp.status_code, 200)  # ở lại trang login
        self.assertEqual(self.client.get("/settings").status_code, 302)

    def test_login_unknown_user_fails(self):
        resp = self._login("ghost", "secret123")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get("/settings").status_code, 302)

    def test_login_success_redirects_to_dashboard(self):
        resp = self._login("admin", "secret123")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/dashboard", resp.headers["Location"])

    def test_logout_clears_session(self):
        self._login("admin", "secret123")
        self.client.get("/logout")
        self.assertEqual(self.client.get("/settings").status_code, 302)


if __name__ == "__main__":
    unittest.main()
