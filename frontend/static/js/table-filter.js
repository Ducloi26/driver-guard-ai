// table-filter.js — Lọc bảng phía client dùng chung cho nhiều trang admin.
// Markup:
//   - 1 input  [data-filter-search]                -> tìm kiếm toàn hàng
//   - 0..n select [data-filter-col="N"]            -> lọc theo cột thứ N (0-based)
//     (option đầu phải value="" = "Tất cả"; các giá trị thật được tự đổ thêm)
//   - bảng có <tbody><tr><td>...; hàng "trống" (1 ô colspan) tự bỏ qua.
(function () {
  "use strict";

  // Hàm thuần (test được ở node): 1 hàng có khớp bộ lọc không.
  function rowMatches(rowText, cells, keyword, columnFilters) {
    if (keyword && rowText.toLowerCase().indexOf(keyword) === -1) return false;
    for (var i = 0; i < columnFilters.length; i++) {
      var f = columnFilters[i];
      if (f.value && (cells[f.col] || "").trim() !== f.value) return false;
    }
    return true;
  }

  function initTableFilter() {
    var search = document.querySelector("[data-filter-search]");
    var selects = Array.prototype.slice.call(
      document.querySelectorAll("[data-filter-col]")
    );
    var rows = Array.prototype.slice
      .call(document.querySelectorAll("tbody tr"))
      .filter(function (tr) {
        return tr.querySelectorAll("td").length > 1; // bỏ hàng "chưa có dữ liệu"
      });

    // Chế độ card: các phần tử [data-filter-item] chỉ lọc theo search (không cột).
    var items = Array.prototype.slice.call(
      document.querySelectorAll("[data-filter-item]")
    );

    if ((!rows.length && !items.length) || (!search && !selects.length)) return;

    // Đổ option thật cho mỗi select từ giá trị trong cột tương ứng.
    selects.forEach(function (sel) {
      var col = parseInt(sel.getAttribute("data-filter-col"), 10);
      var values = rows.map(function (tr) {
        var cells = tr.querySelectorAll("td");
        return cells[col] ? cells[col].textContent.trim() : "";
      });
      var unique = values
        .filter(function (v, i, a) {
          return v && a.indexOf(v) === i;
        })
        .sort();
      unique.forEach(function (v) {
        var o = document.createElement("option");
        o.value = v;
        o.textContent = v;
        sel.appendChild(o);
      });
    });

    function apply() {
      var keyword = search ? search.value.trim().toLowerCase() : "";
      var columnFilters = selects.map(function (sel) {
        return {
          col: parseInt(sel.getAttribute("data-filter-col"), 10),
          value: sel.value,
        };
      });
      rows.forEach(function (tr) {
        var cells = Array.prototype.map.call(
          tr.querySelectorAll("td"),
          function (td) {
            return td.textContent;
          }
        );
        tr.style.display = rowMatches(tr.textContent, cells, keyword, columnFilters)
          ? ""
          : "none";
      });
      items.forEach(function (it) {
        it.style.display = rowMatches(it.textContent, [], keyword, [])
          ? ""
          : "none";
      });
    }

    if (search) search.addEventListener("input", apply);
    selects.forEach(function (sel) {
      sel.addEventListener("change", apply);
    });
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", initTableFilter);
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { rowMatches: rowMatches };
  }
})();
