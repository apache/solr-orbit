# SPDX-License-Identifier: Apache-2.0
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Group data points into the series a chart draws.

One :class:`~solrorbit.tools.reportr.models.Series` per task and metric, holding
the points for every line. The site renders one chart per metric and lets the
reader pick tasks, so this is the shape it wants.
"""

import logging
from collections import OrderedDict
from typing import Iterable

from solrorbit.tools.reportr.models import DataPoint, LineIdentity, Series

logger = logging.getLogger(__name__)


def group(points: Iterable[DataPoint]) -> list[Series]:
    """Collect points into series, keyed by (task, metric)."""
    series: "OrderedDict[tuple[str, str], Series]" = OrderedDict()
    for point in points:
        key = (point.task, point.metric)
        existing = series.get(key)
        if existing is None:
            existing = Series(task=point.task, metric=point.metric, unit=point.unit)
            series[key] = existing
        elif not existing.unit and point.unit:
            existing.unit = point.unit
        existing.points.append(point)
    return list(series.values())


def lines(points: Iterable[DataPoint]) -> "OrderedDict[str, LineIdentity]":
    """Every distinct line present, in first-seen order."""
    found: "OrderedDict[str, LineIdentity]" = OrderedDict()
    for point in points:
        found.setdefault(point.line.id, point.line)
    return found


def tasks(points: Iterable[DataPoint]) -> list[str]:
    """Every task present, in first-seen order."""
    seen: list[str] = []
    for point in points:
        if point.task not in seen:
            seen.append(point.task)
    return seen


def metrics(points: Iterable[DataPoint]) -> list[str]:
    """Every metric present, in first-seen order."""
    seen: list[str] = []
    for point in points:
        if point.metric not in seen:
            seen.append(point.metric)
    return seen


def note_changes(points: Iterable[DataPoint], notes_by_run: dict) -> list[dict]:
    """Where a task's own note about its setup changed.

    A workload keeps a ``reportr.note`` on a task saying how the thing is set
    up -- which facet implementation a query uses, say. When the workload
    changes that setup it changes the note, and the chart should say so at the
    point it happened: a step in the line that comes from the benchmark asking
    a different question is not a step in Solr.
    """
    by_series: dict[tuple[str, str], list[DataPoint]] = {}
    for point in points:
        by_series.setdefault((point.line.id, point.task), []).append(point)

    found: list[dict] = []
    for (line_id, task), group in by_series.items():
        previous: str | None = None
        seen_any = False
        for point in sorted(group, key=lambda p: p.x):
            note = (notes_by_run.get(point.run_id) or {}).get(task)
            if note and seen_any and note != previous:
                found.append({
                    "kind": "note", "line": line_id, "task": task,
                    "x": point.x.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "text": note, "url": None,
                })
            if note is not None:
                previous = note
            seen_any = True
    return sorted(found, key=lambda a: (a["x"], a["task"]))


def release_notes(points: Iterable[DataPoint], configured: Iterable[dict]) -> list[dict]:
    """Curated notes about a particular Solr build, placed where it sits.

    A release that fixes a regression is the explanation for a step in every
    chart on the page, so one entry marks them all unless it names a task.
    A version nothing was benchmarked at is dropped rather than guessed at.
    """
    earliest: dict[str, DataPoint] = {}
    for point in points:
        existing = earliest.get(point.solr_version)
        if existing is None or point.x < existing.x:
            earliest[point.solr_version] = point

    found: list[dict] = []
    for entry in configured or []:
        version = str(entry.get("version") or "").strip()
        anchor = earliest.get(version)
        if not anchor:
            logger.info("Annotation for %r has no benchmarked run; skipping", version)
            continue
        found.append({
            "kind": "release", "line": None, "task": entry.get("task"),
            "x": anchor.x.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": version,
            "text": str(entry.get("text") or "").strip(),
            "url": entry.get("url"),
        })
    return sorted(found, key=lambda a: a["x"])


def revision_changes(points: Iterable[DataPoint]) -> list[dict]:
    """Where a line's workload revision changed, for an annotation marker.

    A workload change moves numbers as surely as a Solr change does, so the
    reader should see it before deciding what a step means. One entry per line
    per change, at the x position of the first point on the new revision.
    """
    by_line: dict[str, list[DataPoint]] = {}
    for point in points:
        by_line.setdefault(point.line.id, []).append(point)

    changes: list[dict] = []
    for line_id, line_points in by_line.items():
        ordered = sorted(line_points, key=lambda p: p.x)
        previous: str | None = None
        for point in ordered:
            revision = point.workload_revision
            if revision and previous and revision != previous:
                changes.append({
                    "kind": "workload", "line": line_id, "task": None,
                    "x": point.x.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "from": previous,
                    "to": revision,
                    "text": f"Workload changed: {previous} → {revision}",
                    "url": None,
                })
            if revision:
                previous = revision
    return changes


#: Operations that set the benchmark up or tear it down. They are measured, but
#: a create-collection latency says nothing about Solr's performance, and
#: charting them buries the operations that do.
LIFECYCLE_TASKS = frozenset({
    "create-collection", "delete-collection", "check-cluster-health",
    "refresh-after-index", "optimize", "wait-for-merges", "force-merge",
})

#: Tasks whose name marks them as writing documents.
_INDEXING_HINTS = ("index", "bulk", "ingest", "update", "append")

KIND_INDEXING = "indexing"
KIND_QUERY = "query"
KIND_LIFECYCLE = "lifecycle"

#: Candidate metrics per kind, in priority order. Indexing is judged on how much
#: it got through; a query on how long it took -- which is why OpenSearch's
#: published query dashboards filter to service_time rather than throughput.
#:
#: A list rather than a fixed choice because which percentiles exist depends on
#: how many samples a run produced: a full run offers p99, a test-mode run may
#: only have the mean. The builder keeps those that are present, capped, so the
#: page stays readable instead of charting every metric for every task.
#: p50 and p90 lead, and p99 follows. The stock query tasks measure 100
#: iterations after warmup, and the 99th percentile of 100 samples is the
#: second-highest observation -- a single draw, which moves run to run for
#: reasons that have nothing to do with Solr. p50 and p90 rest on enough samples
#: to mean something. p99 is still charted when a run carries it, because the
#: tail is what users feel; it is just not the headline.
METRICS_BY_KIND = {
    KIND_INDEXING: ["throughput.mean", "service_time.mean", "error_rate"],
    KIND_QUERY: ["service_time.p50", "service_time.p90", "service_time.p99",
                 "service_time.mean", "error_rate"],
    KIND_LIFECYCLE: ["service_time.mean", "error_rate"],
}

#: How many charts a kind may contribute. Three is about what fits on a screen
#: before the reader stops reading.
MAX_METRICS_PER_KIND = 3

#: How many query tasks to chart before the reader picks. A workload can have a
#: dozen queries, and a chart with a dozen lines is a chart nobody reads. The
#: rest stay one click away.
MAX_DEFAULT_QUERY_TASKS = 4


def metrics_for_kind(kind: str, available) -> list[str]:
    """The metrics to chart for a kind, given what the reports carry."""
    present = set(available)
    chosen = [m for m in METRICS_BY_KIND.get(kind, []) if m in present]
    headline = [m for m in chosen if m != "error_rate"][:MAX_METRICS_PER_KIND - 1]
    if "error_rate" in chosen:
        headline.append("error_rate")
    return headline or chosen[:MAX_METRICS_PER_KIND]


def classify(task: str) -> str:
    """Sort a task into indexing, query or lifecycle."""
    name = task.lower()
    if name in LIFECYCLE_TASKS:
        return KIND_LIFECYCLE
    if any(hint in name for hint in _INDEXING_HINTS):
        return KIND_INDEXING
    return KIND_QUERY


def classify_all(tasks) -> dict:
    """Map every task to its kind."""
    return {task: classify(task) for task in tasks}


def pick_default_tasks(available: list[str], *, preferred: Iterable[str] | None = None,
                       featured: Iterable[str] = ()) -> list[str]:
    """The tasks to chart before the reader picks.

    ``preferred`` is the curated list -- from reportr.yaml, or from the
    workload's own hint -- and wins outright when it names anything present.
    Someone who has looked at the workload knows better than a name heuristic.

    Without one, the fallback is every indexing task plus the first few
    queries, in the order the report lists them. Lifecycle operations are left
    out entirely: a create-collection latency says nothing about Solr. A
    workload with a dozen queries would otherwise open as a dozen overlapping
    lines, which is the noise this exists to avoid -- the rest stay one click
    away in the task picker.

    ``featured`` tasks are always on: a task singled out for its own chart is
    not one to open the page hiding.
    """
    present = list(available)
    curated = [t for t in (preferred or []) if t in present]
    if not curated:
        indexing = [t for t in present if classify(t) == KIND_INDEXING]
        queries = [t for t in present if classify(t) == KIND_QUERY]
        curated = indexing + queries[:MAX_DEFAULT_QUERY_TASKS]

    chosen = list(curated)
    for task in featured:
        if task in present and task not in chosen:
            chosen.append(task)
    return chosen or present
