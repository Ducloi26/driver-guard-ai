// Lọc / tìm kiếm danh sách tài xế phía client.
// Dữ liệu đã được render sẵn trong bảng nên không cần gọi API: chỉ ẩn/hiện hàng
// dựa trên các filter. Mỗi <tr> mang sẵn data-name/data-vehicle/data-shift/data-status.

(function () {
    const search = document.getElementById("driver-search");
    const vehicleSelect = document.getElementById("filter-vehicle");
    const shiftSelect = document.getElementById("filter-shift");
    const statusSelect = document.getElementById("filter-status");

    // Chỉ lấy các hàng tài xế thật (hàng "Chưa có tài xế" không có data-name).
    const rows = Array.from(document.querySelectorAll("tbody tr[data-name]"));

    if (!search || rows.length === 0) {
        return;
    }

    // Đổ option cho dropdown từ giá trị thật trong bảng để filter luôn khớp dữ liệu.
    function fillOptions(select, values) {
        const unique = [...new Set(values)].filter(Boolean).sort();
        unique.forEach(function (value) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = value;
            select.appendChild(option);
        });
    }

    fillOptions(vehicleSelect, rows.map((row) => row.dataset.vehicle));
    fillOptions(shiftSelect, rows.map((row) => row.dataset.shift));

    function applyFilters() {
        const keyword = search.value.trim().toLowerCase();
        const vehicle = vehicleSelect.value;
        const shift = shiftSelect.value;
        const status = statusSelect.value;

        rows.forEach(function (row) {
            const matchName = !keyword || row.dataset.name.includes(keyword);
            const matchVehicle = !vehicle || row.dataset.vehicle === vehicle;
            const matchShift = !shift || row.dataset.shift === shift;
            const matchStatus = !status || row.dataset.status === status;

            row.style.display =
                matchName && matchVehicle && matchShift && matchStatus ? "" : "none";
        });
    }

    [search, vehicleSelect, shiftSelect, statusSelect].forEach(function (element) {
        element.addEventListener("input", applyFilters);
        element.addEventListener("change", applyFilters);
    });
})();
