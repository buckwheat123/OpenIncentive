/* OpenIncentive — progressive enhancement, no build step.
 *
 * 1) Generic table sorter (v5.0 #9): every <table class="sortable"> gets clickable
 *    headers. Numbers sort numerically (a cell can carry an explicit value via
 *    data-sort="…", otherwise we parse the visible text), dates and text sort
 *    locale-aware so Chinese columns order correctly. Click a header to toggle
 *    ascending / descending; a third click restores the original order.
 * 2) Flash banner: turns a one-line notice into a dismissible bar.
 *
 * It never fights the server: sorting is purely client-side over the rows already
 * rendered for the current BG/period selection.
 */
(function () {
  "use strict";

  function cellValue(cell) {
    if (cell.dataset && cell.dataset.sort !== undefined) return cell.dataset.sort.trim();
    return (cell.textContent || "").trim();
  }

  function parseNumber(text) {
    if (text === "" || text == null) return null;
    // strip thousands separators, a trailing %, and stray spaces; keep a leading sign
    var cleaned = String(text).replace(/[,\s\u00a0%]/g, "");
    if (cleaned === "" || cleaned === "-" || cleaned === "+") return null;
    var n = Number(cleaned);
    return isNaN(n) ? null : n;
  }

  function sortTable(table) {
    // table.rows is scoped to THIS table only (nested <table> rows are excluded),
    // which keeps run_detail's <details> sub-tables from being dragged around.
    var all = Array.prototype.slice.call(table.rows);
    var headRow = all[0];
    if (!headRow) return;
    var headers = Array.prototype.slice.call(headRow.cells);
    var body = table.tBodies.length ? table.tBodies[0] : table;
    var rows = all.slice(1);
    if (!rows.length) return;

    // Remember the default order so a third click can restore it.
    var original = rows.slice();

    headers.forEach(function (th, col) {
      if (th.classList.contains("no-sort")) return;
      th.classList.add("sortable-th");
      th.setAttribute("role", "button");
      th.setAttribute("tabindex", "0");
      th.title = "排序 / Sort";
      var dir = 0; // 0 = original, 1 = asc, -1 = desc
      th.addEventListener("click", function () { applySort(th, col); });
      th.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); applySort(th, col); }
      });

      function applySort(headerEl, index) {
        dir = dir === 1 ? -1 : 1;
        headers.forEach(function (h) {
          if (h !== headerEl) h.classList.remove("sort-asc", "sort-desc");
        });
        headerEl.classList.toggle("sort-asc", dir === 1);
        headerEl.classList.toggle("sort-desc", dir === -1);

        var extract = function (tr) { return tr.cells[index] ? cellValue(tr.cells[index]) : ""; };
        var comparator = function (a, b) {
          var av = extract(a), bv = extract(b);
          var an = parseNumber(av), bn = parseNumber(bv);
          var cmp;
          if (an !== null && bn !== null) cmp = an - bn;
          else if (an !== null) cmp = -1;           // numbers first when present
          else if (bn !== null) cmp = 1;
          else cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
          return dir * cmp;
        };
        rows.sort(comparator);
        rows.forEach(function (tr) { body.appendChild(tr); });
        renumber(table);
      }
    });

    // Double-click anywhere on the header row resets to the original ordering.
    headRow.addEventListener("dblclick", function () {
      original.forEach(function (tr) { body.appendChild(tr); });
      headers.forEach(function (h) { h.classList.remove("sort-asc", "sort-desc"); });
      renumber(table);
    });
  }

  // Opt-in row renumbering: only when the header's first cell is literally "#",
  // signalling a positional index column (never a real employee/run id).
  function renumber(table) {
    var all = Array.prototype.slice.call(table.rows);
    var head = all[0];
    if (!head || !head.cells.length || (head.cells[0].textContent || "").trim() !== "#") return;
    var rows = all.slice(1);
    var sequential = rows.length > 0 && rows.every(function (tr) {
      var c = tr.cells[0];
      return c && c.children.length === 0 && /^\d+$/.test((c.textContent || "").trim());
    });
    if (!sequential) return;
    rows.forEach(function (tr, i) { tr.cells[0].textContent = String(i + 1); });
  }

  function dismissibleMsg() {
    var msg = document.querySelector("main > .msg");
    if (msg && !msg.querySelector(".msg-close")) {
      var x = document.createElement("button");
      x.className = "msg-close";
      x.type = "button";
      x.setAttribute("aria-label", "close");
      x.textContent = "×";
      x.addEventListener("click", function () { msg.remove(); });
      msg.appendChild(x);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll("table.sortable"), sortTable);
    dismissibleMsg();
  });
})();
