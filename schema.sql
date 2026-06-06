-- ==============================================================
-- DriverGuard AI - Supabase/PostgreSQL schema
-- Purpose: Store companies, users, drivers, vehicles, shifts,
--          alert history, and alert configuration.
-- ==============================================================

create extension if not exists "pgcrypto";

-- Doanh nghiệp vận tải sử dụng hệ thống.
create table if not exists companies (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    phone text,
    email text,
    address text,
    created_at timestamptz not null default now()
);

-- Hồ sơ người dùng quản trị/giám sát.
-- username + password_hash dùng cho đăng nhập admin (WP4 - xác thực qua DB).
create table if not exists profiles (
    id uuid primary key,
    company_id uuid references companies(id) on delete cascade,
    full_name text not null,
    phone text,
    role text not null default 'manager',
    username text unique,
    password_hash text,
    created_at timestamptz not null default now()
);

-- Migration cho DB đã tồn tại (chạy trong Supabase SQL editor):
--   alter table profiles add column if not exists username text unique;
--   alter table profiles add column if not exists password_hash text;

-- Danh sách tài xế và dữ liệu nhận diện khuôn mặt.
-- avatar_path lưu path trong Storage bucket driver-images.
-- face_encoding lưu vector khuôn mặt dạng JSONB.
create table if not exists drivers (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete cascade,
    driver_code text unique,
    full_name text not null,
    phone text,
    email text,
    date_of_birth date,
    license_number text,
    address text,
    avatar_path text,
    face_encoding jsonb,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    constraint drivers_status_check
    check (status in ('active', 'inactive', 'suspended'))
);

-- Danh sách phương tiện của doanh nghiệp.
create table if not exists vehicles (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete cascade,
    plate_number text not null unique,
    vehicle_type text,
    brand text,
    status text not null default 'active',
    created_at timestamptz not null default now(),

    constraint vehicles_status_check
    check (status in ('active', 'maintenance', 'inactive'))
);

-- Ca làm việc gán tài xế với xe theo ngày và khung giờ.
-- Đây là bảng quan hệ chính để biết tài xế đang phụ trách xe nào.
create table if not exists shifts (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete cascade,
    driver_id uuid references drivers(id) on delete set null,
    vehicle_id uuid references vehicles(id) on delete set null,
    shift_name text,
    work_date date not null default current_date,
    start_time time,
    end_time time,
    status text not null default 'scheduled',
    created_at timestamptz not null default now(),

    constraint shifts_status_check
    check (status in ('scheduled', 'active', 'completed', 'cancelled'))
);

-- Lịch sử cảnh báo AI.
-- image_path lưu path trong Storage bucket alert-captures nếu có ảnh minh chứng.
create table if not exists alerts (
    id uuid primary key default gen_random_uuid(),
    company_id uuid references companies(id) on delete cascade,
    driver_id uuid references drivers(id) on delete set null,
    vehicle_id uuid references vehicles(id) on delete set null,
    shift_id uuid references shifts(id) on delete set null,

    alert_type text not null,
    alert_level text not null default 'low',
    alert_message text,

    ear_value numeric(6, 4),
    mar_value numeric(6, 4),
    head_status text,

    image_path text,
    sent_to_manager boolean not null default false,

    alert_time timestamptz not null default now(),
    created_at timestamptz not null default now(),

    constraint alerts_type_check
    check (alert_type in ('EYES_CLOSED', 'YAWNING', 'HEAD_DOWN', 'DROWSY', 'UNKNOWN_DRIVER')),

    constraint alerts_level_check
    check (alert_level in ('low', 'medium', 'high'))
);

-- Cấu hình ngưỡng cảnh báo và kênh gửi thông báo cho quản lý.
create table if not exists alert_settings (
    id uuid primary key default gen_random_uuid(),
    company_id uuid unique references companies(id) on delete cascade,

    ear_threshold numeric(5, 3) not null default 0.220,
    mar_threshold numeric(5, 3) not null default 0.300,
    head_down_seconds int not null default 2,
    yawn_seconds int not null default 2,
    alert_window_minutes int not null default 5,
    max_alert_count int not null default 3,

    -- Luồng escalation NHANH cho mức cao (GĐ2):
    -- đủ high_fast_count sự kiện high trong high_fast_window_seconds → gửi ngay.
    high_fast_window_seconds int not null default 60,
    high_fast_count int not null default 2,
    high_escalation_cooldown_seconds int not null default 120,

    telegram_chat_id text,
    manager_email text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Index phục vụ truy vấn dashboard, lịch sử cảnh báo và lọc theo công ty.
create index if not exists idx_drivers_company_id on drivers(company_id);
create index if not exists idx_vehicles_company_id on vehicles(company_id);
create index if not exists idx_shifts_company_date on shifts(company_id, work_date);
create index if not exists idx_alerts_company_time on alerts(company_id, alert_time desc);
create index if not exists idx_alerts_driver_time on alerts(driver_id, alert_time desc);
create index if not exists idx_alerts_level_time on alerts(alert_level, alert_time desc);

-- Storage buckets cần tạo trong Supabase Dashboard:
--   driver-images   : lưu ảnh khuôn mặt tài xế
--   alert-captures  : lưu ảnh minh chứng cảnh báo
--
-- Demo hiện dùng backend Flask với service role key.
-- Khi đưa frontend gọi Supabase trực tiếp, cần bật RLS policies phù hợp.
