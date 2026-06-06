// stats.js — Cập nhật trang Thống kê theo thời gian thực (poll /stats-data).
(function () {
  "use strict";

  var POLL_MS = 12000;

  function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function renderBars(byDay) {
    var chart = document.getElementById("chartByDay");
    if (!chart) return;
    chart.replaceChildren();
    (byDay || []).forEach(function (d) {
      var col = document.createElement("div");
      col.className = "chart-column";
      var bar = document.createElement("div");
      bar.className = "chart-bar";
      bar.style.height = (d.pct || 0) + "%";
      bar.title = d.count + " cảnh báo";
      var lbl = document.createElement("div");
      lbl.className = "chart-label";
      lbl.textContent = d.label;
      col.appendChild(bar);
      col.appendChild(lbl);
      chart.appendChild(col);
    });
  }

  function applyStats(s) {
    if (!s || !s.by_type) return;
    setText("statTotal", s.total);
    setText("statHigh", s.high_count);
    setText("statDrowsy", s.by_type.DROWSY);
    setText("statYawn", s.by_type.YAWNING);
    setText("donutTotal", s.total);
    setText("legendEyes", s.by_type.EYES_CLOSED);
    setText("legendYawn", s.by_type.YAWNING);
    setText("legendHead", s.by_type.HEAD_DOWN);
    setText("legendDrowsy", s.by_type.DROWSY);
    renderBars(s.by_day);
  }

  function currentDays() {
    var sel = document.querySelector(".stats-filters select");
    var v = sel ? parseInt(sel.value, 10) : 7;
    return v === 30 ? 30 : 7;
  }

  function refresh() {
    fetch("/stats-data?days=" + currentDays())
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (s) {
        if (s) applyStats(s);
      })
      .catch(function () {});
  }

  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", function () {
      if (!document.getElementById("chartByDay")) return;
      refresh(); // cập nhật ngay khi mở trang
      setInterval(refresh, POLL_MS);
    });
  }
})();
