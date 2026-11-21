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
"""Build the static site.

Reads every stored report, extracts the configured metrics, and writes:

``index.html``, ``app.js``, ``style.css``, ``vendor/echarts.min.js``
    The single-page app, copied verbatim from this package.
``data/index.json``
    The workload catalogue the app loads first.
``data/<workload>.json``
    Series, lines and annotations for one workload's charts.
``reports/<run-id>.json``
    The full enriched report behind each plotted point, so clicking a point can
    show what produced it. Copied into the site rather than linked, so the site
    is self-contained and works from any file server with no bucket exposure.
"""

import json
import logging
import math
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solrorbit.tools.reportr import extract, series
from solrorbit.tools.reportr.config import ReportrConfig
from solrorbit.tools.reportr.models import DataPoint

logger = logging.getLogger(__name__)

SITE_DIR = Path(__file__).parent / "site"


@dataclass
class BuildResult:
    """What a build produced, for the CLI to report."""

    out_dir: Path
    workloads: list[str] = field(default_factory=list)
    reports_read: int = 0
    reports_charted: int = 0
    points: int = 0
    skipped: list[str] = field(default_factory=list)

    def describe(self) -> str:
        lines = [
            f"site:      {self.out_dir}",
            f"workloads: {', '.join(self.workloads) or '(none)'}",
            f"reports:   {self.reports_charted} charted of {self.reports_read} read",
            f"points:    {self.points}",
        ]
        if self.skipped:
            lines.append(f"skipped:   {len(self.skipped)}")
            for reason in self.skipped[:5]:
                lines.append(f"             {reason}")
            if len(self.skipped) > 5:
                lines.append(f"             … and {len(self.skipped) - 5} more")
        return "\n".join(lines)


def find_reports(storage_path: Path) -> list[Path]:
    """Every stored report, in a stable order."""
    return sorted(storage_path.glob("runs/*/*/*/results.json"))


def build(config: ReportrConfig) -> BuildResult:
    """Build the whole site. Returns what it produced."""
    storage = Path(config.storage_path).expanduser()
    out = config.out_dir
    result = BuildResult(out_dir=out)

    reports = find_reports(storage)
    if not reports:
        logger.warning("No reports found under %s/runs/ -- the site will be empty", storage)

    by_workload: dict[str, list[DataPoint]] = {}
    charted: dict[str, Path] = {}
    #: What each workload says about itself, newest report winning, so a
    #: workload that starts declaring hints takes effect on the next run.
    hints: dict[str, dict] = {}
    #: What each task is measured on, and what each run said about its setup.
    measures: dict[str, dict] = {}
    notes_by_run: dict[str, dict] = {}

    for path in reports:
        result.reports_read += 1
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            result.skipped.append(f"{path.name}: not valid JSON ({exc})")
            continue

        workload = str(report.get("workload") or "unknown")
        try:
            points = extract.extract(
                report, config.metrics, tasks=config.tasks_for(workload), source=str(path),
            )
        except extract.SchemaTooNew as exc:
            # One report from a newer launchr must not abort a build over a
            # whole bucket: SchemaTooNew is not a LaunchrError, so cli.py does
            # not catch it either.
            result.skipped.append(f"{path.parent.name}: {exc}")
            continue
        if not points:
            result.skipped.append(f"{path.parent.name}: no plottable points")
            continue

        hints[workload] = extract.hints(report)
        measures.setdefault(workload, {}).update(extract.measures(report))
        by_workload.setdefault(workload, []).extend(points)
        result.reports_charted += 1
        result.points += len(points)
        run_id = points[0].run_id or path.parent.name
        charted[run_id] = path
        notes_by_run[run_id] = extract.notes(report)

    _write_site(out, config, by_workload, charted, hints, measures, notes_by_run)
    result.workloads = sorted(by_workload)
    return result


def _write_site(out: Path, config: ReportrConfig, by_workload: dict[str, list[DataPoint]],
                charted: dict[str, Path], hints: dict[str, dict] | None = None,
                measures: dict[str, dict] | None = None,
                notes_by_run: dict[str, dict] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _copy_shell(out)

    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for workload, points in sorted(by_workload.items()):
        hint = (hints or {}).get(workload) or {}
        _write_json(data_dir / f"{_slug(workload)}.json", workload_payload(
            workload, points,
            # Config beats the workload's own hint in every case: whoever runs
            # the site decides what the site is for.
            description=config.description_for(workload) or hint.get("description"),
            default_tasks=config.default_tasks_for(workload) or hint.get("default"),
            featured_tasks=config.featured_tasks_for(workload) or hint.get("featured"),
            measures=(measures or {}).get(workload),
            notes_by_run=notes_by_run or {},
            release_notes=config.annotations_for(workload),
        ))

    _write_json(data_dir / "index.json", {
        "title": config.title,
        "generated_at": _now(),
        "metrics": config.metrics,
        "workloads": [
            {
                "name": workload,
                "file": f"data/{_slug(workload)}.json",
                "runs": len({p.run_id for p in points}),
                "points": len(points),
                "latest": max(p.x for p in points).strftime("%Y-%m-%d"),
            }
            for workload, points in sorted(by_workload.items())
        ],
    })

    reports_dir = out / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    for run_id, path in sorted(charted.items()):
        _write_json(reports_dir / f"{_slug(run_id)}.json",
                    _publishable(json.loads(path.read_text(encoding="utf-8"))))


def workload_payload(workload: str, points: list[DataPoint], *,
                     description: str | None = None,
                     default_tasks: list[str] | None = None,
                     featured_tasks: list[str] | None = None,
                     measures: dict[str, str] | None = None,
                     notes_by_run: dict[str, dict] | None = None,
                     release_notes: list[dict] | None = None) -> dict[str, Any]:
    """The data file for one workload's charts."""
    all_tasks = series.tasks(points)
    available = set(series.metrics(points))
    featured = [t for t in (featured_tasks or []) if t in all_tasks]
    return {
        "workload": workload,
        "generated_at": _now(),
        "description": description,
        "tasks": all_tasks,
        "task_kinds": series.classify_all(all_tasks),
        # A featured task gets a chart to itself rather than another line in a
        # shared one, so a reader tracking, say, JSON range facets can link
        # straight to it.
        "featured_tasks": featured,
        "default_tasks": series.pick_default_tasks(
            all_tasks, preferred=default_tasks, featured=featured),
        # Which metrics suit which kind of task, intersected with what the
        # reports actually carry.
        "metrics_by_kind": {
            kind: series.metrics_for_kind(kind, available)
            for kind in series.METRICS_BY_KIND
        },
        "metrics": series.metrics(points),
        "lines": {
            line_id: {
                "label": line.label,
                "version_kind": line.version_kind,
                "branch": line.branch,
                "profile": line.profile,
                "cluster_config": line.cluster_config,
                "test_procedure": line.test_procedure,
            }
            for line_id, line in series.lines(points).items()
        },
        # What a task is judged on: a query held at a fixed request rate is
        # judged on latency, one pushed as hard as it would go on throughput.
        "task_measures": measures or {},
        # Three sources, one shape: the workload changed, a task's setup
        # changed, or somebody wrote down what a release did.
        "annotations": (series.revision_changes(points)
                        + series.note_changes(points, notes_by_run or {})
                        + series.release_notes(points, release_notes or [])),
        "series": [s.as_json() for s in series.group(points)],
    }


def _copy_shell(out: Path) -> None:
    """Copy the SPA. It ships inside reportr, so updating the tool updates the site."""
    for item in sorted(SITE_DIR.iterdir()):
        target = out / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copyfile(item, target)


def _publishable(report: dict) -> dict:
    """The report as it goes onto the site.

    ``launchr.benchmark.command`` is the argv of the machine that ran the
    benchmark -- an interpreter path under someone's home directory, the
    workload checkout, the target hosts -- and ``launchr.solr.endpoints`` is
    where its Solr listened, which for a preconfigured profile is a lab
    hostname. The site reads neither, and a publicly hosted site should not
    carry either.
    """
    block = report.get("launchr")
    if isinstance(block, dict):
        if isinstance(block.get("benchmark"), dict):
            block["benchmark"].pop("command", None)
        if isinstance(block.get("solr"), dict):
            block["solr"].pop("endpoints", None)
    return _without_non_finite(report)


def _without_non_finite(value):
    """NaN and Infinity are not JSON, and fetch().json() refuses the file."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _without_non_finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_non_finite(v) for v in value]
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in str(value))
