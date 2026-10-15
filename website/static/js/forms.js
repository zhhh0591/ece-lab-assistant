/* Report and poster forms. There is no server: each form builds an email and
   opens it in the visitor's own mail app, so nothing is stored or sent by this site. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var val = function (id) { var el = $(id); return el ? el.value.trim() : ""; };

  function mailto(to, subject, body) {
    return "mailto:" + to + "?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
  }

  /* ---------- Report a problem ---------- */
  var report = $("report-form");
  if (report) {
    var equip = $("rf-equipment");
    var preset = new URLSearchParams(window.location.search).get("equipment");
    if (preset && equip.querySelector('option[value="' + preset.replace(/"/g, "") + '"]')) {
      equip.value = preset;
      if (preset === "3d-printer") report.querySelector('input[value="3D printer"]').checked = true;
    }

    var compose = function () {
      var kind = report.querySelector('input[name="kind"]:checked').value;
      var thing = equip.value ? equip.options[equip.selectedIndex].text : "";
      var bench = val("rf-bench");
      var subject = "[Capstone Lab] " + kind + (thing ? ": " + thing : "") + (bench ? " (" + bench + ")" : "");
      var lines = [
        "Type: " + kind,
        thing ? "Equipment: " + thing : null,
        bench ? "Bench or machine: " + bench : null,
        "",
        "What happened:",
        val("rf-what"),
        "",
        val("rf-name") ? "From: " + val("rf-name") : null,
        "Sent from the lab website report form, " + new Date().toLocaleString("en-US")
      ].filter(function (l) { return l !== null; });
      return { subject: subject, body: lines.join("\n") };
    };

    report.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!report.reportValidity()) return;
      var m = compose();
      window.location.href = mailto(report.getAttribute("data-to"), m.subject, m.body);
    });

    var copyBtn = $("rf-copy");
    copyBtn.addEventListener("click", function () {
      if (!$("rf-what").reportValidity()) return;
      var m = compose();
      window.LabSite.copy(m.subject + "\n\n" + m.body, copyBtn);
    });
  }

  /* ---------- Poster printing ---------- */
  var poster = $("poster-form");
  if (poster) {
    poster.addEventListener("submit", function (e) {
      e.preventDefault();
      if (!poster.reportValidity()) return;
      var unit = val("pf-unit"), w = val("pf-w"), h = val("pf-h");
      var size = w + " x " + h + " " + unit;
      var subject = "Capstone poster print: " + val("pf-title") + " (" + size + ")";
      var body = [
        "Hello,",
        "",
        "Please print our capstone trifold poster. The PDF is attached and is the final version.",
        "",
        "Project / team: " + val("pf-title"),
        "Dimensions: " + size + " (width x height)",
        val("pf-notes") ? "Notes: " + val("pf-notes") : null,
        "",
        "Thank you,",
        val("pf-name") || ""
      ].filter(function (l) { return l !== null; }).join("\n");
      window.location.href = mailto(poster.getAttribute("data-to"), subject, body);
    });
  }
})();
