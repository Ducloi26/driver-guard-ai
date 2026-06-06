// alerts.js — Modal "Xem" chi tiết cảnh báo (đọc dữ liệu sẵn có trong hàng).
(function () {
  "use strict";

  // Hàm thuần (test được ở node): ghép header + cell thành danh sách hiển thị.
  function buildDetailRows(headers, cells) {
    var rows = [];
    for (var i = 0; i < headers.length; i++) {
      if (headers[i] === "Hành động") continue;
      rows.push({ label: headers[i], value: cells[i] !== undefined ? cells[i] : "" });
    }
    return rows;
  }

  function openModal(tr) {
    var headers = Array.prototype.map.call(
      document.querySelectorAll("table thead th"),
      function (th) { return th.textContent.trim(); }
    );
    var cells = Array.prototype.map.call(
      tr.querySelectorAll("td"),
      function (td) { return td.textContent.trim(); }
    );
    var body = document.getElementById("alertDetailBody");
    if (!body) return;
    body.replaceChildren();
    buildDetailRows(headers, cells).forEach(function (r) {
      var row = document.createElement("div");
      row.className = "info-row";
      var s = document.createElement("span");
      s.textContent = r.label;
      var st = document.createElement("strong");
      st.textContent = r.value || "--";
      row.appendChild(s);
      row.appendChild(st);
      body.appendChild(row);
    });
    var m = document.getElementById("alertDetailModal");
    if (m) m.style.display = "flex";
  }

  function closeAlertModal() {
    var m = document.getElementById("alertDetailModal");
    if (m) m.style.display = "none";
  }
  if (typeof window !== "undefined") window.closeAlertModal = closeAlertModal;

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", function () {
      document.querySelectorAll(".btn-view").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var tr = btn.closest("tr");
          if (tr) openModal(tr);
        });
      });
    });
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { buildDetailRows: buildDetailRows };
  }
})();
