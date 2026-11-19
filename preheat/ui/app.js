"use strict";

const $ = (id) => document.getElementById(id);
const weather = $("weather");
const ceiling = $("ceiling");
const houseButtons = [...document.querySelectorAll("[data-envelope]")];
const houses = { current: "Current insulation", insulated: "Better insulation" };
const format = (value, places = 2) => (Math.round(value * 10 ** places) / 10 ** places || 0).toFixed(places);
const euros = (value) => "€" + format(value);
const degrees = (value) => format(value, 1) + " °C";
const time = (hour) => String(hour).padStart(2, "0") + ":00";
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const scenario = () => ({ ceiling: Number(ceiling.value), case: weather.value });

const icons = {
  bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M13 3 5 14h6l-1 7 8-11h-6z"/></svg>',
  euro: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6.5A7 7 0 1 0 18 17.5M4 10h9M4 14h9"/></svg>',
  thermo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14.5V5a2 2 0 1 1 4 0v9.5a4 4 0 1 1-4 0z"/></svg>',
};

function headline(value) {
  const node = document.createElement("strong");
  node.className = "headline";
  const [from, to] = value.split(" → ");
  if (to === undefined) {
    node.textContent = value;
    return node;
  }
  const parts = /^(\S+) (.+)$/.exec(to);
  node.append(element("span", "from", from), element("span", "arrow", "→"),
    element("span", "", parts ? parts[1] : to));
  if (parts) node.append(element("span", "unit", parts[2]));
  return node;
}

let data;
let house = "current";
let defaultCeiling = Number(ceiling.value);
let revision = 0;
let updateTimer;
let scenarioRequest;
async function api(url, payload, signal) {
  const options = payload === undefined ? { signal } : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload), signal,
  };
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Could not complete the request.");
  return body;
}

function updateScenarioLabels() {
  const cap = Number(ceiling.value);
  $("ceiling-value").textContent = degrees(cap);
  ceiling.setAttribute("aria-valuetext", degrees(cap));
  const position = (cap - Number(ceiling.min)) / (Number(ceiling.max) - Number(ceiling.min));
  ceiling.parentElement.style.setProperty("--thumb", position * 100 + "%");
  if (proposedCeiling !== null) $("proposal-from").textContent = degrees(cap);
  $("chat-context").textContent = weather.selectedOptions[0].text + " · " + degrees(cap) + " · " + houses[house];
}

function refresh(delay = 0) {
  updateScenarioLabels();
  $("insight").textContent = "Updating scenario…";
  $("metrics").setAttribute("aria-busy", "true");
  clearTimeout(updateTimer);
  scenarioRequest?.abort();
  const expected = ++revision;
  const previous = previousForHighlight;
  previousForHighlight = null;
  changedHours = [];
  updateTimer = setTimeout(async () => {
    scenarioRequest = new AbortController();
    try {
      const next = await api("/api/scenario", scenario(), scenarioRequest.signal);
      if (expected !== revision) return;
      data = next;
      const updated = data.envelopes[house].optimised;
      if (previous?.house === house && updated) {
        changedHours = updated.power.flatMap((value, hour) =>
          Math.abs(value - previous.state.power[hour]) > 1e-6
          || Math.abs(updated.temperature[hour + 1] - previous.state.temperature[hour + 1]) > 1e-6 ? [hour] : []);
      }
    } catch (error) {
      if (expected !== revision) return;
      data = null;
      $("insight").textContent = error.message;
    }
    $("metrics").setAttribute("aria-busy", "false");
    renderMetrics();
    renderCharts();
    if (changedHours.length) $("preheat-note").textContent += " · Changed hours highlighted";
  }, delay);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

function renderMetrics() {
  const current = data?.envelopes.current;
  const insulated = data?.envelopes.insulated;
  const delta = $("result-status");
  if (current?.status === "ok" && insulated?.status === "ok" && current.optimised.cost_eur > 0) {
    const percent = 100 * (insulated.optimised.cost_eur / current.optimised.cost_eur - 1);
    delta.textContent = "Better insulation: " + signed(percent, 0) + "% preheated daily cost";
    delta.className = percent < 0 ? "delta" : "delta neutral";
  } else {
    delta.textContent = "";
    delta.className = "";
  }
  const maxEvening = Math.max(0, ...Object.values(data?.envelopes ?? {}).flatMap(pair =>
    pair?.status === "ok" ? [pair.baseline.evening_kwh, pair.optimised.evening_kwh] : []));
  const cards = Object.entries(houses).map(([id, name]) => {
    const card = element("article", "metric" + (id === house ? " is-selected" : ""), "");
    card.append(element("h3", "", name));
    const pair = data?.envelopes[id];
    if (pair?.status !== "ok") {
      card.append(element("p", "", pair?.reason || "Results unavailable."));
      return card;
    }
    const ring = element("div", "ring", "");
    ring.style.setProperty("--pct", String(clamp(pair.avoided_pct ?? 0, 0, 100)));
    ring.append(element("b", "", pair.avoided_pct === null ? "—" : format(pair.avoided_pct, 0) + "%"),
      element("span", "", "less peak use"));
    const rows = element("div", "metric-rows", "");
    for (const [key, label] of [["baseline", "Baseline"], ["optimised", "Preheated"]]) {
      const row = element("div", "metric-row" + (key === "optimised" ? " is-preheated" : "")
        + (id === house && key === "optimised" ? " selected" : ""), "");
      const state = pair[key];
      const cost = element("span", "", "Daily cost");
      const evening = element("span", "", "Evening use");
      cost.append(element("b", "", euros(state.cost_eur)));
      evening.append(element("b", "", format(state.evening_kwh) + " kWh"));
      const bar = element("i", "bar", "");
      bar.style.setProperty("--w", String(maxEvening ? 100 * state.evening_kwh / maxEvening : 0));
      evening.append(bar);
      row.append(element("strong", "", label), cost, evening);
      rows.append(row);
    }
    card.append(ring, rows);
    if (pair.avoided_pct !== null) {
      card.append(element("small", "", format(pair.avoided_pct, 1) + "% less evening use vs this house’s baseline"));
    }
    return card;
  });
  $("metrics").replaceChildren(...cards);
}

function signed(value, digits = 2) {
  const rounded = Number(format(value, digits));
  return (rounded < 0 ? "−" : rounded > 0 ? "+" : "") + format(Math.abs(rounded), digits);
}

function renderSummary(pair) {
  if (pair?.status !== "ok") {
    $("insight").textContent = pair?.reason || "Scenario unavailable.";
    $("kpis").replaceChildren();
    return;
  }
  const base = pair.baseline;
  const opt = pair.optimised;
  const firstAtCeiling = opt.temperature.findIndex(value => value >= data.ceiling - 1e-6);
  const maxTemperature = Math.max(...opt.temperature);
  const eveningPct = pair.avoided_pct;
  const current = data.envelopes.current.optimised;
  const insulated = data.envelopes.insulated.optimised;
  $("insight").textContent = current && insulated && insulated.cost_eur < current.cost_eur
    ? "With preheating, better insulation lowers daily cost from " + euros(current.cost_eur)
      + " to " + euros(insulated.cost_eur) + " and evening use from " + format(current.evening_kwh)
      + " to " + format(insulated.evening_kwh) + " kWh."
    : houses[house] + " with preheating uses " + format(opt.evening_kwh)
      + " kWh during peak hours and costs " + euros(opt.cost_eur) + " for the day.";
  const rows = [
    ["Evening peak use", format(base.evening_kwh) + " → " + format(opt.evening_kwh) + " kWh",
      eveningPct === null ? "17:00–22:00" : signed(-eveningPct, 1) + "% vs baseline · 17:00–22:00", eveningPct > 0, "violet", "bolt"],
    ["Daily cost", euros(base.cost_eur) + " → " + euros(opt.cost_eur),
      euros(pair.saving_eur) + " saved vs baseline", pair.saving_eur > 0, "teal", "euro"],
    ["Comfort", firstAtCeiling >= 0 ? time(firstAtCeiling) : degrees(maxTemperature),
      firstAtCeiling >= 0 ? "Reached the " + degrees(data.ceiling) + " ceiling" : "Peak indoor temperature · ceiling not reached", false, "amber", "thermo"],
  ];
  $("kpis").replaceChildren(...rows.map(([label, value, detail, saving, tone, icon]) => {
    const card = element("article", "kpi kpi-" + tone, "");
    const top = element("div", "kpi-top", "");
    const chip = element("span", "kpi-icon", "");
    chip.setAttribute("aria-hidden", "true");
    chip.innerHTML = icons[icon];
    top.append(chip, element("h3", "", label));
    card.append(top, headline(value), element("small", saving ? "saving" : "", detail));
    return card;
  }));
}

const plots = [
  { kind: "power", canvas: $("power-chart") },
  { kind: "temperature", canvas: $("temperature-chart") },
];
const plotPadding = { left: 38, right: 92, top: 34, bottom: 28 };
const baselineColor = "#7A869C";
const accentColor = "#3F55D3";
let activeHour = null;
let touched = false;
let previousForHighlight;
let changedHours = [];

function renderCharts() {
  const pair = data?.envelopes[house];
  renderSummary(pair);
  $("charts").hidden = pair?.status !== "ok";
  $("chart-error").hidden = pair?.status === "ok";
  $("chart-error").textContent = pair?.reason || "Schedule unavailable.";
  $("hour-data").closest("details").hidden = pair?.status !== "ok";
  if (pair?.status !== "ok") return;
  const rows = pair.baseline.temperature.map((value, hour) => {
    const row = document.createElement("tr");
    const label = element("th", "", time(hour));
    label.scope = "row";
    row.append(label);
    for (const item of [pair.baseline.power[hour], pair.optimised.power[hour], value, pair.optimised.temperature[hour]]) {
      row.append(element("td", "", item === undefined ? "—" : format(item)));
    }
    return row;
  });
  $("hour-data").replaceChildren(...rows);
  const preheatHours = pair.optimised.power.flatMap((value, hour) =>
    hour < data.evening[0] && value > pair.baseline.power[hour] + 1e-6 ? [hour] : []);
  $("preheat-note").textContent = preheatHours.length
    ? "Preheat " + hourRanges(preheatHours).map(([start, end]) => time(start) + "–" + time(end)).join(", ")
    : "";
  drawCharts();
}

function hourRanges(hours) {
  const ranges = [];
  for (const hour of hours) {
    const last = ranges.at(-1);
    if (last && last[1] === hour) last[1] += 1;
    else ranges.push([hour, hour + 1]);
  }
  return ranges;
}

function drawCharts() {
  const pair = data?.envelopes[house];
  if (pair?.status !== "ok") return;
  for (const plot of plots) drawPlot(plot, pair);
  const tooltip = $("chart-tooltip");
  tooltip.hidden = activeHour === null;
  if (activeHour === null) return;
  const hour = activeHour;
  const rows = [element("strong", "", hour === 24 ? "24:00 · closing temperature" : time(hour) + "–" + time(hour + 1))];
  for (const [key, title, unit] of [["power", "Power", " kW"], ["temperature", "Indoor", " °C"]]) {
    const base = pair.baseline[key][hour];
    const opt = pair.optimised[key][hour];
    if (base === undefined) continue;
    rows.push(element("span", "", title + ": " + format(base, 2) + " → " + format(opt, 2) + unit
      + " (" + signed(opt - base, 2) + unit + ")"));
  }
  rows.push(element("span", "tooltip-key", "Baseline → preheated (change)"));
  tooltip.replaceChildren(...rows);
  tooltip.classList.toggle("at-left", hour >= 14);
}

const chartFont = "-apple-system, BlinkMacSystemFont, Inter, system-ui, sans-serif";

// Fritsch–Carlson monotone cubic: smooth, passes through every sample, never overshoots.
function monotonePath(ctx, pts) {
  const n = pts.length;
  const dx = [];
  const slope = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1][0] - pts[i][0]);
    slope.push((pts[i + 1][1] - pts[i][1]) / dx[i]);
  }
  const m = [slope[0]];
  for (let i = 1; i < n - 1; i++) m.push(slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2);
  m.push(slope[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / slope[i];
    const b = m[i + 1] / slope[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * slope[i];
      m[i + 1] = t * b * slope[i];
    }
  }
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i];
    ctx.bezierCurveTo(pts[i][0] + h / 3, pts[i][1] + m[i] * h / 3,
      pts[i + 1][0] - h / 3, pts[i + 1][1] - m[i + 1] * h / 3, pts[i + 1][0], pts[i + 1][1]);
  }
}

function pillLabel(ctx, text, anchorX, py, fg, bg, edge, maxX) {
  ctx.save();
  ctx.font = "600 11.5px " + chartFont;
  const w = ctx.measureText(text).width + 20;
  const px = Math.max(4, Math.min(anchorX, maxX - w - 4));
  ctx.beginPath();
  ctx.roundRect(px, py, w, 22, 11);
  ctx.fillStyle = bg;
  ctx.fill();
  ctx.strokeStyle = edge;
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.fillStyle = fg;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillText(text, px + 10, py + 11.5);
  ctx.restore();
}

function marker(ctx, cx, cy, color) {
  ctx.save();
  ctx.shadowColor = "rgba(29,27,63,.35)";
  ctx.shadowBlur = 8;
  ctx.shadowOffsetY = 2;
  ctx.beginPath();
  ctx.arc(cx, cy, 5.5, 0, Math.PI * 2);
  ctx.fillStyle = "#fff";
  ctx.fill();
  ctx.shadowColor = "transparent";
  ctx.lineWidth = 2.6;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.restore();
}

function drawPlot({ kind, canvas }, pair) {
  const { width, height } = canvas.getBoundingClientRect();
  if (!width || !height) return;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);

  const { left, right, top, bottom } = plotPadding;
  const baseY = height - bottom;
  const power = kind === "power";
  const baseline = pair.baseline[kind];
  const optimised = pair.optimised[kind];
  const low = power ? 0 : Math.min(19.7, ...baseline, ...optimised) - .1;
  const high = power ? Math.max(4, ...baseline, ...optimised) + .45 : Math.max(data.ceiling, ...optimised, ...baseline) + .3;
  const x = hour => left + hour * (width - left - right) / 24;
  const y = value => baseY - (value - low) * (baseY - top) / (high - low);
  const peakStart = data.evening[0];
  const peakEnd = data.evening.at(-1) + 1;

  const lineGradient = ctx.createLinearGradient(x(0), 0, x(24), 0);
  lineGradient.addColorStop(0, "#3b4fd0");
  lineGradient.addColorStop(.55, "#4f6ae6");
  lineGradient.addColorStop(1, "#6a9bff");
  const band = (start, end, from, to) => {
    const fill = ctx.createLinearGradient(0, top, 0, baseY);
    fill.addColorStop(0, from);
    fill.addColorStop(1, to);
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.roundRect(x(start), top, x(end) - x(start), baseY - top, 10);
    ctx.fill();
  };

  // Background layers: comfort envelope, peak tariff, preheat window, changed hours, inspected hour.
  if (!power) {
    const envelope = ctx.createLinearGradient(0, top, 0, baseY);
    envelope.addColorStop(0, "rgba(63,120,200,.13)");
    envelope.addColorStop(1, "rgba(63,120,200,.05)");
    ctx.fillStyle = envelope;
    ctx.beginPath();
    ctx.moveTo(x(0), y(data.ceiling));
    ctx.lineTo(x(24), y(data.ceiling));
    for (let hour = 24; hour >= 0; hour--) ctx.lineTo(x(hour), y(data.floors[hour]));
    ctx.closePath();
    ctx.fill();
  }
  band(peakStart, peakEnd, "rgba(233,184,114,.40)", "rgba(233,184,114,.07)");
  if (power) {
    const preheat = optimised.flatMap((value, hour) =>
      hour < peakStart && value > baseline[hour] + 1e-6 ? [hour] : []);
    for (const [start, end] of hourRanges(preheat)) band(start, end, "rgba(63,85,211,.20)", "rgba(63,85,211,.03)");
  }
  for (const [start, end] of hourRanges(changedHours)) band(start, end, "rgba(24,160,140,.24)", "rgba(24,160,140,.04)");
  if (power && activeHour !== null && activeHour < 24) band(activeHour, activeHour + 1, "rgba(29,27,63,.10)", "rgba(29,27,63,.02)");

  // Grid and axes.
  ctx.font = "500 11.5px " + chartFont;
  ctx.lineWidth = 1;
  ctx.textAlign = "right";
  for (const tick of power ? [0, 1, 2, 3, 4] : [20, 21, 22, 23, 24].filter(v => v <= high)) {
    ctx.setLineDash([2, 5]);
    ctx.strokeStyle = "rgba(35,50,95,.16)";
    ctx.beginPath();
    ctx.moveTo(x(0), y(tick));
    ctx.lineTo(x(24), y(tick));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#5b6479";
    ctx.fillText(tick, left - 8, y(tick) + 4);
  }
  ctx.setLineDash([]);
  ctx.textAlign = "center";
  ctx.fillStyle = "#5b6479";
  const labelStep = width < 460 ? 6 : width < 660 ? 4 : 3;
  for (let hour = 0; hour <= 24; hour += labelStep) ctx.fillText(time(hour), x(hour), height - 6);

  // Series.
  const stepTrace = values => {
    ctx.moveTo(x(0), y(values[0]));
    values.forEach((value, hour) => {
      ctx.lineTo(x(hour), y(value));
      ctx.lineTo(x(hour + 1), y(value));
    });
  };
  const trace = values => power ? stepTrace(values) : monotonePath(ctx, values.map((value, hour) => [x(hour), y(value)]));

  if (!power) {
    ctx.beginPath();
    ctx.moveTo(x(0), y(data.ceiling));
    ctx.lineTo(x(24), y(data.ceiling));
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "rgba(71,81,105,.7)";
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.setLineDash([]);
  }
  const area = ctx.createLinearGradient(0, top, 0, baseY);
  area.addColorStop(0, power ? "rgba(63,85,211,.30)" : "rgba(63,85,211,.18)");
  area.addColorStop(1, "rgba(63,85,211,.02)");
  ctx.beginPath();
  trace(optimised);
  ctx.lineTo(x(24), baseY);
  ctx.lineTo(x(0), baseY);
  ctx.closePath();
  ctx.fillStyle = area;
  ctx.fill();

  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.beginPath();
  trace(baseline);
  ctx.strokeStyle = baselineColor;
  ctx.lineWidth = 1.8;
  ctx.setLineDash(power ? [] : [6, 5]);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.save();
  ctx.shadowColor = "rgba(63,85,211,.38)";
  ctx.shadowBlur = 12;
  ctx.shadowOffsetY = 4;
  ctx.beginPath();
  trace(optimised);
  ctx.strokeStyle = lineGradient;
  ctx.lineWidth = 2.9;
  ctx.stroke();
  ctx.restore();

  // In-chart labels.
  if (power) {
    pillLabel(ctx, "Peak " + peakStart + "–" + peakEnd + " · " + $("peak-price").textContent,
      x(peakStart), 5, "#7a4b0c", "rgba(255,255,255,.9)", "rgba(214,160,85,.8)", width);
  } else {
    pillLabel(ctx, "Ceiling " + degrees(data.ceiling), x(0), 5, "#475169", "rgba(255,255,255,.9)", "rgba(71,81,105,.3)", width);
  }
  ctx.font = "600 11.5px " + chartFont;
  ctx.textAlign = "left";
  const baseValueY = y(baseline.at(-1));
  const optValueY = y(optimised.at(-1));
  const baseLabelY = clamp(baseValueY + (Math.abs(baseValueY - optValueY) < 16 ? -8 : 3), top + 8, baseY + 3);
  const optLabelY = clamp(Math.abs(baseLabelY - optValueY) < 16 ? baseLabelY + 15 : optValueY + 3, top + 8, baseY + 8);
  for (const [label, color, valueY, labelY] of [
    ["Baseline", "#475169", baseValueY, baseLabelY],
    ["Preheated", "#3b4fd0", optValueY, optLabelY],
  ]) {
    ctx.beginPath();
    ctx.moveTo(x(24) + 2, valueY);
    ctx.lineTo(x(24) + 9, labelY - 4);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.fillText(label, x(24) + 12, labelY);
  }

  // Inspected hour: gradient guide and glowing markers.
  if (activeHour !== null && (!power || activeHour < 24)) {
    const cx = power ? x(activeHour + .5) : x(activeHour);
    const guide = ctx.createLinearGradient(0, top, 0, baseY);
    guide.addColorStop(0, "rgba(63,85,211,.85)");
    guide.addColorStop(1, "rgba(63,85,211,.1)");
    ctx.beginPath();
    ctx.moveTo(cx, top);
    ctx.lineTo(cx, baseY);
    ctx.strokeStyle = guide;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    marker(ctx, cx, y(baseline[activeHour]), baselineColor);
    marker(ctx, cx, y(optimised[activeHour]), accentColor);
  }
}

for (const { canvas, kind } of plots) {
  function inspect(event) {
    const { left, right } = plotPadding;
    const rect = canvas.getBoundingClientRect();
    const hour = (event.clientX - rect.left - left) * 24 / (rect.width - left - right);
    activeHour = clamp(kind === "power" ? Math.floor(hour) : Math.round(hour), 0, kind === "power" ? 23 : 24);
    drawCharts();
  }
  canvas.addEventListener("pointermove", event => { if (event.pointerType === "mouse") inspect(event); });
  canvas.addEventListener("pointerdown", event => {
    touched = event.pointerType !== "mouse";
    inspect(event);
  });
  new ResizeObserver(drawCharts).observe(canvas);
}
const chartGroup = $("charts");
chartGroup.addEventListener("pointerleave", () => {
  if (touched) return;
  activeHour = null;
  drawCharts();
});
chartGroup.addEventListener("blur", () => {
  activeHour = null;
  drawCharts();
});
chartGroup.addEventListener("keydown", event => {
  const moves = { ArrowLeft: -1, ArrowRight: 1, Home: -24, End: 24 };
  if (!(event.key in moves) && event.key !== "Escape") return;
  event.preventDefault();
  activeHour = event.key === "Escape" ? null
    : clamp(activeHour === null && event.key === "ArrowRight" ? 0 : (activeHour ?? 0) + moves[event.key], 0, 24);
  drawCharts();
});

function selectHouse(value) {
  house = value;
  activeHour = null;
  changedHours = [];
  for (const item of houseButtons) {
    const checked = item.dataset.envelope === house;
    item.setAttribute("aria-checked", String(checked));
    item.tabIndex = checked ? 0 : -1;
  }
  renderMetrics();
  renderCharts();
  updateScenarioLabels();
}
for (const button of houseButtons) {
  button.addEventListener("click", () => selectHouse(button.dataset.envelope));
  button.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const other = houseButtons.find(item => item !== button);
    selectHouse(other.dataset.envelope);
    other.focus();
  });
}
ceiling.addEventListener("input", () => refresh(110));
weather.addEventListener("change", () => refresh());
$("reset").addEventListener("click", () => {
  ceiling.value = defaultCeiling;
  weather.value = "nominal";
  selectHouse("current");
  refresh();
});

const settings = $("settings");
const conversation = $("conversation");
const message = $("message");
const keyInput = $("api-key");
const modelInput = $("model-id");
const defaultModel = modelInput.value;
let credentials = { key: "", model: defaultModel };
let history = [];
let proposedCeiling = null;
let chatRequest;

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

function scrollConversation() {
  conversation.scrollTo({ top: conversation.scrollHeight, behavior: reduceMotion.matches ? "auto" : "smooth" });
}

// The full text is in the DOM at once (screen readers get it immediately); each word fades in on a stagger.
function reveal(node, text) {
  let index = 0;
  for (const part of text.split(/(\s+)/)) {
    if (!part) continue;
    if (/^\s+$/.test(part)) {
      node.append(document.createTextNode(part));
      continue;
    }
    const word = element("span", "word", part);
    word.style.setProperty("--i", String(Math.min(index++, 70)));
    node.append(word);
  }
  return Math.min(index, 70);
}

function bubble(text, role = "assistant", extra = "", source = "") {
  const animated = role === "assistant" && !extra && text && !reduceMotion.matches;
  const node = element("p", ("bubble " + role + " " + extra).trim(), animated ? "" : text);
  node.dir = "auto";
  const words = animated ? reveal(node, text) : 0;
  if (source) {
    const meta = element("span", "bubble-meta", source);
    meta.style.setProperty("--d", words * 26 + 420 + "ms");
    node.append(meta);
  }
  conversation.append(node);
  scrollConversation();
  return node;
}

function thinking() {
  const node = bubble("", "assistant", "waiting");
  node.append(element("span", "sr-only", "Checking the scenario"));
  for (let dot = 0; dot < 3; dot++) {
    const mark = document.createElement("i");
    mark.setAttribute("aria-hidden", "true");
    node.append(mark);
  }
  return node;
}

function showComparison(comparison, source = "") {
  const card = bubble("", "assistant", "answer-card");
  card.append(element("strong", "", comparison.title));
  const list = document.createElement("dl");
  for (const row of comparison.rows) {
    const item = document.createElement("div");
    item.append(element("dt", "", row.label));
    const value = element("dd", "", row.value);
    value.append(element("small", "", row.detail));
    item.append(value);
    list.append(item);
  }
  card.append(list);
  if (source) card.append(element("span", "bubble-meta", source));
  card.dir = /[\u0600-\u06ff]/.test(comparison.title) ? "rtl" : "ltr";
  scrollConversation();
}

function proposal(value) {
  proposedCeiling = value;
  $("proposal").hidden = value === null;
  $("proposal-from").textContent = value === null ? "" : degrees(Number(ceiling.value));
  $("proposal-value").textContent = value === null ? "" : degrees(value);
}

function updateAssistant() {
  const state = $("assistant-state");
  state.dataset.mode = credentials.key ? "gemini" : "rules";
  state.textContent = credentials.key ? "Gemini · " + credentials.model : "Built-in rules · no AI model";
  $("mode-note").hidden = Boolean(credentials.key);
  $("send-message").disabled = Boolean(chatRequest);
  $("send-message").setAttribute("aria-busy", String(Boolean(chatRequest)));
  for (const button of document.querySelectorAll("[data-prompt]")) button.disabled = Boolean(chatRequest);
}

function clearConversation() {
  chatRequest?.abort();
  chatRequest = null;
  history = [];
  conversation.replaceChildren();
  $("assistant-panel").dataset.started = "false";
  $("chat-intro").hidden = false;
  proposal(null);
  message.value = "";
  updateAssistant();
}

function showSettings() {
  keyInput.type = "password";
  keyInput.value = credentials.key;
  modelInput.value = credentials.model;
  $("show-key").setAttribute("aria-pressed", "false");
  $("show-key").textContent = "Show";
  $("forget-key").disabled = !credentials.key;
  settings.showModal();
}

function saveSettings(key, model) {
  if (key !== credentials.key || model !== credentials.model) {
    credentials = { key, model };
    clearConversation();
  }
  settings.close();
}

function temperatureAnswer(question, pair) {
  const lower = question.toLowerCase();
  const persian = /[\u0600-\u06ff]/.test(lower);
  const romanized = /\b(dama|damaye|damay[e-]|damaaye|miyangin|miangin|dakhel|khune|khoone)\b/.test(lower);
  const temperature = /temperature|temp\b|دما|حرارت/.test(lower) || romanized;
  const typical = /typical|average|mean|usual|معمول|میانگین|متوسط|گِرم|cheghadr|chande|mamuli|mamooli|miyangin|miangin|chand/.test(lower);
  if (!temperature || !typical || /outdoor|outside|بیرون|birun|biroon/.test(lower) || pair?.status !== "ok") return null;

  // Hour-boundary samples include both midnight readings.
  const summary = values => ({
    average: values.reduce((sum, value) => sum + value, 0) / values.length,
    low: Math.min(...values),
    high: Math.max(...values),
  });
  const base = summary(pair.baseline.temperature);
  const opt = summary(pair.optimised.temperature);
  const fa = value => new Intl.NumberFormat("fa-IR", {minimumFractionDigits: 1, maximumFractionDigits: 1}).format(value);
  if (persian || romanized) {
    const name = house === "current" ? "خانه با عایق فعلی" : "خانه با عایق بهتر";
    return { text: `${name} در سناریوی فعلی، در حالت پایه میانگین دمای داخل ${fa(base.average)} درجه است و با پیش‌گرمایش به ${fa(opt.average)} درجه می‌رسد. با پیش‌گرمایش، دما از ${fa(opt.low)} تا ${fa(opt.high)} درجه تغییر می‌کند. میانگین از ۲۵ خوانش ساعتی محاسبه شده است.` };
  }
  return { text: `For ${houses[house].toLowerCase()}, average indoor temperature is ${degrees(base.average)} on the baseline schedule and ${degrees(opt.average)} with preheating. The preheated temperature ranges from ${degrees(opt.low)} to ${degrees(opt.high)}. These averages use 25 hourly readings.` };
}

async function send(text) {
  const value = text.trim();
  if (!value || chatRequest) return;
  message.value = "";
  proposal(null);
  const requestedScenario = scenario();
  $("assistant-panel").dataset.started = "true";
  $("chat-intro").hidden = true;
  message.focus();
  bubble(value, "user");
  const waiting = thinking();
  const request = new AbortController();
  chatRequest = request;
  updateAssistant();
  const messages = [...history, { role: "user", content: value }];
  try {
    const matchingData = data?.case === requestedScenario.case && data.ceiling === requestedScenario.ceiling;
    const grounded = matchingData ? temperatureAnswer(value, data.envelopes[house]) : null;
    const reply = grounded || await api("/api/interpret", { ...credentials, messages, scenario: requestedScenario }, request.signal);
    if (request !== chatRequest) return;
    waiting.remove();
    const current = scenario();
    if (current.ceiling !== requestedScenario.ceiling || current.case !== requestedScenario.case) {
      bubble("The scenario changed while I was checking. Send your question again for the updated results.");
      return;
    }
    const text = reply.text ?? ("You can try " + degrees(reply.ceiling) + " as the all-day ceiling.");
    const origin = grounded ? "Computed in your browser from this scenario’s hourly data"
      : reply.source === "gemini" ? "Gemini · " + credentials.model + " · uses this scenario’s solver data"
      : credentials.key ? "Built-in rules · " + (reply.note || "Gemini gave no usable answer")
      : "Built-in rules · numbers from the solver";
    if (reply.comparison) showComparison(reply.comparison, origin);
    else bubble(text, "assistant", "", origin);
    if (reply.ceiling !== undefined) proposal(reply.ceiling);
    history = [...messages, { role: "assistant", content: text }].slice(-12);
  } catch (error) {
    if (request !== chatRequest) return;
    waiting.remove();
    bubble(error.message, "assistant", "error");
    if (!message.value) message.value = value;
  } finally {
    if (request === chatRequest) {
      chatRequest = null;
      updateAssistant();
    }
  }
}

$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  send(message.value);
});
message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("chat-form").requestSubmit();
  }
});
for (const button of document.querySelectorAll("[data-prompt]")) {
  button.addEventListener("click", () => send(button.dataset.prompt));
}
$("apply").addEventListener("click", () => {
  if (proposedCeiling === null) return;
  const state = data?.envelopes[house]?.optimised;
  if (state) previousForHighlight = { house, state };
  ceiling.value = proposedCeiling;
  bubble("Ceiling set to " + degrees(proposedCeiling) + ". Updating the charts.");
  proposal(null);
  message.focus();
  refresh();
});
$("cancel").addEventListener("click", () => {
  proposal(null);
  bubble("Proposal dismissed.");
  message.focus();
});
$("clear-chat").addEventListener("click", () => {
  clearConversation();
  message.focus();
});
$("settings-open").addEventListener("click", showSettings);
$("connect-gemini").addEventListener("click", showSettings);
$("about-open").addEventListener("click", () => $("about").showModal());
for (const button of document.querySelectorAll("[data-close]")) {
  button.addEventListener("click", () => button.closest("dialog").close());
}
settings.addEventListener("close", () => { keyInput.value = ""; });
$("settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  saveSettings(keyInput.value.trim(), modelInput.value.trim());
});
$("forget-key").addEventListener("click", () => saveSettings("", defaultModel));
$("show-key").addEventListener("click", () => {
  const showing = keyInput.type === "password";
  keyInput.type = showing ? "text" : "password";
  $("show-key").setAttribute("aria-pressed", String(showing));
  $("show-key").textContent = showing ? "Hide" : "Show";
});

const drawerMode = window.matchMedia("(max-width: 1099px)");
const chatPanel = $("assistant-panel");
const chatToggle = $("chat-toggle");
const dashboard = $("dashboard");
const backdrop = $("drawer-backdrop");
let chatOpen = !drawerMode.matches;

function setChat(open, moveFocus = false) {
  chatOpen = open;
  const modal = open && drawerMode.matches;
  document.body.classList.toggle("chat-open", open);
  chatPanel.hidden = !open;
  chatToggle.setAttribute("aria-expanded", String(open));
  backdrop.hidden = !modal;
  dashboard.inert = modal;
  if (modal) {
    chatPanel.setAttribute("role", "dialog");
    chatPanel.setAttribute("aria-modal", "true");
  } else {
    chatPanel.removeAttribute("role");
    chatPanel.removeAttribute("aria-modal");
  }
  if (moveFocus) (open ? $("close-chat") : chatToggle).focus();
}
chatToggle.addEventListener("click", () => setChat(!chatOpen, true));
$("close-chat").addEventListener("click", () => setChat(false, true));
backdrop.addEventListener("click", () => setChat(false, true));
drawerMode.addEventListener("change", () => setChat(!drawerMode.matches));
chatPanel.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    event.preventDefault();
    setChat(false, true);
    return;
  }
  if (!drawerMode.matches || event.key !== "Tab") return;
  const focusable = [...chatPanel.querySelectorAll("button:not(:disabled), textarea")]
    .filter(item => item.getClientRects().length);
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});
setChat(chatOpen);

clearConversation();
api("/api/config").then((config) => {
  for (const [id, label] of Object.entries(config.cases)) {
    if (id !== "nominal") weather.add(new Option(label, id));
  }
  defaultCeiling = config.ceiling;
  $("normal-price").textContent = euros(config.prices[0]) + "/kWh";
  $("peak-price").textContent = euros(config.prices[1]) + "/kWh";
  drawCharts();
}).catch(() => {
  // The nominal scenario remains available if the optional scenario list fails.
});
refresh();
