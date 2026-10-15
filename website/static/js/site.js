/* Site-wide behavior. Every page works without this file; it only adds things on top. */
(function () {
  "use strict";

  var root = document.body.getAttribute("data-root") || "./";
  var $ = function (sel, el) { return (el || document).querySelector(sel); };
  var $$ = function (sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); };

  /* ---------- Northeastern global header/footer fallback ----------
     The official header and footer load from the university CDN. If that is
     unreachable (offline, blocked), show a plain bar and the required links so
     the page never loses them. */
  if (document.body.getAttribute("data-global") === "true") {
    window.addEventListener("load", function () {
      setTimeout(function () {
        var header = $("#nu-global-header");
        if (header && !header.children.length) {
          header.innerHTML = '<div class="wrap nu-fallback-bar"><a href="https://www.northeastern.edu/">Northeastern University</a></div>';
        }
        var footer = $("#nu-global-footer");
        if (footer && !footer.children.length) { $("#fallback-footer").hidden = false; }
      }, 3000);
    });
  } else {
    $("#nu-global-header").innerHTML = '<div class="wrap nu-fallback-bar"><a href="https://www.northeastern.edu/">Northeastern University</a></div>';
    $("#fallback-footer").hidden = false;
  }

  /* ---------- Mobile menu ---------- */
  var toggle = $(".menu-toggle"), nav = $("#site-nav");
  if (toggle && nav) {
    toggle.hidden = false;
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  /* ---------- Copy and print buttons ---------- */
  function copyText(text, btn) {
    var done = function () {
      if (!btn) return;
      var old = btn.textContent; btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = old; }, 1500);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done);
    } else {                         // plain http on the lab server is not a secure context
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (err) { /* ignore */ }
      document.body.removeChild(ta);
    }
  }
  window.LabSite = { copy: copyText };

  document.addEventListener("click", function (e) {
    var copy = e.target.closest("[data-copy]");
    if (copy) copyText(copy.getAttribute("data-copy"), copy);
    if (e.target.closest("[data-print]")) window.print();
  });

  /* ---------- Open / closed status ---------- */
  var hoursEl = $("#hours-data");
  if (hoursEl) {
    var hours = JSON.parse(hoursEl.textContent);
    var keys = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
    // Boston time, whatever the visitor's computer is set to.
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false, weekday: "short"
    }).formatToParts(new Date()).reduce(function (o, p) { o[p.type] = p.value; return o; }, {});
    var today = parts.year + "-" + parts.month + "-" + parts.day;
    var dayKey = parts.weekday.slice(0, 3).toLowerCase();
    var minutes = (parseInt(parts.hour, 10) % 24) * 60 + parseInt(parts.minute, 10);
    var toMin = function (s) { var a = s.split(":"); return +a[0] * 60 + +a[1]; };
    var fmt = function (s) {
      var h = +s.split(":")[0], m = s.split(":")[1];
      return (h % 12 || 12) + (m !== "00" ? ":" + m : "") + (h < 12 ? " AM" : " PM");
    };
    var closedOn = function (iso) {
      for (var i = 0; i < hours.closures.length; i++) if (hours.closures[i].date === iso) return hours.closures[i];
      return null;
    };

    var row = $('.hours tr[data-day="' + dayKey + '"]');
    if (row) row.classList.add("today");
    $$(".closures li").forEach(function (li) { if (li.getAttribute("data-date") < today) li.remove(); });

    var card = $("#lab-status");
    if (card) {
      var state = "closed", line1 = "Closed now", line2 = "";
      var closure = closedOn(today);
      var ranges = closure ? [] : (hours.weekly[dayKey] || []);
      for (var i = 0; i < ranges.length; i++) {
        var a = toMin(ranges[i][0]), b = toMin(ranges[i][1]);
        if (minutes >= a && minutes < b) { state = "open"; line1 = "Open now"; line2 = "Until " + fmt(ranges[i][1]) + " today"; break; }
        if (minutes < a) { line2 = "Opens at " + fmt(ranges[i][0]) + " today"; break; }
      }
      if (closure) line2 = "Closed today: " + closure.label;
      if (state === "closed" && !line2) {
        // find the next opening in the coming week
        var d = new Date(today + "T12:00:00Z");   // noon UTC: day arithmetic never crosses a date line
        for (var n = 1; n <= 7 && !line2; n++) {
          var next = new Date(d.getTime() + n * 86400000);
          var iso = next.toISOString().slice(0, 10);
          var r = closedOn(iso) ? [] : (hours.weekly[keys[next.getUTCDay()]] || []);
          if (r.length) {
            var name = n === 1 ? "tomorrow" : next.toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" });
            line2 = "Opens " + name + " at " + fmt(r[0][0]);
          }
        }
      }
      if (!hours.verified) line2 += (line2 ? " · " : "") + "hours not confirmed yet";
      card.setAttribute("data-state", state);
      $(".status-text", card).innerHTML = "<strong>" + line1 + "</strong><span>" + line2 + "</span>";
    }
  }

  /* ---------- Equipment filter ---------- */
  var filterBar = $("[data-equip-filter]");
  if (filterBar) {
    filterBar.hidden = false;
    var q = $("#equip-q"), chips = $$(".chip", filterBar), cards = $$("#equip-list > li"), empty = $("#equip-empty");
    var cat = "all";
    var apply = function () {
      var words = q.value.toLowerCase().trim().split(/\s+/).filter(Boolean), shown = 0;
      cards.forEach(function (c) {
        var hay = c.getAttribute("data-search") + " " + c.textContent.toLowerCase();
        var ok = (cat === "all" || c.getAttribute("data-category") === cat) &&
          words.every(function (w) { return hay.indexOf(w) !== -1; });
        c.hidden = !ok; if (ok) shown++;
      });
      empty.hidden = shown !== 0;
    };
    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        cat = chip.getAttribute("data-filter");
        chips.forEach(function (c) { c.setAttribute("aria-pressed", c === chip ? "true" : "false"); });
        apply();
      });
    });
    q.addEventListener("input", apply);
  }

  /* ---------- Site search ---------- */
  var dialog = $("#search-dialog"), openBtn = $(".search-open");
  if (dialog && openBtn && typeof dialog.showModal === "function") {
    openBtn.hidden = false;
    var input = $("#search-q"), list = $("#search-results"), index = null, active = -1;

    var esc = function (s) { return s.replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
    var hl = function (s, words) {
      var out = esc(s);
      words.forEach(function (w) {
        if (w.length < 2) return;
        out = out.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
      });
      return out;
    };
    var snippet = function (text, words) {
      var lower = text.toLowerCase(), at = -1;
      for (var i = 0; i < words.length && at < 0; i++) at = lower.indexOf(words[i]);
      var start = Math.max(0, at - 50);
      return (start > 0 ? "…" : "") + text.slice(start, start + 160) + (text.length > start + 160 ? "…" : "");
    };
    var render = function () {
      var words = input.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
      active = -1;
      if (!words.length) { list.innerHTML = '<li class="search-empty">Try “scope”, “gerber”, “poster”, “fuse” or “resistor”.</li>'; return; }
      var hits = index.map(function (p) {
        var title = p.title.toLowerCase(), text = p.text.toLowerCase(), score = 0;
        for (var i = 0; i < words.length; i++) {
          var w = words[i], inTitle = title.indexOf(w) !== -1, inText = text.indexOf(w) !== -1;
          if (!inTitle && !inText) return null;
          score += (inTitle ? 10 : 0) + (inText ? 1 + Math.min(5, text.split(w).length - 1) * 0.2 : 0);
        }
        return { p: p, score: score * (p.rank || 1) };
      }).filter(Boolean).sort(function (a, b) { return b.score - a.score; }).slice(0, 12);
      if (!hits.length) { list.innerHTML = '<li class="search-empty">Nothing found. <a href="' + root + 'report/">Tell us what you were looking for.</a></li>'; return; }
      list.innerHTML = hits.map(function (h) {
        return '<li><a href="' + root + h.p.url + '"><span class="r-title">' + hl(h.p.title, words) + '</span>' +
          (h.p.section ? '<span class="r-section">' + esc(h.p.section) + '</span>' : "") +
          '<span class="r-snip">' + hl(snippet(h.p.text, words), words) + '</span></a></li>';
      }).join("");
    };
    var open = function () {
      dialog.showModal(); input.focus(); input.select();
      if (!index) {
        list.innerHTML = '<li class="search-empty">Loading…</li>';
        fetch(root + "static/search-index.json").then(function (r) { return r.json(); })
          .then(function (data) { index = data; render(); })
          .catch(function () { list.innerHTML = '<li class="search-empty">Search could not load.</li>'; });
      } else { render(); }
    };
    openBtn.addEventListener("click", open);
    input.addEventListener("input", function () { if (index) render(); });
    input.addEventListener("keydown", function (e) {
      var links = $$("a", list);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!links.length) return;
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
        links.forEach(function (l, i) { l.classList.toggle("active", i === active); });
        links[active].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        e.preventDefault();
        var target = links[active >= 0 ? active : 0];
        if (target) window.location.href = target.href;
      }
    });
    dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
    document.addEventListener("keydown", function (e) {
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
      if ((e.key === "/" && !typing) || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k")) {
        e.preventDefault(); if (!dialog.open) open();
      }
    });
  }
})();
