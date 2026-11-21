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
"""Turn an enriched report into data points.

The report is Solr Orbit's ``test_run.json`` plus launchr's ``launchr`` block.
Everything a chart needs about *where* a point belongs comes from that block;
everything about *what* the number is comes from ``results.op_metrics``.

Two rules shape this module:

* **Be tolerant of missing metrics.** Which percentiles a report carries depends
  on ``--latency-percentiles`` and on how many samples the run produced -- a
  test-mode run may have ``50_0`` and ``100_0`` but no ``99_0``. A metric that is
  not there is skipped, never an error.
* **Be intolerant of a schema we do not understand.** A report whose
  ``schema_version`` is newer than this code is refused rather than
  mis-interpreted.
"""

import logging
import math
import re
from datetime import datetime, timezone
from typing import Iterable

from solrorbit.tools.reportr.models import DataPoint, LineIdentity

logger = logging.getLogger(__name__)

#: The newest ``launchr.schema_version`` this code understands.
SUPPORTED_SCHEMA_VERSION = 1

#: Metrics that are a plain number on the operation, not a family of statistics.
SCALAR_METRICS = {"error_rate": "", "duration": "s"}

#: The spread a charted metric came out of, as ``(low, high)`` statistics of the
#: same family. Solr Orbit reports these alongside the headline number and the
#: site drew none of it, so every point looked equally certain -- a mean
#: throughput whose sampling intervals ranged from 3k to 9k docs/s was the same
#: dot as one where every interval hit 4.7k. Pairs are only listed where both
#: ends mean something next to the number in the middle.
SPREAD_OF = {
    "throughput.mean": ("min", "max"),
    "throughput.median": ("min", "max"),
    "service_time.p90": ("50_0", "99_0"),
    "service_time.mean": ("50_0", "100_0"),
    "latency.p90": ("50_0", "99_0"),
    "latency.mean": ("50_0", "100_0"),
}

#: ``p99`` -> ``99_0``, ``p99_9`` -> ``99_9``. Solr Orbit spells percentile keys
#: with an underscore for the decimal point.
_PERCENTILE = re.compile(r"^p(?P<whole>\d+)(?:_(?P<frac>\d+))?$")


class SchemaTooNew(Exception):
    """A report was written by a newer launchr than this reportr understands."""


def percentile_key(stat: str) -> str:
    """Map a metric statistic to Solr Orbit's key spelling."""
    match = _PERCENTILE.match(stat)
    if not match:
        return stat
    return f"{match.group('whole')}_{match.group('frac') or '0'}"


def parse_metric(metric: str) -> tuple[str, str | None]:
    """Split ``service_time.p99`` into ``("service_time", "99_0")``.

    A metric with no dot is a scalar on the operation, e.g. ``error_rate``.
    """
    if "." not in metric:
        return metric, None
    family, stat = metric.split(".", 1)
    return family, percentile_key(stat)


def line_of(block: dict) -> LineIdentity:
    """Build the line identity for a report's launchr block."""
    solr = block.get("solr") or {}
    workload = block.get("workload") or {}
    cluster_config = block.get("cluster_config") or {}
    return LineIdentity(
        version_kind=str(solr.get("version_kind") or "unknown"),
        branch=solr.get("branch"),
        profile=str((block.get("infra") or {}).get("provisioning_profile") or "unknown"),
        cluster_config=str(cluster_config.get("name") or "unknown"),
        test_procedure=workload.get("test_procedure"),
    )


#: Where a workload's own one-line description lands in the report. Solr Orbit
#: reads it from ``workload.json``'s ``description`` field -- the workloads repo
#: is where it belongs, next to the thing it describes -- and writes it here.
#: The field is specified as a command-line label of under 80 characters, so a
#: workload wanting a fuller paragraph says so in its meta instead. Older
#: reports predate the field and simply have no description.
WORKLOAD_DESCRIPTION = "workload-description"

#: Further presentation hints a workload may carry, read from the ``meta`` block
#: Solr Orbit attaches to every operation. ``GlobalStatsCalculator`` merges
#: the workload's, the test procedure's, the operation's and the task's
#: ``meta_data`` into that one dict, so a workload declares these in its own
#: JSON and they arrive in every report without reportr knowing the workload:
#:
#: .. code-block:: json
#:
#:     {"name": "range", "operation": "range",
#:      "meta": {"reportr.chart": "own",
#:               "reportr.description": "Taxi rides, 165M rows of real data."}}
#:
#: They are hints, not orders: reportr.yaml overrides them, because the person
#: running the site knows which comparison this site is for.
HINT_DESCRIPTION = "reportr.description"
HINT_CHART = "reportr.chart"
HINT_DEFAULT = "reportr.default"

#: The value of ``reportr.chart`` that asks for a chart of this task alone.
CHART_OWN = "own"

#: A note the workload keeps about how a task is set up, e.g. which facet
#: implementation a query uses. reportr marks the point where the text changes:
#: the workload editing this note is the workload telling the chart that the
#: thing it measures is no longer quite the same thing.
HINT_NOTE = "reportr.note"

#: What a task is measured on. A task driven at a fixed request rate tells you
#: nothing through its throughput -- that number is the rate you asked for --
#: so it is judged on latency. A task with no target rate was pushed as hard as
#: it would go, and its throughput is the headline: queries per second.
MEASURE_THROUGHPUT = "throughput"
MEASURE_LATENCY = "latency"


def measure_of(operation: dict) -> str:
    """Whether this task's numbers are about speed or about volume."""
    schedule = operation.get("schedule")
    if not isinstance(schedule, dict):
        # Reports written before Solr Orbit recorded the schedule. Latency is
        # the safe reading: it is meaningful either way.
        return MEASURE_LATENCY
    target = schedule.get("target_throughput")
    return MEASURE_LATENCY if isinstance(target, (int, float)) else MEASURE_THROUGHPUT


def notes(report: dict) -> dict:
    """Each task's note about its own setup, where it has one."""
    found: dict[str, str] = {}
    for operation in ((report.get("results") or {}).get("op_metrics")) or []:
        meta = operation.get("meta")
        task = operation.get("task") or operation.get("operation")
        if task and isinstance(meta, dict) and meta.get(HINT_NOTE):
            found[str(task)] = str(meta[HINT_NOTE]).strip()
    return found


def measures(report: dict) -> dict:
    """Each task mapped to what it is measured on."""
    return {
        str(op.get("task") or op.get("operation")): measure_of(op)
        for op in ((report.get("results") or {}).get("op_metrics")) or []
        if op.get("task") or op.get("operation")
    }


def hints(report: dict) -> dict:
    """What the workload itself asks for, if anything.

    Returns ``description``, ``featured`` (tasks wanting their own chart) and
    ``default`` (tasks to chart before the reader picks). Absent hints come back
    as ``None`` and empty lists, which every caller treats as "decide for me".

    Both descriptions belong to the workload. ``reportr.description`` in its
    meta wins when present, because the ``description`` field is specified as a
    command-line label of under 80 characters -- fine as a fallback, thin as the
    paragraph at the top of a page.
    """
    operations = ((report.get("results") or {}).get("op_metrics")) or []
    declared = report.get(WORKLOAD_DESCRIPTION)
    fallback: str | None = str(declared).strip() or None if declared else None
    description: str | None = None
    featured: list[str] = []
    default: list[str] = []

    for operation in operations:
        meta = operation.get("meta")
        if not isinstance(meta, dict):
            continue
        task = operation.get("task") or operation.get("operation")
        if description is None and meta.get(HINT_DESCRIPTION):
            description = str(meta[HINT_DESCRIPTION]).strip() or None
        if not task:
            continue
        if str(meta.get(HINT_CHART) or "").lower() == CHART_OWN and task not in featured:
            featured.append(str(task))
        if _truthy(meta.get(HINT_DEFAULT)) and task not in default:
            default.append(str(task))

    return {"description": description or fallback, "featured": featured, "default": default}


def _truthy(value) -> bool:
    """YAML and JSON both reach here, so accept the spellings both produce."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "on"}


def extract(report: dict, metrics: Iterable[str], *, tasks: Iterable[str] | None = None,
            source: str | None = None) -> list[DataPoint]:
    """Extract the requested metrics from one enriched report.

    :param metrics: metric keys such as ``throughput.mean`` or ``error_rate``.
    :param tasks: restrict to these task names; ``None`` means every task.
    :param source: where the report came from, for log messages.
    """
    block = report.get("launchr")
    if not block:
        logger.debug("Skipping %s: no launchr block, so nothing places it on a timeline", source)
        return []

    version = int(block.get("schema_version") or 0)
    if version > SUPPORTED_SCHEMA_VERSION:
        raise SchemaTooNew(
            f"{source or 'report'} has launchr.schema_version {version}, but this reportr "
            f"understands at most {SUPPORTED_SCHEMA_VERSION}. Upgrade Solr Orbit."
        )

    if block.get("status") != "completed":
        logger.info("Skipping %s: status is %r", source, block.get("status"))
        return []

    operations = ((report.get("results") or {}).get("op_metrics")) or []
    if not operations:
        logger.info("Skipping %s: no op_metrics", source)
        return []

    when = _timestamp(block)
    if when is None:
        logger.warning("Skipping %s: no usable launchr.solr.version_timestamp", source)
        return []

    solr = block.get("solr") or {}
    workload_block = block.get("workload") or {}
    benchmark = block.get("benchmark") or {}
    line = line_of(block)
    wanted_tasks = set(tasks) if tasks else None
    metric_list = list(metrics)

    points: list[DataPoint] = []
    for operation in operations:
        task = operation.get("task") or operation.get("operation")
        if not task or (wanted_tasks is not None and task not in wanted_tasks):
            continue
        for metric in metric_list:
            found = _value_of(operation, metric)
            if found is None:
                continue
            value, unit = found
            low_high = spread_of(operation, metric)
            points.append(DataPoint(
                workload=str(report.get("workload") or workload_block.get("name") or "unknown"),
                task=str(task),
                metric=metric,
                value=float(value),
                unit=unit,
                x=when,
                line=line,
                solr_version=str(solr.get("version") or ""),
                run_id=str(block.get("run_id") or ""),
                timestamp_source=solr.get("version_timestamp_source"),
                timestamp_precision=solr.get("version_timestamp_precision"),
                commit=solr.get("commit"),
                test_mode=bool(benchmark.get("test_mode", False)),
                workload_revision=workload_block.get("revision"),
                low=low_high[0] if low_high else None,
                high=low_high[1] if low_high else None,
            ))
    return points


def spread_of(operation: dict, metric: str) -> tuple[float, float] | None:
    """The low and high of the distribution behind ``metric``, if reported.

    Absent statistics are not an error: which percentiles a run carries depends
    on how many samples it produced, and a run with one sample has no spread to
    show.
    """
    pair = SPREAD_OF.get(metric)
    if not pair:
        return None
    group = operation.get(parse_metric(metric)[0])
    if not isinstance(group, dict):
        return None
    low, high = (group.get(key) for key in pair)
    if not _finite(low) or not _finite(high):
        return None
    return (float(low), float(high)) if high > low else None


def _value_of(operation: dict, metric: str) -> tuple[float, str] | None:
    """Pull one metric out of an op_metrics entry, or None if absent."""
    family, stat = parse_metric(metric)
    if stat is None:
        value = operation.get(family)
        if not _finite(value):
            return None
        return float(value), SCALAR_METRICS.get(family, "")

    group = operation.get(family)
    if not isinstance(group, dict):
        return None
    value = group.get(stat)
    if not _finite(value):
        return None
    return float(value), str(group.get("unit") or "")


def _finite(value) -> bool:
    """A number the chart can draw.

    NaN and Infinity parse as floats and would be written back by json.dumps
    as bare NaN/Infinity, which is not JSON: the browser's fetch().json()
    then refuses the whole workload file, not just the offending point.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timestamp(block: dict) -> datetime | None:
    raw = (block.get("solr") or {}).get("version_timestamp")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Unparseable version_timestamp %r", raw)
        return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def tasks_in(report: dict) -> list[str]:
    """Every task name a report carries, in report order."""
    operations = ((report.get("results") or {}).get("op_metrics")) or []
    seen: list[str] = []
    for operation in operations:
        task = operation.get("task") or operation.get("operation")
        if task and task not in seen:
            seen.append(str(task))
    return seen


def metrics_in(report: dict) -> list[str]:
    """Every metric key a report could supply, for `reportr build --list-metrics`."""
    found: set[str] = set()
    for operation in ((report.get("results") or {}).get("op_metrics")) or []:
        for key, value in operation.items():
            if key in SCALAR_METRICS and isinstance(value, (int, float)):
                found.add(key)
            elif isinstance(value, dict):
                for stat in value:
                    if stat == "unit":
                        continue
                    found.add(f"{key}.{_pretty_stat(stat)}")
    return sorted(found)


def _pretty_stat(stat: str) -> str:
    """``99_0`` -> ``p99``, ``99_9`` -> ``p99_9``, ``mean`` -> ``mean``."""
    if not stat[0].isdigit():
        return stat
    whole, _, frac = stat.partition("_")
    return f"p{whole}" if frac in ("", "0") else f"p{whole}_{frac}"
