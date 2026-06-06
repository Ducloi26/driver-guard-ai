-- ==============================================================
-- Migration GĐ2: thêm tham số luồng escalation NHANH (mức cao)
-- vào bảng alert_settings để chỉnh được từ trang Cài đặt.
--
-- Chạy 1 lần trong Supabase SQL Editor.
-- Code đã co giãn: nếu CHƯA chạy migration, app vẫn hoạt động
-- (dùng giá trị mặc định 60s / 2 lần / 120s).
-- ==============================================================

alter table alert_settings
    add column if not exists high_fast_window_seconds int not null default 60,
    add column if not exists high_fast_count int not null default 2,
    add column if not exists high_escalation_cooldown_seconds int not null default 120;
