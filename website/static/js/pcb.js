/* PCB file checker for the LPKF mill. Reads Gerber (RS-274X) and Excellon files
   in the browser and checks them against the lab's rules. Nothing is uploaded.

   What it checks, and where each rule comes from (the lab's own milling sheet):
     - one file each named with TOP / BOT / DRL / BOA, in capitals
     - copper and outline are Gerber, ideally .gbr; drill is Excellon
     - no DXF
     - board outline fits the reflow oven: 8 x 6.5 in (203 x 165 mm)
   What it cannot check: trace clearance (needs a real DRC in your CAD tool). */
(function () {
  "use strict";

  var OVEN = { long: 8 * 25.4, short: 6.5 * 25.4 };   // 8 x 6.5 in = 203.2 x 165.1 mm
  var ROLES = ["TOP", "BOT", "DRL", "BOA"];
  var EXTRA = /silk|mask|paste|legend|overlay|courtyard|assembly|fab|keepout|\.gto$|\.gbo$|\.gts$|\.gbs$|\.gtp$|\.gbp$/i;

  /* ---------- Parsers (pure; exposed as window.PcbCheck for testing) ---------- */

  function sniff(text, name) {
    var head = text.slice(0, 4000);
    if (/\.dxf$/i.test(name) || (/\bSECTION\b/.test(head) && /\bENTITIES\b|\bHEADER\b/.test(head))) return "dxf";
    if (/^\s*(;.*\n\s*)*M48\b/m.test(head) || (/^M48\s*$/m.test(head) && /^T\d+.*C[\d.]+/m.test(text))) return "excellon";
    if (/%FS[LTD]?[AI]X\d\dY\d\d/.test(head) || /%MO(MM|IN)\*%/.test(head)) return "gerber";
    if (/^T\d+C[\d.]+/m.test(head) && /^X-?\d/m.test(text)) return "excellon";
    return "unknown";
  }

  function parseGerber(text) {
    var out = { units: null, format: null, bbox: null, points: 0, apertures: [], ended: /M02\*/.test(text), incremental: false };
    var fs = text.match(/%FS([LTD]?)([AI])X(\d)(\d)Y(\d)(\d)\*%/);
    if (fs) {
      out.format = { zeros: fs[1] || "L", xi: +fs[3], xd: +fs[4], yi: +fs[5], yd: +fs[6] };
      out.incremental = fs[2] === "I";
    }
    var mo = text.match(/%MO(MM|IN)\*%/);
    if (mo) out.units = mo[1] === "MM" ? "mm" : "in";
    else if (/G71\*/.test(text)) out.units = "mm";
    else if (/G70\*/.test(text)) out.units = "in";
    if (!out.format || !out.units) return out;

    var scale = out.units === "in" ? 25.4 : 1;
    var f = out.format;
    function coord(str, intDigits, decDigits) {
      var neg = str[0] === "-", digits = str.replace(/^[-+]/, "");
      if (f.zeros === "T") { while (digits.length < intDigits + decDigits) digits += "0"; }
      var v = parseInt(digits, 10) / Math.pow(10, decDigits);
      return (neg ? -v : v) * scale;
    }

    var re = /%ADD(\d+)([A-Za-z_][\w.$]*),([\d.]+)/g, m;
    while ((m = re.exec(text))) out.apertures.push({ d: +m[1], shape: m[2], size: parseFloat(m[3]) * scale });

    // Walk the data blocks; X and Y are modal, so remember the last of each.
    var body = text.replace(/%[^%]*%/g, "");
    var blocks = body.split("*"), x = null, y = null, minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (var i = 0; i < blocks.length; i++) {
      var b = blocks[i];
      if (!/[XY]/.test(b) || /^\s*G0?4/.test(b)) continue;       // G04 is a comment
      var mx = b.match(/X([-+]?\d+)/), my = b.match(/Y([-+]?\d+)/);
      if (mx) x = coord(mx[1], f.xi, f.xd);
      if (my) y = coord(my[1], f.yi, f.yd);
      if (x === null || y === null) continue;
      out.points++;
      if (x < minX) minX = x; if (x > maxX) maxX = x;
      if (y < minY) minY = y; if (y > maxY) maxY = y;
    }
    if (out.points) out.bbox = { minX: minX, minY: minY, maxX: maxX, maxY: maxY, w: maxX - minX, h: maxY - minY };
    return out;
  }

  function parseExcellon(text) {
    var out = { units: null, tools: [], holes: 0 };
    var header = (text.split(/^%\s*$/m)[0] || text);
    if (/METRIC|M71/.test(header)) out.units = "mm";
    else if (/INCH|M72/.test(header)) out.units = "in";
    var scale = out.units === "in" ? 25.4 : 1;
    var re = /^T(\d+)(?:[FSBHZ][\d.]+)*C([\d.]+)/gm, m, seen = {};
    while ((m = re.exec(text))) {
      if (seen[m[1]]) continue;
      seen[m[1]] = true;
      out.tools.push({ t: +m[1], dia: parseFloat(m[2]) * scale });
    }
    out.holes = (text.match(/^(?:G\d+)?X[-+]?[\d.]+(?:Y[-+]?[\d.]+)?\s*$/gm) || []).length +
                (text.match(/^Y[-+]?[\d.]+\s*$/gm) || []).length;
    return out;
  }

  // Which of TOP/BOT/DRL/BOA a file name claims to be.
  function classify(name) {
    var base = name.replace(/\.[^.]+$/, "");
    if (EXTRA.test(name)) return { role: null, extra: true, roles: [], capital: true };
    // Whole words first, so "laptop_BOT" is BOT and not TOP; BOTTOM counts as BOT.
    var alias = { TOP: "TOP", BOT: "BOT", BOTTOM: "BOT", DRL: "DRL", BOA: "BOA" };
    var found = {}, capital = true;
    base.split(/[^A-Za-z0-9]+/).forEach(function (tok) {
      var r = alias[tok.toUpperCase()];
      if (r) { found[r] = true; if (tok !== tok.toUpperCase()) capital = false; }
    });
    var roles = Object.keys(found);
    if (!roles.length) {   // no separators, e.g. "boardTOP": capitals only, so "board" is not BOA
      roles = ROLES.filter(function (r) { return base.indexOf(r) !== -1; });
      capital = true;
    }
    var role = roles.length === 1 ? roles[0] : null;
    return { role: role, roles: roles, extra: false, capital: capital };
  }

  window.PcbCheck = { sniff: sniff, parseGerber: parseGerber, parseExcellon: parseExcellon, classify: classify };

  /* ---------- Page wiring ---------- */

  var drop = document.getElementById("pcb-drop");
  var input = document.getElementById("pcb-files");
  var report = document.getElementById("pcb-report");
  if (!drop || !input || !report) return;

  var current = [];
  var esc = function (s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var mm = function (v) { return (Math.round(v * 10) / 10).toFixed(1) + " mm"; };
  var inch = function (v) { return (v / 25.4).toFixed(2) + " in"; };

  function analyze(files) {
    return Promise.all(files.map(function (file) {
      if (file.size > 25e6) return Promise.resolve({ file: file, text: "", tooBig: true });
      return file.text().then(function (text) { return { file: file, text: text }; });
    })).then(function (items) {
      items.forEach(function (it) {
        it.name = it.file.name;
        it.kind = it.tooBig ? "unknown" : sniff(it.text, it.name);
        it.cls = classify(it.name);
        if (it.kind === "gerber") it.gerber = parseGerber(it.text);
        if (it.kind === "excellon") it.drill = parseExcellon(it.text);
      });
      return items;
    });
  }

  function render(items) {
    var sides = +document.querySelector('input[name="sides"]:checked').value;
    var checks = [];   // [level, html]
    var add = function (level, html) { checks.push([level, html]); };
    var byRole = {};

    items.forEach(function (it) {
      var n = "<code>" + esc(it.name) + "</code>";
      if (it.tooBig) { add("warn", n + " is over 25 MB and was skipped."); return; }
      if (it.cls.extra) { add("info", n + " looks like a silkscreen, mask or paste layer. The mill does not use it; you can leave it out."); return; }
      if (it.kind === "dxf") { add("fail", n + " is a DXF file. DXF often gets corrupted on import. Export Gerber (.gbr) instead."); }
      if (it.cls.roles.length > 1) { add("fail", n + " has more than one of TOP, BOT, DRL, BOA in its name (" + it.cls.roles.join(", ") + "). Use exactly one."); return; }
      if (!it.cls.role) {
        add("warn", n + " does not say which layer it is. Put TOP, BOT, DRL or BOA in the name, e.g. <code>logic_card_TOP.gbr</code>.");
        return;
      }
      if (!it.cls.capital) add("warn", n + ": write <code>" + it.cls.role + "</code> in capital letters, as the lab asks.");
      (byRole[it.cls.role] = byRole[it.cls.role] || []).push(it);

      if (it.cls.role === "DRL") {
        if (it.kind === "gerber") add("fail", n + " is a Gerber file, but the drill file <strong>must be Excellon</strong>. Export the NC drill / Excellon file from your CAD tool.");
        else if (it.kind !== "excellon") add("fail", n + " is not a readable Excellon drill file.");
        else {
          if (!/\.drl$/i.test(it.name)) add("warn", n + ": the lab's example uses a <code>.drl</code> extension.");
          var d = it.drill;
          if (!d.units) add("warn", n + ": the header does not say METRIC or INCH. Hole sizes may be read wrong.");
          if (!d.tools.length) add("warn", n + ": no drill sizes found in the header.");
          else add("pass", n + ": Excellon, " + d.tools.length + " drill size" + (d.tools.length > 1 ? "s" : "") + " (" +
            d.tools.map(function (t) { return t.dia.toFixed(2); }).join(", ") + " mm), about " + d.holes + " holes.");
        }
      } else {
        if (it.kind === "excellon") add("fail", n + " is an Excellon drill file, but its name says " + it.cls.role + ".");
        else if (it.kind !== "gerber" && it.kind !== "dxf") add("fail", n + " is not a readable Gerber file.");
        else if (it.kind === "gerber") {
          var g = it.gerber;
          if (!/\.gbr$/i.test(it.name)) add("warn", n + ": Gerber files are preferred with a <code>.gbr</code> extension. Renaming the file is fine.");
          if (!g.format || !g.units) add("fail", n + ": missing the format (%FS) or units (%MO) statement, so it cannot be read reliably.");
          else if (g.incremental) add("warn", n + " uses incremental coordinates. Export absolute coordinates instead.");
          else if (!g.ended) add("warn", n + " does not end with M02. The file may be cut off.");
          else add("pass", n + ": Gerber, " + g.units + ", " + g.points + " coordinates.");
        }
      }
    });

    // required set
    var need = sides === 2 ? ["TOP", "BOT", "DRL", "BOA"] : ["DRL", "BOA"];
    need.forEach(function (r) {
      if (!byRole[r]) add("fail", "Missing the <strong>" + r + "</strong> file" + ({ TOP: " (top copper)", BOT: " (bottom copper)", DRL: " (Excellon drill)", BOA: " (board outline)" })[r] + ".");
    });
    if (sides === 1) {
      if (!byRole.TOP && !byRole.BOT) add("fail", "Missing a copper layer. A single-sided board needs a TOP or a BOT file.");
      if (byRole.TOP && byRole.BOT) add("info", "You sent both TOP and BOT but chose single-sided. Switch to double-sided if you meant two layers.");
    }
    ROLES.forEach(function (r) { if (byRole[r] && byRole[r].length > 1) add("warn", "More than one " + r + " file. Send only one per layer."); });

    // board size from the outline
    var outline = byRole.BOA && byRole.BOA[0].gerber;
    if (outline && outline.bbox) {
      var w = outline.bbox.w, h = outline.bbox.h, L = Math.max(w, h), S = Math.min(w, h);
      var size = mm(w) + " x " + mm(h) + " (" + inch(w) + " x " + inch(h) + ")";
      if (L < 1 || S < 1) add("warn", "The outline is only " + size + ". Check that it really is the board edge.");
      else if (L <= OVEN.long && S <= OVEN.short) add("pass", "Board size " + size + " fits the reflow oven (max 203 x 165 mm).");
      else add("warn", "Board size " + size + " is larger than the reflow oven takes (8 x 6.5 in, 203 x 165 mm). Ask a technician before you go further.");

      ["TOP", "BOT"].forEach(function (r) {
        var cu = byRole[r] && byRole[r][0].gerber;
        if (!cu || !cu.bbox) return;
        var tol = 0.5;
        if (cu.bbox.minX < outline.bbox.minX - tol || cu.bbox.maxX > outline.bbox.maxX + tol ||
            cu.bbox.minY < outline.bbox.minY - tol || cu.bbox.maxY > outline.bbox.maxY + tol) {
          add("warn", "Some " + r + " copper lies outside the board outline. Check the layers line up and use the same units and origin.");
        }
      });
    }

    var fails = checks.filter(function (c) { return c[0] === "fail"; }).length;
    var warns = checks.filter(function (c) { return c[0] === "warn"; }).length;
    var summary = fails ? "<strong>" + fails + " problem" + (fails > 1 ? "s" : "") + " to fix</strong> before you send these files."
      : warns ? "<strong>No blocking problems.</strong> Look at the " + warns + " warning" + (warns > 1 ? "s" : "") + " below."
      : "<strong>These files pass every check.</strong> Send them to a lab technician.";

    report.innerHTML =
      '<div class="calc-result" style="margin-top:16px">' + summary + "</div>" +
      '<ul class="checks">' + checks.sort(function (a, b) {
        var o = { fail: 0, warn: 1, pass: 2, info: 3 }; return o[a[0]] - o[b[0]];
      }).map(function (c) { return '<li class="' + c[0] + '"><span class="sr-only">' + c[0] + ": </span>" + c[1] + "</li>"; }).join("") + "</ul>" +
      '<p class="note">Still check trace clearance (at least 0.5 mm) with your CAD tool\'s design rule check. This page cannot measure it.</p>';
  }

  function handle(fileList) {
    current = Array.prototype.slice.call(fileList);
    if (!current.length) return;
    if (current.some(function (f) { return /\.zip$/i.test(f.name); })) {
      report.innerHTML = '<div class="calc-result" style="margin-top:16px">Unzip the .zip first, then drop the files inside it.</div>';
      return;
    }
    report.innerHTML = '<p class="note">Reading ' + current.length + " files…</p>";
    analyze(current).then(function (items) { current.items = items; render(items); });
  }

  input.addEventListener("change", function () { handle(input.files); });
  ["dragenter", "dragover"].forEach(function (t) {
    drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.add("over"); });
  });
  ["dragleave", "drop"].forEach(function (t) {
    drop.addEventListener(t, function (e) { e.preventDefault(); drop.classList.remove("over"); });
  });
  drop.addEventListener("drop", function (e) { handle(e.dataTransfer.files); });
  document.querySelectorAll('input[name="sides"]').forEach(function (r) {
    r.addEventListener("change", function () { if (current.items) render(current.items); });
  });
})();
