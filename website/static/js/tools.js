/* Bench calculators. Pure functions at the top, page wiring below. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };

  /* ---------- SI parsing and formatting ---------- */

  var PREFIX = { p: -12, n: -9, u: -6, "µ": -6, m: -3, "": 0, k: 3, K: 3, M: 6, G: 9 };

  // "4.7k" -> 4700, "4k7" -> 4700, "10u" -> 1e-5, "2.2 MΩ" -> 2.2e6. Returns NaN if it cannot parse.
  function parseSI(s) {
    if (s == null) return NaN;
    s = String(s).trim().replace(/[ΩΩVAFHz\s]|ohms?$/gi, "");
    if (!s) return NaN;
    var rkm = s.match(/^(\d+)([pnuµmkKMGR])(\d+)$/);          // 4k7 style
    if (rkm) s = rkm[1] + "." + rkm[3] + (rkm[2] === "R" ? "" : rkm[2]);
    var m = s.match(/^([-+]?\d*\.?\d+(?:e[-+]?\d+)?)([pnuµmkKMG]?)$/i);
    if (!m) return NaN;
    var p = m[2];
    if (p === "K") p = "k";
    if (!(p in PREFIX)) return NaN;
    return parseFloat(m[1]) * Math.pow(10, PREFIX[p]);
  }

  function fmtSI(x, unit, digits) {
    if (!isFinite(x)) return "–";
    digits = digits || 3;
    if (x === 0) return "0 " + unit;
    var steps = [[1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"]];
    var a = Math.abs(x);
    for (var i = 0; i < steps.length; i++) {
      if (a >= steps[i][0] * 0.9995 || i === steps.length - 1) {
        var v = x / steps[i][0];
        return parseFloat(v.toPrecision(digits)) + " " + steps[i][1] + unit;
      }
    }
  }

  /* ---------- E-series ---------- */

  var E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2];
  var E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1];
  var E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58,
    1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55, 2.61,
    2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12, 4.22, 4.32,
    4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65, 6.81, 6.98, 7.15,
    7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76];

  // mode: "nearest" | "up" (smallest standard value >= x) | "down"
  function standard(x, series, mode) {
    if (!(x > 0)) return NaN;
    var dec = Math.floor(Math.log10(x)), best = NaN, bestErr = Infinity;
    for (var d = dec - 1; d <= dec + 1; d++) {
      for (var i = 0; i < series.length; i++) {
        var v = +(series[i] * Math.pow(10, d)).toPrecision(3);
        if (mode === "up" && v < x * (1 - 1e-9)) continue;
        if (mode === "down" && v > x * (1 + 1e-9)) continue;
        var err = Math.abs(Math.log(v / x));
        if (err < bestErr) { bestErr = err; best = v; }
      }
    }
    return best;
  }
  var pct = function (got, want) { return ((got - want) / want * 100).toFixed(1).replace("-0.0", "0.0") + "%"; };

  /* ---------- Resistor color code ---------- */

  var COLORS = [
    { name: "Black", hex: "#000000", digit: 0, mult: 1 },
    { name: "Brown", hex: "#7B3F00", digit: 1, mult: 10, tol: 1 },
    { name: "Red", hex: "#D41B2C", digit: 2, mult: 100, tol: 2 },
    { name: "Orange", hex: "#F57C00", digit: 3, mult: 1e3 },
    { name: "Yellow", hex: "#FFD600", digit: 4, mult: 1e4 },
    { name: "Green", hex: "#2E7D32", digit: 5, mult: 1e5, tol: 0.5 },
    { name: "Blue", hex: "#1565C0", digit: 6, mult: 1e6, tol: 0.25 },
    { name: "Violet", hex: "#7B1FA2", digit: 7, mult: 1e7, tol: 0.1 },
    { name: "Grey", hex: "#808080", digit: 8, mult: 1e8, tol: 0.05 },
    { name: "White", hex: "#FFFFFF", digit: 9, mult: 1e9 },
    { name: "Gold", hex: "#C8A13A", mult: 0.1, tol: 5 },
    { name: "Silver", hex: "#C0C0C0", mult: 0.01, tol: 10 }
  ];
  var byName = {};
  COLORS.forEach(function (c) { byName[c.name] = c; });

  function bandSpec(n) {
    var digits = COLORS.filter(function (c) { return c.digit !== undefined; });
    var mults = COLORS.filter(function (c) { return c.mult !== undefined; });
    var tols = COLORS.filter(function (c) { return c.tol !== undefined; });
    var spec = [];
    for (var i = 0; i < n - 2; i++) spec.push({ label: "Digit " + (i + 1), options: digits, def: ["Yellow", "Violet", "Black"][i] });
    spec.push({ label: "Multiplier", options: mults, def: n === 4 ? "Red" : "Brown" });
    spec.push({ label: "Tolerance", options: tols, def: "Gold" });
    return spec;
  }

  function setupResistor() {
    var selects = $("rc-selects"), preview = $("rc-preview"), out = $("rc-out");
    if (!selects) return;
    var n = 4;
    function build() {
      selects.innerHTML = "";
      bandSpec(n).forEach(function (b, i) {
        var id = "rc-band-" + i;
        var wrap = document.createElement("div"); wrap.className = "field";
        wrap.innerHTML = '<label for="' + id + '">' + b.label + "</label>";
        var sel = document.createElement("select"); sel.id = id;
        b.options.forEach(function (c) {
          var o = document.createElement("option"); o.value = c.name;
          o.textContent = c.name + (i < n - 2 ? " (" + c.digit + ")" : i === n - 2 ? " (×" + fmtSI(c.mult, "", 3).trim() + ")" : " (±" + c.tol + "%)");
          if (c.name === b.def) o.selected = true;
          sel.appendChild(o);
        });
        sel.addEventListener("change", calc);
        wrap.appendChild(sel); selects.appendChild(wrap);
      });
      calc();
    }
    function calc() {
      var vals = Array.prototype.map.call(selects.querySelectorAll("select"), function (s) { return byName[s.value]; });
      var digits = 0;
      for (var i = 0; i < n - 2; i++) digits = digits * 10 + vals[i].digit;
      var r = digits * vals[n - 2].mult, tol = vals[n - 1].tol;
      out.innerHTML = "<strong>" + fmtSI(r, "Ω", 4) + "</strong> ±" + tol + "%<br><span class=\"hint\">Between " +
        fmtSI(r * (1 - tol / 100), "Ω", 4) + " and " + fmtSI(r * (1 + tol / 100), "Ω", 4) + "</span>";
      preview.innerHTML = vals.map(function (c, i) {
        return (i === n - 1 ? '<span class="band-gap"></span>' : "") + '<span class="band" style="background:' + c.hex + '"></span>';
      }).join("");
    }
    document.querySelectorAll('input[name="rc-bands"]').forEach(function (r) {
      r.addEventListener("change", function () { n = +r.value; build(); });
    });
    build();

    var rev = $("rc-value"), revOut = $("rc-rev");
    function reverse() {
      var x = parseSI(rev.value);
      if (!rev.value.trim()) { revOut.textContent = ""; return; }
      if (!(x >= 0.1)) { revOut.textContent = "Enter a resistance of 0.1 Ω or more, like 220, 4.7k or 1M."; return; }
      var lines = [];
      [[2, "4-band"], [3, "5-band"]].forEach(function (cfg) {
        var sig = cfg[0], exp = Math.floor(Math.log10(x)) - (sig - 1);
        var digits = Math.round(x / Math.pow(10, exp));
        if (digits >= Math.pow(10, sig)) { digits /= 10; exp += 1; }
        var mult = COLORS.filter(function (c) { return Math.abs(Math.log10(c.mult) - exp) < 1e-9; })[0];
        if (!mult) return;
        var ds = String(digits).split("").map(function (d) { return COLORS[+d].name; });
        var exact = digits * Math.pow(10, exp);
        lines.push("<strong>" + cfg[1] + ":</strong> " + ds.concat(mult.name).join(", ") + ", then tolerance" +
          (Math.abs(exact - x) / x > 1e-6 ? ' <span class="hint">(nearest: ' + fmtSI(exact, "Ω", 4) + ")</span>" : ""));
      });
      revOut.innerHTML = lines.join("<br>");
    }
    rev.addEventListener("input", reverse);
  }

  /* ---------- Ohm's law ---------- */

  function setupOhm() {
    var v = $("ohm-v"), i = $("ohm-i"), r = $("ohm-r"), out = $("ohm-out");
    if (!v) return;
    function calc() {
      var V = parseSI(v.value), I = parseSI(i.value), R = parseSI(r.value);
      var have = [isFinite(V), isFinite(I), isFinite(R)].filter(Boolean).length;
      if (have < 2) { out.innerHTML = '<span class="hint">Enter two of the three values.</span>'; return; }
      if (have === 3) { out.innerHTML = '<span class="hint">Clear one box so the calculator knows which value to work out.</span>'; return; }
      if (!isFinite(V)) V = I * R;
      else if (!isFinite(I)) I = V / R;
      else R = V / I;
      out.innerHTML = "<strong>" + fmtSI(V, "V") + "</strong> · <strong>" + fmtSI(I, "A") + "</strong> · <strong>" + fmtSI(R, "Ω") +
        "</strong><br>Power: <strong>" + fmtSI(V * I, "W") + "</strong>" +
        (V * I > 0.25 ? ' <span class="hint">More than a standard ¼ W resistor can take.</span>' : "");
    }
    [v, i, r].forEach(function (el) { el.addEventListener("input", calc); });
    calc();
  }

  /* ---------- Voltage divider ---------- */

  function setupDivider() {
    var vin = $("dv-vin"), r1 = $("dv-r1"), r2 = $("dv-r2"), out = $("dv-out"), tgt = $("dv-target"), sug = $("dv-suggest");
    if (!vin) return;
    function calc() {
      var Vin = parseSI(vin.value), R1 = parseSI(r1.value), R2 = parseSI(r2.value);
      if (!(isFinite(Vin) && R1 > 0 && R2 > 0)) { out.innerHTML = '<span class="hint">Enter V<sub>in</sub>, R1 and R2.</span>'; }
      else {
        var Vout = Vin * R2 / (R1 + R2), I = Vin / (R1 + R2);
        out.innerHTML = "V<sub>out</sub> = <strong>" + fmtSI(Vout, "V") + "</strong><br>Divider current: " + fmtSI(I, "A") +
          " · Thevenin resistance: " + fmtSI(R1 * R2 / (R1 + R2), "Ω");
      }
      var T = parseSI(tgt.value);
      if (!tgt.value.trim()) { sug.textContent = ""; return; }
      if (!(T > 0 && T < Vin && R1 > 0)) { sug.innerHTML = '<span class="hint">The target must be between 0 and V<sub>in</sub>.</span>'; return; }
      var ideal = R1 * T / (Vin - T);
      sug.innerHTML = "Ideal R2 = " + fmtSI(ideal, "Ω") + ["E12", "E24"].map(function (name) {
        var s = standard(ideal, name === "E12" ? E12 : E24, "nearest");
        return "<br>" + name + ": <strong>" + fmtSI(s, "Ω") + "</strong> gives " + fmtSI(Vin * s / (R1 + s), "V");
      }).join("");
    }
    [vin, r1, r2, tgt].forEach(function (el) { el.addEventListener("input", calc); });
    calc();
  }

  /* ---------- LED resistor ---------- */

  function setupLed() {
    var vs = $("led-vs"), vf = $("led-vf"), iF = $("led-if"), out = $("led-out");
    if (!vs) return;
    function calc() {
      var Vs = parseSI(vs.value), Vf = parseSI(vf.value), I = parseSI(iF.value);
      if (!(isFinite(Vs) && isFinite(Vf) && I > 0)) { out.innerHTML = '<span class="hint">Enter the supply, forward voltage and current.</span>'; return; }
      if (Vs <= Vf) { out.innerHTML = "The supply must be higher than the LED's forward voltage."; return; }
      var R = (Vs - Vf) / I, s = standard(R, E12, "up"), s24 = standard(R, E24, "up");
      var Ireal = (Vs - Vf) / s, P = Ireal * Ireal * s;
      out.innerHTML = "Exact: " + fmtSI(R, "Ω") + "<br>Use <strong>" + fmtSI(s, "Ω") + "</strong> (E12, next value up) → " + fmtSI(Ireal, "A") +
        (s24 !== s ? " · or " + fmtSI(s24, "Ω") + " (E24)" : "") +
        "<br>Resistor power: " + fmtSI(P, "W") + (P > 0.125 ? ' <span class="hint">Use at least a ' + (P > 0.25 ? "½" : "¼") + " W resistor.</span>" : "");
    }
    [vs, vf, iF].forEach(function (el) { el.addEventListener("input", calc); });
    calc();
  }

  /* ---------- RC ---------- */

  function setupRC() {
    var r = $("rcf-r"), c = $("rcf-c"), out = $("rcf-out");
    if (!r) return;
    function calc() {
      var R = parseSI(r.value), C = parseSI(c.value);
      if (!(R > 0 && C > 0)) { out.innerHTML = '<span class="hint">Enter R and C, like 1k and 100n.</span>'; return; }
      var tau = R * C;
      out.innerHTML = "Cutoff f<sub>c</sub> = 1 / (2πRC) = <strong>" + fmtSI(1 / (2 * Math.PI * tau), "Hz") + "</strong>" +
        "<br>Time constant τ = RC = <strong>" + fmtSI(tau, "s") + "</strong>" +
        '<br><span class="hint">A step response reaches 63% after τ and 99% after 5τ (' + fmtSI(5 * tau, "s") + ").</span>";
    }
    [r, c].forEach(function (el) { el.addEventListener("input", calc); });
    calc();
  }

  /* ---------- Standard values ---------- */

  function setupESeries() {
    var inp = $("es-value"), out = $("es-out");
    if (!inp) return;
    function calc() {
      var x = parseSI(inp.value);
      if (!(x > 0)) { out.innerHTML = '<span class="hint">Enter a resistance, like 3.9k.</span>'; return; }
      out.innerHTML = [["E12", E12], ["E24", E24], ["E96", E96]].map(function (s) {
        var v = standard(x, s[1], "nearest");
        return s[0] + ": <strong>" + fmtSI(v, "Ω") + "</strong> <span class=\"hint\">(" + pct(v, x) + ")</span>";
      }).join("<br>");
    }
    inp.addEventListener("input", calc);
    calc();
  }

  setupResistor(); setupOhm(); setupDivider(); setupLed(); setupRC(); setupESeries();

  // exposed for the self-test in the browser console: LabTools.parseSI("4k7")
  window.LabTools = { parseSI: parseSI, fmtSI: fmtSI, standard: standard, E12: E12, E24: E24, E96: E96 };
})();
