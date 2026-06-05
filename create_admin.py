"""
Tạo tài khoản admin trong DB (bảng profiles) - chạy 1 lần.

Yêu cầu: đã chạy ALTER TABLE thêm cột username + password_hash vào profiles
(xem schema.sql). Sau đó:

    python create_admin.py

Nhập username + mật khẩu, script sẽ băm mật khẩu và insert vào DB.
"""
import getpass

from werkzeug.security import generate_password_hash

from database import create_admin


def main():
    print("=== Tạo tài khoản admin DriverGuard AI ===")
    username = input("Username: ").strip()
    if not username:
        print("Username không được trống.")
        return

    password = getpass.getpass("Mật khẩu: ")
    confirm = getpass.getpass("Nhập lại mật khẩu: ")
    if password != confirm:
        print("Mật khẩu nhập lại không khớp.")
        return
    if len(password) < 6:
        print("Mật khẩu nên dài ít nhất 6 ký tự.")
        return

    full_name = input("Họ tên hiển thị: ").strip() or username

    ok, msg = create_admin(username, generate_password_hash(password), full_name)
    print(("[OK] " if ok else "[Lỗi] ") + msg)


if __name__ == "__main__":
    main()
