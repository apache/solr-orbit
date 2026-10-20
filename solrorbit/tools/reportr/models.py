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
"""The data model behind every chart.

A :class:`DataPoint` is one metric from one benchmark run, placed on the x-axis
by *when the Solr version was created* rather than when the benchmark ran. A
:class:`Series` is the points that belong on one line of one chart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class LineIdentity:
    """What makes two points belong on the same line.

    Deliberately *not* part of this: the run id, the hostname, and the workload
    revision -- a workload change gets an annotation rather than a new line, so
    the long-run trend stays continuous. ``test_mode`` is also excluded: a
    1000-document run is charted like any other and flagged in the tooltip.

    Deliberately *in* it: the profile and cluster config, so the site never
    silently compares a 3-node EC2 result against a laptop run; and the version
    kind and branch, so releases and nightlies of different branches do not
    share a line -- their timestamps come from different clocks.
    """

    version_kind: str
    branch: str | None
    profile: str
    cluster_config: str
    test_procedure: str | None

    @property
    def id(self) -> str:
        """A stable, URL-safe identifier."""
        parts = (
            self.version_kind,
            self.branch or "-",
            self.profile,
            self.cluster_config,
            self.test_procedure or "default",
        )
        return "__".join(_slug(p) for p in parts)

    @property
    def label(self) -> str:
        """A short human rendering for a chart legend."""
        head = self.branch or self.version_kind
        parts = [head, self.profile, self.cluster_config]
        if self.test_procedure:
            parts.append(self.test_procedure)
        return " · ".join(parts)


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in str(value))


@dataclass(frozen=True)
class DataPoint:
    """One metric from one run, ready to plot."""

    workload: str
    task: str
    metric: str
    value: float
    unit: str
    x: datetime
    line: LineIdentity
    solr_version: str
    run_id: str
    #: Which source placed this point on the timeline, and how precisely. Two
    #: points from different sources are not measuring the same clock.
    timestamp_source: str | None = None
    timestamp_precision: str | None = None
    commit: str | None = None
    #: A 1000-document run. Charted normally, surfaced in the tooltip.
    test_mode: bool = False
    #: Shown as an annotation where it changes: a workload change moves numbers
    #: as surely as a Solr change does.
    workload_revision: str | None = None
    #: The spread this number came out of, when the report carries one -- the
    #: slowest and fastest sampling interval behind a mean throughput, the
    #: median and the tail behind a p90. A point drawn without it looks exactly
    #: as certain as a point drawn with a wide one.
    low: float | None = None
    high: float | None = None

    def as_json(self) -> dict[str, Any]:
        payload = {
            "x": _iso(self.x),
            "y": self.value,
            "line": self.line.id,
            "run_id": self.run_id,
            "solr_version": self.solr_version,
            "commit": self.commit,
            "timestamp_source": self.timestamp_source,
            "timestamp_precision": self.timestamp_precision,
            "test_mode": self.test_mode,
            "workload_revision": self.workload_revision,
        }
        if self.low is not None and self.high is not None and self.high > self.low:
            payload["lo"] = self.low
            payload["hi"] = self.high
        return payload


@dataclass
class Series:
    """The points for one task and metric, across every line."""

    task: str
    metric: str
    unit: str
    points: list[DataPoint] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "metric": self.metric,
            "unit": self.unit,
            "points": [p.as_json() for p in sorted(self.points, key=lambda p: p.x)],
        }


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")
