# ==============================================================
# database.py
# Tầng duy nhất được phép nói chuyện với Supabase.
# app.py sẽ import và gọi các hàm ở đây, không tự query DB.
# ==============================================================

import os                          # Đọc biến môi trường (.env)
import logging                     # Ghi log lỗi ra terminal thay vì print
from datetime import datetime, timezone, timedelta  # Xử lý thời gian
from zoneinfo import ZoneInfo      # Xử lý múi giờ (Python 3.9+, không cần cài thêm)
from dotenv import load_dotenv     # Nạp file .env vào os.environ
from supabase import create_client, Client  # SDK chính để kết nối Supabase

# Nạp .env ngay khi file này được import
# Nếu không có dòng này, os.getenv(...) sẽ trả về None
load_dotenv()

# Tạo logger riêng cho file này
# Khi lỗi xảy ra, terminal sẽ in: "database - ERROR - ..."
logger = logging.getLogger(__name__)

# Cache Supabase client để tránh tạo mới mỗi lần gọi hàm
# None = chưa khởi tạo, sẽ được tạo lần đầu trong get_supabase_client()
_supabase_client = None


# ==============================================================
# PHẦN 1: KẾT NỐI VÀ CẤU HÌNH
# ==============================================================

def get_supabase_client() -> Client:
    """
    Tạo và trả về một Supabase client. Có cache: chỉ tạo mới 1 lần.

    Tại sao dùng service role key thay vì anon key?
      - anon key bị RLS (Row Level Security) chặn nếu chưa cấu hình policy
      - service role key bypass toàn bộ RLS → dùng cho server-side code
      - KHÔNG BAO GIỜ để service role key lộ ra frontend

    Tại sao cache client?
      - Tạo client mới mỗi request tốn tài nguyên không cần thiết
      - Client là stateless (không giữ session) → dùng chung an toàn

    Returns:
        Client: object dùng để gọi .table(), .storage, v.v.

    Raises:
        ValueError: nếu thiếu biến môi trường
    """
    global _supabase_client

    # Nếu đã tạo trước đó thì dùng lại, không tạo mới
    if _supabase_client is not None:
        return _supabase_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    # Kiểm tra sớm, báo lỗi rõ ràng thay vì để crash ở chỗ khác
    if not url or not key:
        raise ValueError(
            "Thiếu SUPABASE_URL hoặc SUPABASE_SERVICE_ROLE_KEY trong .env"
        )

    # create_client trả về object Client
    # Client này có các method: .table(), .auth, .storage, .rpc()
    _supabase_client = create_client(url, key)
    return _supabase_client


def get_default_company_id() -> str:
    """
    Lấy company_id mặc định từ .env.

    Tại sao cần hàm riêng?
      - Nhiều hàm khác đều cần company_id
      - Nếu sau này đổi logic (lấy từ session thay vì .env),
        chỉ cần sửa 1 chỗ này

    Returns:
        str: UUID dạng "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

    Raises:
        ValueError: nếu chưa set DEFAULT_COMPANY_ID trong .env
    """
    company_id = os.getenv("DEFAULT_COMPANY_ID")

    if not company_id:
        raise ValueError("Thiếu DEFAULT_COMPANY_ID trong .env")

    return company_id.strip()  # .strip() phòng trường hợp có khoảng trắng thừa


def clean_form_data(form) -> dict:
    """
    Làm sạch dữ liệu từ HTML form trước khi insert vào DB.

    Tại sao cần hàm này?
      - request.form trả về chuỗi, DB cần đúng kiểu dữ liệu
      - Field rỗng từ form = chuỗi "", DB cần None (NULL)
      - Khoảng trắng thừa (user nhấn space) phải được loại bỏ

    Args:
        form: request.form từ Flask (ImmutableMultiDict)

    Returns:
        dict: dữ liệu đã được xử lý, sẵn sàng insert vào DB
    """

    def to_none_if_empty(value):
        """Chuỗi rỗng hoặc chỉ có khoảng trắng → None (NULL trong DB)"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None  # "" → None, "abc" → "abc"

    def parse_date(value):
        """
        HTML date input trả về chuỗi "YYYY-MM-DD".
        Supabase date column nhận "YYYY-MM-DD" → không cần convert.
        Chỉ cần validate format hợp lệ.
        """
        cleaned = to_none_if_empty(value)
        if cleaned is None:
            return None
        try:
            # Thử parse để validate, nếu sai format sẽ raise ValueError
            datetime.strptime(cleaned, "%Y-%m-%d")
            return cleaned  # Trả về string gốc, Supabase tự hiểu
        except ValueError:
            logger.warning(f"Date format không hợp lệ: {value}")
            return None

    return {
        # form.get('tên_field') khớp với attribute name="..." trong HTML
        "full_name":      to_none_if_empty(form.get("full_name")),
        "phone":          to_none_if_empty(form.get("phone")),
        "email":          to_none_if_empty(form.get("email")),
        "date_of_birth":  parse_date(form.get("date_of_birth")),
        "license_number": to_none_if_empty(form.get("license_number")),
        "address":        to_none_if_empty(form.get("address")),
        "driver_code":    to_none_if_empty(form.get("driver_code")),
        # status từ <select>, default 'active' nếu không có
        "status":         form.get("status", "active"),
    }


# ==============================================================
# PHẦN 2: CRUD TÀI XẾ (DRIVERS)
# ==============================================================

def get_all_drivers() -> list:
    """
    Lấy tất cả tài xế đang hoạt động của công ty.

    Soft delete: bảng drivers dùng cột `status` thay vì xóa thật.
    Tài xế bị xóa sẽ có status='inactive', không hiện trong danh sách.

    Returns:
        list[dict]: danh sách tài xế, mỗi phần tử là 1 dict.
                    Trả về [] nếu không có hoặc lỗi.

    Ví dụ 1 phần tử trong list:
        {
            "id": "uuid...",
            "full_name": "Nguyễn Văn A",
            "driver_code": "DRV001",
            "status": "active",
            ...
        }
    """
    try:
        supabase = get_supabase_client()
        company_id = get_default_company_id()

        response = (
            supabase
            .table("drivers")           # Chọn bảng
            .select("*")               # Lấy tất cả cột (* = all columns)
            .eq("company_id", company_id)   # WHERE company_id = ?
            .neq("status", "inactive")     # AND status != 'inactive'
                                            # (hiện cả active và suspended)
            .order("created_at", desc=True) # ORDER BY created_at DESC
            .execute()                      # Thực thi query, trả về response
        )

        # response.data là list[dict] chứa kết quả
        # Nếu không có row nào, response.data = []
        return response.data

    except Exception as e:
        # Không để lỗi DB làm crash cả app
        # In lỗi ra terminal để debug, trả về [] để UI vẫn chạy
        logger.error(f"get_all_drivers() lỗi: {e}")
        return []


def get_driver_by_id(driver_id: str) -> dict | None:
    """
    Lấy thông tin chi tiết 1 tài xế theo ID.

    Tại sao không dùng .single()?
      - .single() raise exception khi không tìm thấy row → khó phân biệt
        "lỗi thật" và "không có dữ liệu"
      - Dùng .limit(1) + kiểm tra response.data an toàn hơn

    Tại sao lọc thêm company_id?
      - Backend dùng service role key, bypass RLS hoàn toàn
      - Phải tự lọc để tránh lấy nhầm tài xế của công ty khác

    Args:
        driver_id (str): UUID của tài xế, lấy từ URL (vd: /drivers/abc-123)

    Returns:
        dict: thông tin tài xế nếu tìm thấy
        None: nếu không tìm thấy hoặc lỗi
    """
    try:
        supabase = get_supabase_client()
        company_id = get_default_company_id()

        response = (
            supabase
            .table("drivers")
            .select("*")
            .eq("id", driver_id)             # WHERE id = driver_id
            .eq("company_id", company_id)    # AND company_id = ? (bảo vệ đa công ty)
            .limit(1)                        # Chỉ lấy tối đa 1 row, không raise exception
            .execute()
        )

        # response.data là list: có phần tử thì lấy [0], không có thì None
        if response.data:
            return response.data[0]
        return None

    except Exception as e:
        logger.error(f"get_driver_by_id({driver_id}) lỗi: {e}")
        return None


def add_driver(driver_data: dict) -> tuple[bool, str]:
    """
    Thêm tài xế mới vào DB.

    Tại sao trả về tuple(bool, str) thay vì chỉ dict?
      - Route cần biết: thành công hay thất bại?
      - Nếu thất bại: thông báo lỗi là gì để hiện cho user?
      - tuple(True, "Thêm thành công") hoặc tuple(False, "Lý do lỗi")

    Args:
        driver_data (dict): kết quả từ clean_form_data()

    Returns:
        tuple[bool, str]:
            (True, "Thêm tài xế thành công")
            (False, "Họ tên không được để trống")
            (False, "Số GPLX đã tồn tại trong hệ thống")
    """
    # --- VALIDATE TRƯỚC KHI GỬI LÊN DB ---
    # Kiểm tra các field bắt buộc ngay tại đây, không để DB báo lỗi
    if not driver_data.get("full_name"):
        return False, "Họ tên không được để trống"

    # Kiểm tra status hợp lệ (phải khớp constraint trong DB)
    valid_statuses = ("active", "inactive", "suspended")
    if driver_data.get("status") not in valid_statuses:
        driver_data["status"] = "active"  # Fallback về mặc định

    try:
        supabase = get_supabase_client()

        # Gộp dữ liệu form với các field hệ thống
        # {**a, **b} = merge 2 dict, key của b ghi đè a nếu trùng
        insert_data = {
            **driver_data,                              # Dữ liệu từ form
            "company_id": get_default_company_id(),    # Thêm company_id
            # id, created_at, updated_at: Supabase tự tạo (có default)
        }

        response = (
            supabase
            .table("drivers")
            .insert(insert_data)   # INSERT INTO drivers (...) VALUES (...)
            .execute()
        )

        # insert trả về list các row vừa insert
        if response.data:
            return True, "Thêm tài xế thành công"
        else:
            return False, "Không thể thêm tài xế, vui lòng thử lại"

    except Exception as e:
        error_msg = str(e)
        logger.error(f"add_driver() lỗi: {error_msg}")

        # Phân tích lỗi từ Supabase để báo user rõ hơn
        # unique violation = trùng giá trị ở cột có UNIQUE constraint
        if "unique" in error_msg.lower() or "duplicate" in error_msg.lower():
            if "driver_code" in error_msg:
                return False, "Mã tài xế đã tồn tại trong hệ thống"
            if "license_number" in error_msg:
                return False, "Số GPLX đã tồn tại trong hệ thống"
            return False, "Dữ liệu bị trùng lặp, vui lòng kiểm tra lại"

        return False, "Lỗi hệ thống, vui lòng thử lại"


def update_driver(driver_id: str, driver_data: dict) -> tuple[bool, str]:
    """
    Cập nhật thông tin tài xế.

    Tại sao lọc thêm company_id trong WHERE?
      - Đảm bảo chỉ update tài xế thuộc đúng công ty
      - Nếu driver_id không tồn tại hoặc thuộc công ty khác
        → response.data rỗng → trả về lỗi rõ ràng

    Args:
        driver_id (str): UUID của tài xế cần update
        driver_data (dict): dict chứa các field muốn thay đổi

    Returns:
        tuple[bool, str]: (True/False, thông báo)
    """
    if not driver_data.get("full_name"):
        return False, "Họ tên không được để trống"

    try:
        supabase = get_supabase_client()
        company_id = get_default_company_id()

        # Chỉ update các field được phép
        # KHÔNG để user tự thay đổi: id, company_id, created_at
        allowed_fields = [
            "full_name", "phone", "email", "date_of_birth",
            "license_number", "address", "driver_code", "status"
        ]
        # Lọc chỉ giữ các key có trong allowed_fields
        safe_data = {k: v for k, v in driver_data.items() if k in allowed_fields}

        # Validate status: chỉ chấp nhận 3 giá trị hợp lệ (khớp DB constraint)
        valid_statuses = ("active", "inactive", "suspended")
        if safe_data.get("status") not in valid_statuses:
            safe_data["status"] = "active"  # Fallback về mặc định nếu sai

        # Thêm updated_at thủ công vì trigger DB có thể chưa được cấu hình
        safe_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        response = (
            supabase
            .table("drivers")
            .update(safe_data)               # UPDATE drivers SET ...
            .eq("id", driver_id)             # WHERE id = driver_id
            .eq("company_id", company_id)    # AND company_id = ? (bảo vệ đa công ty)
            .execute()
        )

        # response.data rỗng = không tìm thấy row thỏa điều kiện
        if response.data:
            return True, "Cập nhật thành công"
        else:
            return False, "Không tìm thấy tài xế để cập nhật"

    except Exception as e:
        logger.error(f"update_driver({driver_id}) lỗi: {e}")
        return False, "Lỗi hệ thống khi cập nhật"


def delete_driver(driver_id: str) -> tuple[bool, str]:
    """
    Soft delete: đánh dấu tài xế là 'inactive' thay vì xóa thật.

    Tại sao KHÔNG xóa thật (hard delete)?
      - Bảng alerts có foreign key → drivers (on delete SET NULL)
      - Nếu xóa driver, các alert liên quan mất driver_id → mất lịch sử
      - Soft delete giữ nguyên dữ liệu, chỉ ẩn khỏi UI

    Args:
        driver_id (str): UUID của tài xế cần xóa

    Returns:
        tuple[bool, str]: (True/False, thông báo)
    """
    try:
        supabase = get_supabase_client()
        company_id = get_default_company_id()

        response = (
            supabase
            .table("drivers")
            .update({
                "status": "inactive",                                    # Đánh dấu đã xóa
                "updated_at": datetime.now(timezone.utc).isoformat()    # Ghi thời gian
            })
            .eq("id", driver_id)
            .eq("company_id", company_id)    # Chỉ xóa tài xế thuộc đúng công ty
            .execute()
        )

        # response.data rỗng = không tìm thấy row thỏa điều kiện
        if response.data:
            return True, "Đã xóa tài xế khỏi hệ thống"
        else:
            return False, "Không tìm thấy tài xế"

    except Exception as e:
        logger.error(f"delete_driver({driver_id}) lỗi: {e}")
        return False, "Lỗi hệ thống khi xóa"


# ==============================================================
# PHẦN 3: ALERTS
# ==============================================================

def get_all_alerts(limit: int = 100) -> list:
    """
    Lấy danh sách cảnh báo kèm tên tài xế và biển số xe.

    Tại sao select("*, drivers(full_name), vehicles(plate_number)")?
      - alerts chỉ lưu driver_id và vehicle_id (UUID), không lưu tên/biển số
      - Supabase syntax: "*, related_table(column1, column2)"
      - Kết quả sẽ có thêm:
          {"drivers": {"full_name": "Nguyễn Văn A"},
           "vehicles": {"plate_number": "51A-123.45"}}
      - Nếu driver_id hoặc vehicle_id là NULL thì key tương ứng trả về None

    Args:
        limit (int): số lượng alert tối đa trả về (default 100)

    Returns:
        list[dict]: danh sách alert, mỗi dict có thêm key "drivers" và "vehicles"
    """
    try:
        supabase = get_supabase_client()
        company_id = get_default_company_id()

        response = (
            supabase
            .table("alerts")
            # Join lấy tên tài xế + biển số xe cùng lúc
            .select("*, drivers(full_name), vehicles(plate_number)")
            .eq("company_id", company_id)
            .order("alert_time", desc=True)   # Mới nhất lên đầu
            .limit(limit)                      # Giới hạn số lượng
            .execute()
        )

        return response.data

    except Exception as e:
        logger.error(f"get_all_alerts() lỗi: {e}")
        return []


def add_alert(alert_data: dict) -> tuple[bool, str]:
    """
    Lưu 1 cảnh báo buồn ngủ vào DB.
    Hàm này sẽ được gọi từ AI/camera module sau này.

    Args:
        alert_data (dict): cần có:
            - driver_id (UUID)
            - alert_type: 'EYES_CLOSED' | 'YAWNING' | 'HEAD_DOWN' | 'DROWSY' | 'UNKNOWN_DRIVER'
            - alert_level: 'low' | 'medium' | 'high'
            - alert_message (optional): mô tả thêm
            - ear_value, mar_value, head_status (optional): số liệu từ AI
            - vehicle_id, shift_id (optional)

    Returns:
        tuple[bool, str]: (True/False, thông báo)
    """
    # Validate alert_type vì DB có constraint
    valid_types = ("EYES_CLOSED", "YAWNING", "HEAD_DOWN", "DROWSY", "UNKNOWN_DRIVER")
    if alert_data.get("alert_type") not in valid_types:
        return False, f"alert_type không hợp lệ. Phải là một trong: {valid_types}"

    valid_levels = ("low", "medium", "high")
    if alert_data.get("alert_level", "low") not in valid_levels:
        alert_data["alert_level"] = "low"

    try:
        supabase = get_supabase_client()

        insert_data = {
            **alert_data,
            "company_id": get_default_company_id(),
            # alert_time và created_at có default now() trong DB
        }

        response = (
            supabase
            .table("alerts")
            .insert(insert_data)
            .execute()
        )

        if response.data:
            return True, "Lưu cảnh báo thành công"
        else:
            return False, "Không thể lưu cảnh báo"

    except Exception as e:
        logger.error(f"add_alert() lỗi: {e}")
        return False, "Lỗi hệ thống khi lưu cảnh báo"


def count_recent_alerts(driver_id: str, minutes: int = 5) -> int:
    """
    Đếm số cảnh báo MỨC TRUNG BÌNH HOẶC CAO của tài xế trong N phút gần nhất.
    Dùng để quyết định có gửi thông báo cho manager không.

    Tại sao chỉ đếm medium + high, bỏ qua low?
      - Alert level "low" là cảnh báo nhẹ, chưa cần can thiệp
      - Chỉ leo thang thông báo khi có alert đủ nghiêm trọng

    Tại sao lọc bằng Python thay vì .in_() của SDK?
      - Supabase Python SDK đôi khi có vấn đề với .in_() tùy version
      - Lấy ít cột (id, alert_level), lọc bằng Python: đơn giản, ít lỗi hơn

    Args:
        driver_id (str): UUID tài xế
        minutes (int): khoảng thời gian nhìn lại (default 5 phút)

    Returns:
        int: số cảnh báo medium/high. Trả về 0 nếu lỗi.
    """
    try:
        supabase = get_supabase_client()
        company_id = get_default_company_id()

        # Tính thời điểm bắt đầu cửa sổ thời gian
        # timezone.utc: dùng UTC để khớp với Supabase (luôn lưu UTC)
        threshold = datetime.now(timezone.utc) - timedelta(minutes=minutes)

        # Chuyển sang ISO format để so sánh với timestamptz trong DB
        # Ví dụ: "2024-01-15T10:30:00+00:00"
        threshold_str = threshold.isoformat()

        # Lấy id + alert_level trong khoảng thời gian, lọc Python phía dưới
        response = (
            supabase
            .table("alerts")
            .select("id, alert_level")         # Chỉ lấy 2 cột cần thiết, nhẹ hơn SELECT *
            .eq("company_id", company_id)      # Chỉ alert của công ty này
            .eq("driver_id", driver_id)
            .gte("alert_time", threshold_str)  # alert_time >= threshold
            .execute()
        )

        if not response.data:
            return 0

        # Lọc bằng Python: chỉ đếm medium và high, bỏ qua low
        filtered = [
            row for row in response.data
            if row.get("alert_level") in ("medium", "high")
        ]
        return len(filtered)

    except Exception as e:
        logger.error(f"count_recent_alerts({driver_id}) lỗi: {e}")
        return 0


# ==============================================================
# PHẦN 4: DASHBOARD
# ==============================================================

def get_dashboard_stats() -> dict:
    """
    Lấy số liệu tổng hợp cho trang dashboard.

    Tại sao tính "hôm nay" theo giờ Việt Nam thay vì UTC?
      - UTC+0: "hôm nay" bắt đầu lúc 7:00 sáng giờ VN
      - Nếu dùng UTC, alert lúc 1:00-6:59 sáng giờ VN sẽ bị tính vào "hôm qua"
      - Dùng Asia/Ho_Chi_Minh (UTC+7) để "hôm nay" = 00:00 - 23:59 giờ VN

    Returns:
        dict: {
            "total_drivers": int,       # Tổng tài xế đang hoạt động
            "total_alerts_today": int,  # Tổng cảnh báo hôm nay (giờ VN)
            "high_alerts_today": int,   # Cảnh báo mức cao hôm nay (giờ VN)
            "active_shifts": int,       # Ca làm đang diễn ra
        }
        Trả về dict với giá trị 0 nếu lỗi để template không crash.
    """
    # Giá trị mặc định, dùng nếu query lỗi
    stats = {
        "total_drivers": 0,
        "total_alerts_today": 0,
        "high_alerts_today": 0,
        "active_shifts": 0,
    }

    try:
        supabase = get_supabase_client()
        company_id = get_default_company_id()

        # --- Tính khoảng thời gian "hôm nay" theo giờ Việt Nam ---
        vn_tz = ZoneInfo("Asia/Ho_Chi_Minh")
        now_vn = datetime.now(vn_tz)

        # 00:00:00 hôm nay theo giờ VN
        today_start_vn = now_vn.replace(hour=0, minute=0, second=0, microsecond=0)
        # 00:00:00 ngày mai theo giờ VN (dùng < thay vì <= để tránh edge case)
        tomorrow_start_vn = today_start_vn + timedelta(days=1)

        # Chuyển sang UTC ISO string để query Supabase (DB lưu UTC)
        today_start_utc = today_start_vn.astimezone(timezone.utc).isoformat()
        tomorrow_start_utc = tomorrow_start_vn.astimezone(timezone.utc).isoformat()

        # --- Query 1: Đếm tài xế active ---
        r1 = (
            supabase.table("drivers")
            .select("id", count="exact")
            .eq("company_id", company_id)
            .eq("status", "active")          # Chỉ đếm active (không lấy suspended)
            .execute()
        )
        stats["total_drivers"] = r1.count or 0

        # --- Query 2: Đếm alert hôm nay (giờ VN) ---
        # Dùng >= today_start và < tomorrow_start để lấy đúng ngày hôm nay
        r2 = (
            supabase.table("alerts")
            .select("id", count="exact")
            .eq("company_id", company_id)
            .gte("alert_time", today_start_utc)      # >= 00:00:00 hôm nay (VN)
            .lt("alert_time", tomorrow_start_utc)    # <  00:00:00 ngày mai (VN)
            .execute()
        )
        stats["total_alerts_today"] = r2.count or 0

        # --- Query 3: Đếm alert HIGH hôm nay (giờ VN) ---
        r3 = (
            supabase.table("alerts")
            .select("id", count="exact")
            .eq("company_id", company_id)
            .eq("alert_level", "high")
            .gte("alert_time", today_start_utc)
            .lt("alert_time", tomorrow_start_utc)
            .execute()
        )
        stats["high_alerts_today"] = r3.count or 0

        # --- Query 4: Đếm ca đang chạy ---
        r4 = (
            supabase.table("shifts")
            .select("id", count="exact")
            .eq("company_id", company_id)
            .eq("status", "active")           # Ca đang diễn ra
            .execute()
        )
        stats["active_shifts"] = r4.count or 0

    except Exception as e:
        logger.error(f"get_dashboard_stats() lỗi: {e}")
        # Trả về stats với giá trị 0, không crash

    return stats