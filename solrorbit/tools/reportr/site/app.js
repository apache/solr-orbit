/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

"use strict";

/* Line colours from Solr's palette, then colour-blind-safe additions. */
const PALETTE = ["#D9411E", "#305CB3", "#2F8F4E", "#8C5BA8", "#FF833D",
                 "#0072B2", "#8C564B", "#B8340E", "#56B4E9", "#CC79A7"];

const METRIC_LABELS = {
  "throughput.mean": "Throughput (mean)",
  "throughput.median": "Throughput (median)",
  "throughput.min": "Throughput (min)",
  "throughput.max": "Throughput (max)",
  "service_time.mean": "Service time (mean)",
  "service_time.p50": "Service time (p50)",
  "service_time.p90": "Service time (p90)",
  "service_time.p99": "Service time (p99)",
  "service_time.p99_9": "Service time (p99.9)",
  "service_time.p100": "Service time (max)",
  "latency.mean": "Latency (mean)",
  "latency.p50": "Latency (p50)",
  "latency.p99": "Latency (p99)",
  "error_rate": "Error rate",
  "duration": "Duration"
};

const LOWER_IS_BETTER = /^(service_time|latency|processing_time|client_processing_time|error_rate|duration)/;

/* Within a chart, colour means "where it ran"; tasks differ by dash and symbol. */
const TASK_DASH = ["solid", [6, 4], [2, 3], [10, 4, 2, 4]];
const TASK_SYMBOL = ["circle", "triangle", "rect", "diamond"];

const state = {
  index: null, workload: null, data: null, charts: [],
  //: Which tasks are on the page at all (the chips), which sections are folded
  //: away, and the panels those two produce. Hiding one line of a chart you are
  //: looking at is the chart's own business, handled by its legend.
  panels: [], tasks: new Set(), collapsed: new Set(), defaults: new Set()
};
const el = (id) => document.getElementById(id);
const metricLabel = (m) => METRIC_LABELS[m] || m;

/* What to call a point on the axis. Not every point is a release: launchr
   classifies a version as release, snapshot or unknown, and a snapshot is a
   nightly or somebody's build from source. A release is named by its version,
   which is the whole point of it. A snapshot's version repeats across every
   build on that branch -- "10.0.0-SNAPSHOT" says nothing about which one -- so
   the commit is what identifies it, and the branch says where it came from. */
function shortBranch(branch) {
  if (!branch) return null;
  return String(branch).replace(/^branch_/, "").replace(/^(\d+)_(\d+)$/, "$1.$2");
}

function pointLabel(point) {
  const line = (state.data && state.data.lines && state.data.lines[point.line]) || {};
  const kind = line.version_kind || "unknown";
  const version = point.solr_version || "";
  if (kind === "release" && version) return version;

  const commit = point.commit ? String(point.commit).slice(0, 7) : null;
  const branch = shortBranch(line.branch);
  if (commit) return `${branch || "src"}#${commit}`;
  if (branch) return `${branch}-nightly`;
  return version || "build";
}

/* "Release" is only the right word when every line on the page is one. */
function buildNoun() {
  const lines = Object.values((state.data && state.data.lines) || {});
  return lines.length && lines.every((l) => l.version_kind === "release")
    ? "release" : "build";
}

function lineColour(data, lineId) {
  const i = Object.keys(data.lines).indexOf(lineId);
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length];
}

/* Colour encodes whatever varies. Comparing environments (several lines), it is
   the line; comparing operations on one environment, it is the task. Encoding
   the line when there is only one leaves every series the same colour. */
function colourFor(data, lineId, task, taskOrder) {
  if (Object.keys(data.lines).length > 1) return lineColour(data, lineId);
  const i = taskOrder.indexOf(task);
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length];
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${url}`);
  return r.json();
}

function formatNumber(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs !== 0 && abs < 0.01) return value.toExponential(2);
  if (abs >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/* ---------------------------------------------------------------- bootstrap */

async function start() {
  try {
    state.index = await getJSON("data/index.json");
  } catch (err) {
    showEmpty(`Could not load data/index.json — ${err.message}`);
    return;
  }

  const title = state.index.title || "Apache Solr Benchmarks";
  el("page-title").textContent = title;
  document.title = title;
  if (state.index.generated_at) el("generated").textContent = `Built ${state.index.generated_at}`;

  const workloads = state.index.workloads || [];
  const totalRuns = workloads.reduce((n, w) => n + (w.runs || 0), 0);
  el("run-count").textContent = `${totalRuns} run${totalRuns === 1 ? "" : "s"}`;

  if (!workloads.length) { showEmpty(); return; }

  buildNav(workloads);
  const wanted = parseHash();
  const opening = workloads.find((w) => w.name === wanted.workload) || workloads[0];
  await selectWorkload(opening.name, opening.name === wanted.workload ? wanted.task : null);

  window.addEventListener("hashchange", () => {
    const target = parseHash();
    if (target.workload && target.workload !== state.workload) {
      selectWorkload(target.workload, target.task);
    } else if (target.task) {
      const added = ensureCharted(target.task);
      if (added) state.panels = buildPanels();
      if (revealSection(target.task) || added) {
        buildTaskChips();
        render();
      }
      scrollToSection(target.task);
    }
  });
  window.addEventListener("resize", () => state.charts.forEach((c) => c.resize()));
  /* Closed unless this reader has opened it before. It is reference material,
     not something to scroll past on every visit. */
  const howto = el("howto");
  howto.open = localStorage.getItem("reportr.howto") === "open";
  howto.addEventListener("toggle", () => {
    try { localStorage.setItem("reportr.howto", howto.open ? "open" : "closed"); }
    catch (e) { /* private browsing; the panel simply starts closed each time */ }
  });

  el("detail-close").addEventListener("click", closeDetail);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
}

function showEmpty(message) {
  el("empty").hidden = false;
  if (message) {
    const p = document.createElement("p");
    p.className = "error";
    p.textContent = message;
    el("empty").appendChild(p);
  }
}

function buildNav(workloads) {
  const nav = el("workload-nav");
  nav.textContent = "";
  for (const w of workloads) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "nav-item";
    b.dataset.workload = w.name;
    b.innerHTML = `<span class="dot"></span><span>${esc(w.name)}</span><span class="nav-count">${w.runs}</span>`;
    b.title = `${w.runs} run(s), ${w.points} points, latest ${w.latest}`;
    b.addEventListener("click", () => selectWorkload(w.name));
    nav.appendChild(b);
  }
}

/* The hash is "#workload" or "#workload/section", so any section of the page
   can be linked to directly -- a task charted on its own, or the query charts
   as a group. */
function parseHash() {
  const raw = (location.hash || "").replace(/^#/, "");
  if (!raw) return { workload: null, task: null };
  const cut = raw.indexOf("/");
  if (cut < 0) return { workload: decodeURIComponent(raw), task: null };
  return {
    workload: decodeURIComponent(raw.slice(0, cut)),
    task: decodeURIComponent(raw.slice(cut + 1))
  };
}

/* Reports are data written by whoever ran the benchmark, and workload hints and
   release notes are text from other repositories: nothing in them is markup.
   Every string that reaches an innerHTML template goes through esc(). */
const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
}

/* A link in a release note is for people to follow: http(s) only. */
function safeUrl(url) {
  return /^https?:\/\//i.test(String(url || "")) ? String(url) : null;
}

function hashFor(workload, group) {
  return "#" + encodeURIComponent(workload) +
    (group ? "/" + encodeURIComponent(sectionSlug(group)) : "");
}

/* Every section is linkable, not just the ones a workload featured: "look at
   the query charts for nyc_taxis" is a link someone wants to send. The slug is
   what goes in the hash, and the same slug is the element id. */
function sectionSlug(group) {
  return String(group).trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function sectionAnchorId(group) {
  return "s-" + sectionSlug(group);
}

function scrollToSection(slug) {
  const node = document.getElementById("s-" + sectionSlug(slug));
  if (node) node.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* A link to a task's chart has to produce that chart. The chips are a reader's
   own selection and a bookmark carries none of it, so a fragment naming a task
   switches it on rather than landing on a section that was never built.
   Returns whether anything changed. */
function ensureCharted(slug) {
  if (!slug || !state.data) return false;
  const task = (state.data.tasks || []).find((name) => sectionSlug(name) === sectionSlug(slug));
  if (!task || state.tasks.has(task)) return false;
  state.tasks.add(task);
  return true;
}

async function selectWorkload(name, focusTask) {
  const entry = (state.index.workloads || []).find((w) => w.name === name);
  if (!entry) return;

  state.workload = name;
  location.hash = hashFor(name, focusTask);
  el("crumb").textContent = name;
  /* Name the workload in the heading and the tab: a bookmarked chart should say
     which benchmark it is, not just that it is a benchmark. */
  const base = state.index.title || "Apache Solr Benchmarks";
  el("page-title").textContent = `${base} — ${name}`;
  document.title = `${base} — ${name}`;
  for (const b of el("workload-nav").querySelectorAll(".nav-item")) {
    b.classList.toggle("active", b.dataset.workload === name);
  }

  try {
    state.data = await getJSON(entry.file);
  } catch (err) {
    showEmpty(`Could not load ${entry.file} — ${err.message}`);
    return;
  }

  state.defaults = new Set((state.data.default_tasks || []).length
    ? state.data.default_tasks
    : state.data.tasks.slice(0, 2));
  /* The chips are the tasks with a chart of their own, and the ones the
     workload singled out are simply the ones pre-selected. Picking any other
     gives it the same treatment -- a chip that meant "own chart" for some tasks
     and "another line" for others was one gesture with two outcomes. */
  state.tasks = new Set((state.data.featured_tasks || []).filter(
    (task) => (state.data.tasks || []).includes(task)));
  ensureCharted(focusTask);
  state.collapsed = loadCollapsed(name);
  state.panels = buildPanels();
  if (revealSection(focusTask)) state.panels = buildPanels();

  el("controls").hidden = false;
  buildAbout();
  buildStats(entry);
  buildTaskChips();
  buildLegend();
  render();
  if (focusTask) setTimeout(() => scrollToSection(focusTask), 120);
}

/* Unfold whatever section holds the thing a link points at. Landing on a
   collapsed heading is the same disappointment as landing on nothing. */
function revealSection(slug) {
  if (!slug || !state.collapsed.size) return false;
  const wanted = sectionSlug(slug);
  for (const group of Array.from(state.collapsed)) {
    const holds = state.panels.some(
      (panel) => panel.group === group &&
        (sectionSlug(group) === wanted || (panel.sub && sectionSlug(panel.sub) === wanted)));
    if (holds) {
      state.collapsed.delete(group);
      saveCollapsed();
      return true;
    }
  }
  return false;
}

/* What this workload is and what it is for. Without it the page is a wall of
   numbers whose provenance the reader has to guess. */
function buildAbout() {
  const host = el("about");
  const text = (state.data.description || "").trim();
  el("about-text").textContent = text;
  el("about-workload").textContent = state.workload;
  host.hidden = !text;
}

/* --------------------------------------------------------------- stat tiles */

function buildStats(entry) {
  const points = (state.data.series || []).flatMap((s) => s.points);
  const versions = new Set(points.map((p) => pointLabel(p)));
  const lines = Object.keys(state.data.lines || {}).length;
  const span = points.length
    ? `${points.reduce((a, p) => (p.x < a ? p.x : a), points[0].x).slice(0, 7)} → ${entry.latest}`
    : "—";

  const tiles = [
    { label: "Runs charted", value: entry.runs, cls: "", delta: `${entry.points} data points` },
    { label: buildNoun() === "release" ? "Solr releases" : "Solr builds",
      value: versions.size, cls: "blue", delta: span },
    { label: "Tasks measured", value: (state.data.tasks || []).length, cls: "lorange",
      delta: `${(state.data.metrics || []).length} metrics` },
    { label: "Lines", value: lines, cls: "dark", delta: "profile × cluster config" }
  ];

  el("stats").innerHTML = tiles.map((t) => `
    <div class="stat ${t.cls}">
      <div class="stat-label">${esc(t.label)}</div>
      <div class="stat-value">${esc(t.value)}</div>
      <div class="stat-delta">${esc(t.delta)}</div>
    </div>`).join("");
}

/* One chip per task the run measured, and nothing else -- a chip is a thing the
   benchmark did, not a panel the site drew. Switching one on gives that task a
   chart of its own, inside the section for the kind of work it is. The tasks
   the workload singled out are simply the ones already on. */
function buildTaskChips() {
  const host = el("task-chips");
  host.textContent = "";
  const kinds = state.data.task_kinds || {};
  const featured = new Set(state.data.featured_tasks || []);

  for (const task of state.data.tasks) {
    const chip = document.createElement("button");
    chip.type = "button";
    const kind = kinds[task] || "query";
    /* No colour code for the singled-out tasks: the page already shows which
       they are, by giving them a chart of their own. */
    chip.className = "chip" + (state.tasks.has(task) ? " active" : "") +
      (kind === "lifecycle" ? " lifecycle" : "");
    chip.textContent = task;
    chip.title = state.tasks.has(task)
      ? `${kind} task · charted on its own below`
      : `${kind} task · click for a chart of its own` +
        (featured.has(task) ? " (the workload singles this one out)" : "");
    chip.addEventListener("click", () => {
      /* Turning the last one off is fine: the shared charts remain. */
      if (state.tasks.has(task)) state.tasks.delete(task);
      else state.tasks.add(task);
      state.panels = buildPanels();
      buildTaskChips();
      render();
    });
    host.appendChild(chip);
  }
}

/* Which sections this reader has folded away, remembered per workload. The
   page opens the same way they left it rather than making them re-collapse the
   setup-and-teardown charts on every visit. */
function collapseKey(workload) {
  return `reportr.collapsed.${workload}`;
}

function loadCollapsed(workload) {
  try {
    const stored = JSON.parse(localStorage.getItem(collapseKey(workload)) || "[]");
    return new Set(Array.isArray(stored) ? stored : []);
  } catch (e) {
    return new Set();  /* private browsing, or something else wrote the key */
  }
}

function saveCollapsed() {
  try {
    localStorage.setItem(collapseKey(state.workload),
                         JSON.stringify(Array.from(state.collapsed)));
  } catch (e) { /* nothing to do; the choice simply lasts this visit */ }
}

function toggleSection(group) {
  if (state.collapsed.has(group)) state.collapsed.delete(group);
  else state.collapsed.add(group);
  saveCollapsed();
  render();
}

function buildLegend() {
  el("line-legend").innerHTML = Object.entries(state.data.lines).map(([id, line]) =>
    `<span class="legend-item"><span class="legend-swatch" style="background:${lineColour(state.data, id)}"></span>${esc(line.label)}</span>`
  ).join("");
}

/* ------------------------------------------------------------------ charts */

const KIND_TITLES = { indexing: "Indexing", query: "Query", lifecycle: "Setup and teardown" };
const KIND_BLURB = {
  indexing: "How much the cluster got through. Higher is better.",
  query: "How long a request took. Lower is better, and the tail matters more than the mean.",
  lifecycle: "Collection setup and teardown. Measured, but not a statement about Solr's speed."
};

/* ------------------------------------------------------- what changed */

/* The one number that speaks for a task. A line chart per task answers "how has
   this moved?"; the matrix below answers "what moved, and when?", and for that
   each task gets one metric, not three. */
const HEADLINE_METRIC = {
  indexing: ["throughput.mean", "service_time.mean"],
  query: ["service_time.p50", "service_time.p90", "service_time.mean"],
  lifecycle: ["service_time.mean"]
};

function headlineSeries(task) {
  const kind = (state.data.task_kinds || {})[task] || "query";
  for (const metric of HEADLINE_METRIC[kind] || []) {
    const found = (state.data.series || []).find((s) => s.task === task && s.metric === metric);
    if (found && found.points.length > 1) return found;
  }
  return null;
}

/* Release-over-release change per task, signed so that positive always means
   better -- throughput up and service time down are the same good news, and a
   reader should not have to remember which chart they are looking at. */
function changeMatrix(lineId) {
  const rows = [];
  const columns = [];
  const cells = [];

  /* The curated tasks, not every task: the matrix answers "what moved?", and
     twelve rows of it answers nothing. */
  const rowTasks = state.defaults.size
    ? (state.data.tasks || []).filter((task) => state.defaults.has(task))
    : (state.data.tasks || []);
  for (const task of rowTasks) {
    const entry = headlineSeries(task);
    if (!entry) continue;
    const points = entry.points.filter((p) => p.line === lineId)
      .slice().sort((a, b) => a.x.localeCompare(b.x));
    if (points.length < 2) continue;

    const row = rows.length;
    rows.push(task);
    for (let i = 1; i < points.length; i++) {
      const before = points[i - 1], after = points[i];
      if (!before.y) continue;
      const label = pointLabel(after) || after.x.slice(0, 10);
      let column = columns.indexOf(label);
      if (column < 0) { column = columns.length; columns.push(label); }
      const raw = ((after.y - before.y) / Math.abs(before.y)) * 100;
      const better = LOWER_IS_BETTER.test(entry.metric) ? -raw : raw;
      cells.push([column, row, Number(better.toFixed(2)), {
        task, metric: entry.metric, from: pointLabel(before), to: pointLabel(after),
        before: before.y, after: after.y, unit: entry.unit, meta: after
      }]);
    }
  }
  return { rows, columns, cells };
}

function changeCard(lineId) {
  const matrix = changeMatrix(lineId);
  if (matrix.rows.length < 2 || !matrix.cells.length) return null;

  const card = document.createElement("section");
  card.className = "chart-block";
  const line = state.data.lines[lineId] || { label: lineId };
  const noun = buildNoun();
  card.innerHTML = `
    <div class="chart-head">
      <div>
        <div class="chart-title">${noun === "release" ? "Release" : "Build"} over ${noun}</div>
        <div class="chart-sub">% better or worse than the ${noun} before · ${esc(line.label)}</div>
      </div>
    </div>`;

  const host = document.createElement("div");
  host.className = "chart heatmap";
  host.style.height = `${Math.max(150, 52 + matrix.rows.length * 26)}px`;
  card.appendChild(host);

  const legend = document.createElement("div");
  legend.className = "chart-legend";
  legend.innerHTML =
    `<span class="legend-item muted">Green is faster, red is slower · ` +
    `one metric per task · click a cell for that run's report</span>`;
  card.appendChild(legend);

  setTimeout(() => state.charts.push(drawHeatmap(host, matrix)), 0);
  return card;
}

function drawHeatmap(host, matrix) {
  const chart = echarts.init(host);
  /* Clamped at ten per cent: benchmark noise lives in the first few, and
     without a clamp one outlier release flattens every other cell to grey. */
  const limit = 10;
  chart.setOption({
    animationDuration: 320,
    grid: { left: 150, right: 20, top: 10, bottom: 56 },
    tooltip: {
      backgroundColor: "#262130", borderWidth: 0, padding: [10, 12],
      textStyle: { color: "#fff", fontSize: 12 },
      formatter: (p) => {
        const d = p.data[3];
        const direction = p.data[2] >= 0 ? "better" : "worse";
        return `<div class="tt-date">${esc(d.from)} → ${esc(d.to)}</div>` +
               `<div class="tt-val">${esc(d.task)} · ${Math.abs(p.data[2]).toFixed(1)}% ${direction}</div>` +
               `<div class="tt-version">${esc(metricLabel(d.metric))}: ` +
               `${formatNumber(d.before)} → ${formatNumber(d.after)} ${esc(d.unit)}</div>`;
      }
    },
    xAxis: {
      type: "category", data: matrix.columns, splitArea: { show: true },
      axisLabel: { color: "#6B6875", fontSize: 10,
                   fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
      axisLine: { lineStyle: { color: "#E6E7E8" } }, axisTick: { show: false }
    },
    yAxis: {
      type: "category", data: matrix.rows, splitArea: { show: true },
      axisLabel: { color: "#3D3847", fontSize: 10,
                   fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
      axisLine: { show: false }, axisTick: { show: false }
    },
    visualMap: {
      /* Each cell is [column, row, change, meta] and ECharts colours by the
         LAST dimension unless told otherwise -- which here is the meta object,
         so every cell came out uncoloured. */
      dimension: 2,
      min: -limit, max: limit, calculable: false, orient: "horizontal",
      left: "center", bottom: 4, itemWidth: 11, itemHeight: 90,
      text: ["better", "worse"], textStyle: { color: "#6B6875", fontSize: 10 },
      inRange: { color: ["#B8340E", "#F3D9D2", "#F1F1F3", "#D6EADB", "#2F8F4E"] }
    },
    series: [{
      type: "heatmap", data: matrix.cells,
      label: {
        show: true, fontSize: 10,
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        formatter: (p) => (p.data[2] > 0 ? "+" : "") + p.data[2].toFixed(0) + "%"
      },
      itemStyle: { borderColor: "#fff", borderWidth: 2, borderRadius: 3 },
      emphasis: { itemStyle: { borderColor: "#262130", borderWidth: 2 } }
    }]
  });
  chart.on("click", (params) => {
    const d = params.data && params.data[3];
    if (d && d.meta) openDetail(Object.assign({}, d.meta, { task: d.task, metric: d.metric, unit: d.unit }));
  });
  return chart;
}

/* The series for one metric in one set of tasks, split by unit: indexing
   throughput is docs/s and a query's is ops/s, and on a shared axis the smaller
   one is flattened against zero. */
function unitsFor(metric, tasksHere) {
  const relevant = (state.data.series || []).filter(
    (s) => s.metric === metric && tasksHere.includes(s.task));
  if (!relevant.length) return [];
  if (metric === "error_rate" && relevant.every((s) => s.points.every((p) => p.y === 0))) {
    return [];  /* An all-zero error rate is a flat line saying nothing. */
  }
  const byUnit = new Map();
  for (const entry of relevant) {
    const unit = entry.unit || "";
    if (!byUnit.has(unit)) byUnit.set(unit, []);
    byUnit.get(unit).push(entry);
  }
  return Array.from(byUnit.entries());
}

/* What a task is judged on. A query held at a fixed request rate says nothing
   through its throughput -- that number is the rate that was asked for -- so it
   is read as latency. A query with no target rate was pushed as hard as it
   would go, and queries per second is the headline. */
function measureOf(task) {
  return (state.data.task_measures || {})[task] || "latency";
}

/* Throughput only belongs on a chart of tasks that were actually driven for
   it. Everything else applies to every task of the kind. */
function tasksFor(metric, tasks) {
  if (!metric.startsWith("throughput")) return tasks;
  const kinds = state.data.task_kinds || {};
  return tasks.filter(
    (task) => (kinds[task] || "query") === "indexing" || measureOf(task) === "throughput");
}

function metricsFor(kind, tasks) {
  const byKind = state.data.metrics_by_kind || {};
  const base = byKind[kind] || state.data.metrics || [];
  /* A workload whose queries run unthrottled is measured in queries per
     second, so lead with it -- without pushing the latency charts off a page
     that is still about how long a request took. */
  if (kind === "query" && tasks.some((task) => measureOf(task) === "throughput") &&
      !base.includes("throughput.mean") && (state.data.metrics || []).includes("throughput.mean")) {
    return ["throughput.mean"].concat(base);
  }
  return base;
}

/* Every panel this workload can show, in the order the page lays them out.
   Computed once per workload: the chips switch panels off, they do not change
   what the set of panels is. */
function buildPanels() {
  const kinds = state.data.task_kinds || {};
  const byKind = state.data.metrics_by_kind || {};
  const panels = [];

  for (const lineId of Object.keys(state.data.lines || {})) {
    const line = state.data.lines[lineId] || { label: lineId };
    panels.push({
      id: `change:${lineId}`, group: "Overview", groupKind: "overview", kind: "change",
      label: "Build over build", lineId,
      hint: `What moved between builds · ${line.label}`
    });
  }

  /* Query first and indexing last, because a release is usually read for what
     happened to its queries; indexing is one task and it keeps. Within a kind,
     the shared chart gives the whole picture and the tasks picked out follow it
     in detail -- a task with a chart of its own is still a task of that kind,
     and putting it in its own top-level section read as though "range" were a
     peer of "Query" rather than one of them. */
  for (const kind of ["query", "lifecycle", "indexing"]) {
    const ofKind = (state.data.tasks || []).filter(
      (task) => (kinds[task] || "query") === kind);
    if (!ofKind.length) continue;
    const group = KIND_TITLES[kind];
    const metrics = metricsFor(kind, ofKind);

    /* The shared chart carries every task of its kind, so any of them can be
       compared against the others from its legend. It opens with the workload's
       curated tasks, minus any that already have a chart of their own -- no
       need to draw the same line twice. A kind with nothing left to open gets
       no shared chart: setup and teardown starts that way on purpose, since a
       create-collection latency says nothing about Solr. */
    const open = ofKind.filter((task) => state.defaults.has(task) && !state.tasks.has(task));
    if (open.length) {
      for (const metric of metrics) {
        for (const [unit, chartSeries] of unitsFor(metric, tasksFor(metric, ofKind))) {
          panels.push({
            id: `kind:${kind}:${metric}:${unit}`, group, groupKind: kind, sub: null,
            label: metricLabel(metric), kind, metric, unit, series: chartSeries,
            open: new Set(open)
          });
        }
      }
    }

    for (const task of ofKind.filter((task) => state.tasks.has(task))) {
      for (const metric of metrics) {
        for (const [unit, chartSeries] of unitsFor(metric, tasksFor(metric, [task]))) {
          panels.push({
            id: `task:${task}:${metric}:${unit}`, group, groupKind: kind, sub: task,
            label: metricLabel(metric), kind, metric, unit, series: chartSeries, task
          });
        }
      }
    }
  }
  return panels;
}

function sectionWith(cards, headHtml, id) {
  const section = document.createElement("section");
  section.className = "section";
  if (id) section.id = id;
  section.innerHTML = headHtml;
  cards.forEach((c) => section.appendChild(c));
  return section;
}

function sectionHead(panel, count) {
  const folded = state.collapsed.has(panel.group);
  const caret = `<button type="button" class="fold" aria-expanded="${!folded}"` +
    ` title="${folded ? "Show" : "Hide"} these charts">${folded ? "▸" : "▾"}</button>`;
  /* The heading itself is the permalink. Folding gets the caret: between a
     link worth keeping and a fold worth repeating, the link wins the target
     a reader is most likely to hit. */
  const title = `<h2>${caret}` +
    `<a href="${hashFor(state.workload, panel.group)}" title="Link to this section">` +
    `${esc(panel.group)}</a></h2>`;

  let meta;
  if (folded) {
    meta = `${count} chart${count === 1 ? "" : "s"} hidden`;
  } else if (panel.groupKind === "overview") {
    meta = `Each ${buildNoun()} against the one before it`;
  } else {
    meta = KIND_BLURB[panel.kind];
  }
  return `<div class="section-head">${title}<span class="meta">${meta}</span></div>`;
}

/* A task the workload singled out: its own block, its own link, inside the
   section for the kind of work it is. */
function subHead(task, kind) {
  const node = document.createElement("div");
  node.className = "sub-head";
  node.id = sectionAnchorId(task);
  node.innerHTML =
    `<h3><a href="${hashFor(state.workload, task)}" title="Link to this chart">${esc(task)}</a></h3>` +
    `<span class="meta">Tracked on its own · ${KIND_BLURB[kind]}</span>`;
  return node;
}

function render() {
  const container = el("charts");
  state.charts.forEach((c) => c.dispose());
  state.charts = [];
  container.textContent = "";

  /* Group first, draw second. A section needs to know how many charts it holds
     before it can say "4 charts hidden", and a collapsed section builds none of
     them -- ECharts cannot size a chart inside a hidden container, and drawing
     one nobody asked to see is work for nothing. */
  const groups = [];
  for (const panel of state.panels) {
    const last = groups[groups.length - 1];
    if (last && last.group === panel.group) last.panels.push(panel);
    else groups.push({ group: panel.group, first: panel, panels: [panel] });
  }

  let drew = 0;
  for (const entry of groups) {
    const folded = state.collapsed.has(entry.group);
    const cards = [];
    if (!folded) {
      let sub = null;
      for (const panel of entry.panels) {
        const card = panel.kind === "change" ? changeCard(panel.lineId) : chartCard(panel);
        if (!card) continue;
        if (panel.sub && panel.sub !== sub) cards.push(subHead(panel.sub, panel.kind));
        sub = panel.sub || null;
        cards.push(card);
      }
    }
    if (!folded && !cards.length) continue;

    const section = sectionWith(cards, sectionHead(entry.first, entry.panels.length),
                                sectionAnchorId(entry.group));
    if (folded) section.classList.add("folded");
    section.querySelector(".fold").addEventListener("click", () => toggleSection(entry.group));
    container.appendChild(section);
    /* Sub-headings ride along in the same list; only charts count as drawn. */
    drew += cards.filter((node) => node.classList.contains("chart-block")).length;
  }

  const sections = groups.length;
  el("controls-meta").textContent =
    `${state.panels.length} chart${state.panels.length === 1 ? "" : "s"}` +
    ` in ${sections} section${sections === 1 ? "" : "s"}`;
  el("empty").hidden = drew > 0 || state.collapsed.size > 0;
}

function chartCard(panel) {
  const { metric, unit } = panel;
  const group = panel.series;
  const card = document.createElement("section");
  card.className = "chart-block";
  const lowerBetter = LOWER_IS_BETTER.test(metric);
  const latest = latestAndDelta(group);

  let currentHtml = "";
  if (latest) {
    const improved = lowerBetter ? latest.delta < 0 : latest.delta > 0;
    const cls = latest.delta === 0 ? "" : (improved ? "up" : "down");
    const sign = latest.delta > 0 ? "+" : "";
    const deltaText = latest.previous === null
      ? "first data point"
      : `${sign}${latest.deltaPct.toFixed(1)}% vs ${latest.previousVersion}`;
    currentHtml = `
      <div class="chart-current">
        <div class="chart-current-val">${formatNumber(latest.value)}<span class="unit">${esc(unit)}</span></div>
        <div class="chart-current-delta ${cls}">${esc(deltaText)}</div>
      </div>`;
  }

  /* The subtitle no longer lists the tasks: the chart's own legend names them,
     and naming them twice in one panel is noise. */
  card.innerHTML = `
    <div class="chart-head">
      <div>
        <div class="chart-title">${esc(metricLabel(metric))}</div>
        <div class="chart-sub">${unit ? esc(unit) + " · " : ""}${lowerBetter ? "lower is better" : "higher is better"}</div>
      </div>
      ${currentHtml}
    </div>`;

  const host = document.createElement("div");
  host.className = "chart";
  card.appendChild(host);

  const hint = document.createElement("div");
  hint.className = "chart-legend";
  hint.innerHTML =
    `<span class="legend-item muted">Click a line's name above to show or hide it` +
    ` · click a point for the full report</span>`;
  card.appendChild(hint);

  /* ECharts needs the host in the document before it can size itself. */
  setTimeout(() => state.charts.push(drawChart(host, metric, group, unit, panel.open)), 0);
  return card;
}

function latestAndDelta(group) {
  /* Only meaningful for a single line of a single task. Across several tasks the
     "last two points" are two different measurements, and the percentage between
     them means nothing. */
  const lines = new Set(group.flatMap((s) => s.points.map((p) => p.line)));
  if (group.length !== 1 || lines.size !== 1) return null;
  const points = group[0].points.slice().sort((a, b) => (a.x < b.x ? -1 : 1));
  if (!points.length) return null;
  const last = points[points.length - 1];
  const previous = points.length > 1 ? points[points.length - 2] : null;
  const delta = previous ? last.y - previous.y : 0;
  return {
    value: last.y,
    previous: previous ? previous.y : null,
    previousVersion: previous ? pointLabel(previous) : null,
    delta,
    deltaPct: previous && previous.y ? (delta / previous.y) * 100 : 0
  };
}

const TOOL_TITLES = {
  zoom: "Drag a box to zoom (already on)",
  back: "Undo the last zoom",
  restore: "Reset the zoom"
};

/* Markers for the things that explain a step in a line but are not in it: the
   workload changed, a task's setup changed, or somebody wrote down what a
   release did. Scoped to the charts they are about -- a note on "range" does
   not belong on the indexing chart -- and drawn once per x even when several
   lines cross it. */
function annotationsFor(seriesList) {
  const tasks = new Set(seriesList.map((s) => s.task));
  const lines = new Set(seriesList.flatMap((s) => s.points.map((p) => p.line)));
  const seen = new Map();
  for (const note of state.data.annotations || []) {
    if (note.task && !tasks.has(note.task)) continue;
    if (note.line && !lines.has(note.line)) continue;
    const at = seen.get(note.x);
    if (at) at.push(note);
    else seen.set(note.x, [note]);
  }
  return seen;
}

const ANNOTATION_STYLE = {
  release: { colour: "#305CB3", glyph: "◆" },
  workload: { colour: "#8C5BA8", glyph: "✎" },
  note: { colour: "#8C5BA8", glyph: "✎" }
};

function annotationMarkLine(seriesList) {
  const grouped = annotationsFor(seriesList);
  if (!grouped.size) return null;
  const data = [];
  for (const [x, notes] of grouped) {
    const lead = notes[0];
    const style = ANNOTATION_STYLE[lead.kind] || ANNOTATION_STYLE.note;
    data.push({
      xAxis: +new Date(x),
      label: {
        formatter: style.glyph + (notes.length > 1 ? ` ×${notes.length}` : ""),
        position: "insideEndTop", color: style.colour, fontSize: 11
      },
      lineStyle: { color: style.colour, type: [5, 4], width: 1, opacity: .75 },
      /* The text rides on the item so the tooltip can read it back. */
      notes
    });
  }
  return {
    silent: false, symbol: "none", animation: false, data,
    emphasis: { lineStyle: { width: 2, opacity: 1 } }
  };
}

function annotationTooltip(notes) {
  return notes.map((note) => {
    const url = safeUrl(note.url);
    const body = url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(note.text)}</a>`
      : esc(note.text);
    const head = note.kind === "release" ? `Solr ${note.version || ""}`.trim()
                                         : (note.task ? note.task : "Workload");
    return `<div class="tt-date">${esc(head)}</div><div class="tt-note">${body}</div>`;
  }).join("");
}

function drawChart(host, metric, seriesList, unit, open) {
  const chart = echarts.init(host);
  const taskOrder = Array.from(new Set(seriesList.map((s) => s.task)));
  const multiTask = taskOrder.length > 1;

  /* A band showing the distribution the headline number came out of: the
     slowest and fastest sampling interval behind a mean throughput, the median
     and the tail behind a p90. Only on a chart of one line and one task --
     overlapping translucent bands are mud, and the question a band answers
     ("how settled is this number?") is one you ask of a single series. Drawn as
     a transparent floor plus a stacked height, which is how ECharts draws a
     range without a dedicated range series. */
  const soloChart = seriesList.length === 1 &&
    new Set(seriesList[0].points.map((p) => p.line)).size === 1;
  const banded = soloChart && seriesList[0].points.some((p) => p.lo !== undefined);
  const bands = [];
  if (banded) {
    const pts = seriesList[0].points.filter((p) => p.lo !== undefined);
    const shared = { type: "line", stack: "spread", symbol: "none", silent: true,
                     legendHoverLink: false, tooltip: { show: false },
                     lineStyle: { opacity: 0 }, z: 1 };
    bands.push(Object.assign({ name: "spread-floor", data: pts.map((p) => [p.x, p.lo]) }, shared));
    bands.push(Object.assign({
      name: "spread",
      data: pts.map((p) => [p.x, p.hi - p.lo]),
      areaStyle: { color: "rgba(217,65,30,.11)" }
    }, shared));
  }

  /* Which series a legend entry belongs to, so the panel can open with the
     curated tasks switched on and the rest a click away. */
  const seriesTask = {};
  const marks = annotationMarkLine(seriesList);
  let marked = false;
  const series = seriesList.flatMap((entry) => {
    const taskIndex = taskOrder.indexOf(entry.task);
    const byLine = new Map();
    for (const point of entry.points) {
      if (!byLine.has(point.line)) byLine.set(point.line, []);
      byLine.get(point.line).push(point);
    }
    return Array.from(byLine.entries()).map(([lineId, points]) => {
      const line = state.data.lines[lineId] || { label: lineId };
      const colour = colourFor(state.data, lineId, entry.task, taskOrder);
      const manyLines = Object.keys(state.data.lines).length > 1;
      /* The line only earns a place in the name when there is more than one of
         them; on a single-environment site it is the same words every time. */
      const name = multiTask
        ? (manyLines ? `${entry.task} — ${line.label}` : entry.task)
        : (manyLines ? line.label : entry.task);
      seriesTask[name] = entry.task;
      /* One series carries the markers; repeating them per line would stack
         identical dashes on the same date. */
      const markLine = marked ? undefined : (marked = true, marks || undefined);
      return {
        name,
        type: "line",
        markLine,
        symbol: TASK_SYMBOL[taskIndex % TASK_SYMBOL.length],
        symbolSize: 9,
        connectNulls: true,
        lineStyle: {
          width: 2, color: colour,
          /* Dashes only carry the task when colour is busy carrying the line. */
          type: manyLines ? TASK_DASH[taskIndex % TASK_DASH.length] : "solid"
        },
        itemStyle: { color: colour },
        emphasis: { focus: "series", scale: 1.6 },
        data: points.map((p) => ({
          value: [p.x, p.y],
          meta: Object.assign({}, p, { task: entry.task, metric, unit })
        }))
      };
    });
  });

  /* The Solr version belongs to the x position, not to every dot on it: each
     release sits at one date, and every line crossing that date ran that same
     release. Labelling points repeated the version once per series and once per
     task. A second x-axis says it once, under the date axis, and ECharts thins
     the labels when releases crowd together. */
  const versionAt = new Map();
  for (const entry of seriesList) {
    for (const point of entry.points) {
      const label = pointLabel(point);
      if (label) versionAt.set(+new Date(point.x), label);
    }
  }
  const versionTicks = Array.from(versionAt.keys()).sort((a, b) => a - b);
  /* Both axes get the same explicit extent: an axis with no series of its own
     has nothing to derive one from, and a version tick that drifts off the date
     it belongs to is worse than no tick at all. The padding keeps the first and
     last labels clear of the y-axis and the right edge. */
  const lo = versionTicks.length ? versionTicks[0] : 0;
  const hi = versionTicks.length ? versionTicks[versionTicks.length - 1] : 1;
  const pad = Math.max((hi - lo) * 0.06, 86400000);
  const timeAxis = { type: "time", min: lo - pad, max: hi + pad };

  /* Everything this chart could draw is in the legend; the chips decide which
     of them it opens with. Turning one on here shows it in this chart only,
     without putting it on every other chart on the page. */
  const selected = {};
  for (const [name, task] of Object.entries(seriesTask)) {
    selected[name] = !open || open.has(task);
  }
  if (!Object.values(selected).some(Boolean)) {
    for (const name of Object.keys(selected)) selected[name] = true;
  }

  chart.setOption({
    animationDuration: 320,
    color: PALETTE,
    grid: { left: 64, right: 30, top: 72, bottom: 112 },
    legend: {
      /* Its own row, full width. Sharing a line with the toolbox meant a
         workload with seven query tasks ran its legend straight through the
         zoom buttons -- and reserving a fixed strip for them only moves the
         collision to the next workload with longer task names. */
      type: "scroll", top: 26, left: 0, right: 0,
      itemWidth: 16, itemHeight: 3, itemGap: 14, icon: "roundRect",
      selected,
      textStyle: { color: "#3D3847", fontSize: 11,
                   fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
      inactiveColor: "#C3C1CA",
      pageIconColor: "#6B6875", pageIconInactiveColor: "#D8D7DC", pageIconSize: 10,
      pageTextStyle: { color: "#6B6875", fontSize: 10 },
      /* The band is scaffolding for the line above it, not a series anyone
         turns off. */
      data: Object.keys(seriesTask)
    },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: "#262130",
      borderWidth: 0,
      padding: [10, 12],
      textStyle: { color: "#fff", fontSize: 12 },
      formatter: (params) => (params.data && params.data.notes)
        ? annotationTooltip(params.data.notes)
        : tooltipHtml(params.data.meta)
    },
    xAxis: [
      Object.assign({}, timeAxis, {
        /* No axis name: the chips below spell out what the axis is, and a
           caption placed under them lands on the zoom slider. */
        axisLine: { lineStyle: { color: "#E6E7E8" } },
        axisLabel: { color: "#6B6875" },
        splitLine: { show: false }
      }),
      Object.assign({}, timeAxis, {
        position: "bottom", offset: 20,
        axisLine: { show: false },
        axisTick: {
          show: true, customValues: versionTicks, length: 4, inside: true,
          lineStyle: { color: "#D9411E" }
        },
        /* Upright chips: a version string is wider than the gap between two
           releases, so laid flat they collide and ECharts hides most of them.
           Turned on their side they each need a few pixels of width, and a
           dense release history still shows every one. */
        axisLabel: {
          customValues: versionTicks,
          formatter: (value) => versionAt.get(value) || "",
          hideOverlap: true,
          rotate: -90,
          align: "center",
          color: "#8F2B0B", fontSize: 10,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          backgroundColor: "rgba(217,65,30,.10)",
          borderColor: "rgba(217,65,30,.28)", borderWidth: 1, borderRadius: 3,
          padding: [3, 5]
        },
        splitLine: { show: false }
      })
    ],
    yAxis: {
      type: "value", scale: true,
      axisLabel: { color: "#6B6875" },
      splitLine: { lineStyle: { color: "#EFEFF1" } }
    },
    toolbox: {
      right: 8, top: 0, itemSize: 14, itemGap: 8,
      iconStyle: { borderColor: "#6B6875" },
      emphasis: { iconStyle: { borderColor: "#D9411E" } },
      /* ECharts' built-in titles render directly under the pointer, covering the
         button you are reaching for. Use the tooltip instead, placed above and
         to the left of the cursor so the icon stays visible. */
      showTitle: false,
      tooltip: {
        show: true,
        backgroundColor: "#262130",
        borderWidth: 0,
        padding: [6, 9],
        textStyle: { color: "#fff", fontSize: 11 },
        /* With showTitle off ECharts labels the tooltip with the raw icon name
           ("back"), not the title configured below, so spell them out here. */
        formatter: (p) => TOOL_TITLES[p.name] || p.title || p.name,
        position: (point, params, dom, rect, size) => [
          Math.max(4, point[0] - size.contentSize[0] - 14),
          Math.max(4, point[1] - size.contentSize[1] - 12)
        ]
      },
      feature: {
        dataZoom: {
          yAxisIndex: "none",
          title: { zoom: "Drag a box to zoom", back: "Undo zoom" }
        },
        restore: { title: "Reset zoom" }
      }
    },
    /* No "inside" zoom. It takes the wheel whenever the pointer is over a chart
       -- gating it behind shift stops it rescaling the chart but it still
       swallows the event, so the page would not scroll past a chart at all.
       Dragging a box and the slider below cover zooming between them. */
    dataZoom: [
      { type: "slider", xAxisIndex: [0, 1], height: 18, bottom: 16, filterMode: "none",
        borderColor: "#E6E7E8", fillerColor: "rgba(217,65,30,.08)",
        handleStyle: { color: "#D9411E" }, moveHandleStyle: { color: "#D9411E" },
        textStyle: { color: "#6B6875", fontSize: 10 } }
    ],
    series: bands.concat(series)
  });

  chart.on("click", (params) => {
    if (params.data && params.data.meta) openDetail(params.data.meta);
  });
  /* Box zoom is the primary way to narrow in on a static history, so arm it up
     front instead of making the reader find the toolbox first. A click without a
     drag still falls through to the point, so this costs nothing. ECharts drops
     the cursor mode once a box is drawn, so re-arm after every zoom. */
  const armBoxZoom = () => chart.dispatchAction({
    type: "takeGlobalCursor", key: "dataZoomSelect", dataZoomSelectActive: true
  });
  armBoxZoom();
  chart.on("dataZoom", () => setTimeout(armBoxZoom, 0));
  chart.on("restore", () => setTimeout(armBoxZoom, 0));
  return chart;
}

/* A release is "Solr 9.11.0". A snapshot is that version plus the branch it was
   built from and the commit it was built at, because the version alone is the
   same for every nightly on that branch. */
function versionLine(meta) {
  const line = (state.data.lines || {})[meta.line] || {};
  const kind = line.version_kind || "unknown";
  const commit = meta.commit ? " · " + String(meta.commit).slice(0, 10) : "";
  if (kind === "release") return `Solr ${meta.solr_version}${commit}`;
  const branch = shortBranch(line.branch);
  const where = branch ? ` (${branch})` : "";
  return `Solr ${meta.solr_version || "build"}${where}${commit}`;
}

function tooltipHtml(meta) {
  const parts = [
    `<div class="tt-date">${esc(meta.x.slice(0, 10))} · ${esc(meta.timestamp_source || "unknown source")}</div>`,
    `<div class="tt-val">${formatNumber(meta.y)}${meta.unit ? " " + esc(meta.unit) : ""} · ${esc(meta.task)}</div>`,
    `<div class="tt-version">${esc(versionLine(meta))}</div>`
  ];
  const notes = [];
  if (meta.test_mode) notes.push("test mode — 1000 documents");
  if (meta.workload_revision) notes.push("workload " + esc(meta.workload_revision));
  notes.push("Click to open the full report");
  parts.push(`<div class="tt-note">${notes.join("<br>")}</div>`);
  return parts.join("");
}

/* ------------------------------------------------------------- run detail */

async function openDetail(meta) {
  el("detail").hidden = false;
  el("detail-title").textContent = meta.run_id;
  el("detail-body").innerHTML = `<p class="muted">Loading report…</p>`;
  try {
    const report = await getJSON(`reports/${encodeURIComponent(meta.run_id)}.json`);
    el("detail-body").innerHTML = detailHtml(report, meta);
  } catch (err) {
    el("detail-body").innerHTML = `<p class="error">Could not load the report — ${esc(err.message)}</p>`;
  }
}

function closeDetail() { el("detail").hidden = true; }

function detailHtml(report, meta) {
  const L = report.launchr || {};
  const solr = L.solr || {};
  const infra = L.infra || {};
  const cc = L.cluster_config || {};
  const bench = L.benchmark || {};
  const wl = L.workload || {};
  const host = infra.host || {};

  const badges = [];
  if (bench.test_mode) badges.push(`<span class="cat-badge testmode">test mode</span>`);
  if (infra.provider === "local") badges.push(`<span class="cat-badge local">local</span>`);

  let caveat = "";
  if (bench.test_mode || infra.provider === "local") {
    const bits = [];
    if (bench.test_mode) bits.push("indexed 1000 documents, so absolute numbers are not comparable with a full run");
    if (infra.provider === "local") bits.push("ran with the load driver on the same machine as Solr, so treat it as development data");
    caveat = `<p class="caveat">This run ${bits.join(", and ")}.</p>`;
  }

  const sections = [
    section("Solr", [
      ["Version", solr.version], ["Commit", code(solr.commit)], ["Lucene", solr.lucene_version],
      ["Image", code(solr.image)], ["Version date", solr.version_timestamp],
      ["Dated from", `${solr.version_timestamp_source || "?"} (${solr.version_timestamp_precision || "?"})`],
      ["Kind", solr.version_kind + (solr.branch ? ` · ${solr.branch}` : "")],
      ["JVM", solr.jvm ? `${solr.jvm.vendor || "?"} ${solr.jvm.version || ""}`.trim() : null]
    ]),
    section("Where it ran", [
      ["Profile", infra.provisioning_profile], ["Provisioning", infra.provisioning],
      ["Install", infra.install_method], ["Provider", infra.provider], ["Nodes", infra.nodes],
      ["Host", host.os ? `${host.os} · ${host.cpu || "?"} · ${host.cores || "?"} cores · ${host.memory_gb || "?"} GB` : null]
    ]),
    section("Cluster config", [
      ["Name", cc.name], ["Heap", cc.heap], ["GC", cc.gc],
      ["Shards", cc.shards], ["Replicas", cc.replicas],
      ["Applied", cc.applied_env ? markup(Object.entries(cc.applied_env).map(([k, v]) => code(`${k}=${v}`).html).join(" ")) : null]
    ]),
    section("Benchmark", [
      ["Workload", wl.name], ["Procedure", wl.test_procedure || "default"],
      ["Workload rev", code(wl.revision)], ["Iterations", bench.iterations],
      ["Solr Orbit", bench.orbit_version], ["Started", L.started_at], ["Finished", L.finished_at],
      ["Session", code(L.session_id)]
    ])
  ];

  const ops = ((report.results || {}).op_metrics) || [];
  let opsTable = "";
  if (ops.length) {
    const rows = ops.map((op) =>
      `<tr class="${op.task === meta.task ? "current" : ""}"><td>${esc(op.task)}</td>` +
      `<td>${formatNumber(op.throughput && op.throughput.mean)}</td>` +
      `<td>${formatNumber(op.service_time && op.service_time.mean)}</td>` +
      `<td>${formatNumber(op.error_rate)}</td></tr>`).join("");
    opsTable = `<h3>Operations</h3><table class="ops"><thead><tr><th>Task</th>` +
      `<th>Throughput</th><th>Service time</th><th>Errors</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  return `<div class="detail-badges">${badges.join("")}</div>${caveat}${sections.join("")}${opsTable}`;
}

/* Markup built here, as opposed to text from a report: section() leaves it alone. */
function markup(html) { return { html }; }
function code(value) { return value ? markup(`<code>${esc(value)}</code>`) : null; }

function section(title, rows) {
  const body = rows
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `<div class="kv-row"><div class="kv-key">${esc(k)}</div><div class="kv-val">${v && v.html !== undefined ? v.html : esc(v)}</div></div>`)
    .join("");
  return body ? `<h3>${title}</h3><div class="kv-list">${body}</div>` : "";
}

start();
