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
"""Grouping points into the series a chart draws."""

from datetime import datetime

import pytest

from solrorbit.tools.reportr import series
from solrorbit.tools.reportr.models import DataPoint, LineIdentity

LINE_A = LineIdentity("release", None, "local-docker", "default-1s1r", None)
LINE_B = LineIdentity("release", None, "ec2-3node", "default-3s2r", None)


def point(task="index", metric="throughput.mean", value=1.0, day=1, line=LINE_A,
          revision="r1", unit="docs/s"):
    return DataPoint(workload="w", task=task, metric=metric, value=value, unit=unit,
                     x=datetime(2026, 1, day), line=line, solr_version="9.11.0",
                     run_id=f"run-{day}", workload_revision=revision)


class TestGroup:
    def test_one_series_per_task_and_metric(self):
        grouped = series.group([
            point(task="index", metric="throughput.mean"),
            point(task="index", metric="error_rate"),
            point(task="match-all", metric="throughput.mean"),
        ])
        assert {(s.task, s.metric) for s in grouped} == {
            ("index", "throughput.mean"), ("index", "error_rate"),
            ("match-all", "throughput.mean"),
        }

    def test_lines_share_a_series(self):
        grouped = series.group([point(line=LINE_A), point(line=LINE_B)])
        assert len(grouped) == 1
        assert len(grouped[0].points) == 2

    def test_points_are_emitted_in_time_order(self):
        grouped = series.group([point(day=3, value=3), point(day=1, value=1), point(day=2, value=2)])
        assert [p["y"] for p in grouped[0].as_json()["points"]] == [1, 2, 3]

    def test_the_unit_survives_a_point_that_lacks_one(self):
        grouped = series.group([point(unit=""), point(unit="docs/s")])
        assert grouped[0].unit == "docs/s"


class TestInventory:
    def test_lines_are_first_seen_order(self):
        found = series.lines([point(line=LINE_B), point(line=LINE_A), point(line=LINE_B)])
        assert list(found) == [LINE_B.id, LINE_A.id]

    def test_tasks_and_metrics(self):
        points = [point(task="index", metric="throughput.mean"),
                  point(task="range", metric="error_rate")]
        assert series.tasks(points) == ["index", "range"]
        assert series.metrics(points) == ["throughput.mean", "error_rate"]


class TestDefaultTasks:
    def test_indexing_comes_first(self):
        chosen = series.pick_default_tasks(["create-collection", "match-all", "index"])
        assert chosen[0] == "index"

    def test_skips_setup_and_teardown(self):
        # A create-collection latency tells nobody anything about Solr.
        chosen = series.pick_default_tasks(
            ["delete-collection", "create-collection", "check-cluster-health", "range"])
        assert "create-collection" not in chosen
        assert "range" in chosen

    def test_falls_back_when_everything_is_boring(self):
        assert series.pick_default_tasks(["create-collection"]) == ["create-collection"]

    def test_caps_the_number_of_queries(self):
        # A dozen overlapping query lines is the noise this avoids.
        queries = [f"query-{i}" for i in range(12)]
        chosen = series.pick_default_tasks(["index"] + queries)
        assert chosen[0] == "index"
        assert len(chosen) == 1 + series.MAX_DEFAULT_QUERY_TASKS

    def test_every_indexing_task_is_kept(self):
        chosen = series.pick_default_tasks(["index", "index-append", "match-all"])
        assert "index" in chosen and "index-append" in chosen


class TestRevisionAnnotations:
    def test_marks_where_the_workload_revision_changed(self):
        changes = series.revision_changes([
            point(day=1, revision="aaa"), point(day=2, revision="aaa"),
            point(day=3, revision="bbb"),
        ])
        assert len(changes) == 1
        assert changes[0]["from"] == "aaa" and changes[0]["to"] == "bbb"
        assert changes[0]["x"].startswith("2026-01-03")

    def test_no_change_means_no_annotation(self):
        assert series.revision_changes([point(day=1), point(day=2)]) == []

    def test_lines_are_tracked_separately(self):
        changes = series.revision_changes([
            point(day=1, revision="aaa", line=LINE_A),
            point(day=2, revision="bbb", line=LINE_A),
            point(day=1, revision="zzz", line=LINE_B),
            point(day=2, revision="zzz", line=LINE_B),
        ])
        assert [c["line"] for c in changes] == [LINE_A.id]

    def test_a_missing_revision_does_not_fabricate_a_change(self):
        assert series.revision_changes([point(day=1, revision=None), point(day=2, revision="aaa")]) == []


class TestClassification:
    """Charting by what a task does is how the page stays readable."""

    @pytest.mark.parametrize("task", ["index", "index-append", "bulk-index", "update-docs"])
    def test_indexing_tasks(self, task):
        assert series.classify(task) == series.KIND_INDEXING

    @pytest.mark.parametrize("task", ["match-all", "range", "date_histogram_facet", "term"])
    def test_query_tasks(self, task):
        assert series.classify(task) == series.KIND_QUERY

    @pytest.mark.parametrize("task", ["create-collection", "delete-collection",
                                      "check-cluster-health", "optimize", "refresh-after-index"])
    def test_lifecycle_tasks(self, task):
        assert series.classify(task) == series.KIND_LIFECYCLE

    def test_indexing_is_judged_on_throughput(self):
        chosen = series.metrics_for_kind(series.KIND_INDEXING,
                                         ["throughput.mean", "service_time.mean", "error_rate"])
        assert chosen[0] == "throughput.mean"

    def test_a_query_is_judged_on_service_time(self):
        # Which is why OpenSearch's published query dashboards filter to it.
        chosen = series.metrics_for_kind(series.KIND_QUERY,
                                         ["throughput.mean", "service_time.p99", "error_rate"])
        assert chosen[0] == "service_time.p99"

    def test_falls_back_when_a_percentile_is_absent(self):
        # A test-mode run has too few samples for p99.
        chosen = series.metrics_for_kind(series.KIND_QUERY, ["service_time.mean", "error_rate"])
        assert "service_time.mean" in chosen

    def test_never_charts_more_than_the_cap(self):
        everything = ["service_time.p99", "service_time.p90", "service_time.p50",
                      "service_time.mean", "error_rate"]
        assert len(series.metrics_for_kind(series.KIND_QUERY, everything)) <= series.MAX_METRICS_PER_KIND

    def test_error_rate_is_kept_last_when_present(self):
        chosen = series.metrics_for_kind(series.KIND_QUERY,
                                         ["service_time.p99", "service_time.p50", "error_rate"])
        assert chosen[-1] == "error_rate"

    def test_classify_all_maps_every_task(self):
        kinds = series.classify_all(["index", "range", "optimize"])
        assert kinds == {"index": "indexing", "range": "query", "optimize": "lifecycle"}


class TestQueryMetricPriority:
    def test_the_median_and_p90_lead_the_tail(self):
        # p99 of the stock 100 iterations is a single observation; p50 and p90
        # rest on enough samples to mean something, so they come first.
        order = series.METRICS_BY_KIND[series.KIND_QUERY]
        assert order.index("service_time.p50") < order.index("service_time.p99")
        assert order.index("service_time.p90") < order.index("service_time.p99")

    def test_the_tail_is_still_charted_when_a_run_carries_it(self):
        chosen = series.metrics_for_kind(series.KIND_QUERY, {
            "service_time.p50", "service_time.p90", "service_time.p99", "error_rate"})
        assert "service_time.p99" in series.METRICS_BY_KIND[series.KIND_QUERY]
        assert chosen[:2] == ["service_time.p50", "service_time.p90"]


class TestCuratedDefaultTasks:
    AVAILABLE = ["create-collection", "index", "match-all", "range", "facet", "sort"]

    def test_a_curated_list_wins_over_the_heuristic(self):
        chosen = series.pick_default_tasks(self.AVAILABLE, preferred=["range", "index"])
        assert chosen == ["range", "index"]

    def test_names_that_are_not_present_are_dropped(self):
        chosen = series.pick_default_tasks(self.AVAILABLE, preferred=["range", "gone"])
        assert chosen == ["range"]

    def test_a_curated_list_of_nothing_present_falls_back(self):
        chosen = series.pick_default_tasks(self.AVAILABLE, preferred=["nope"])
        assert "index" in chosen

    def test_a_featured_task_is_always_on(self):
        # Singling a task out for its own chart and then hiding it by default
        # would be a contradiction.
        chosen = series.pick_default_tasks(self.AVAILABLE, preferred=["index"], featured=["sort"])
        assert chosen == ["index", "sort"]

    def test_a_featured_task_is_not_duplicated(self):
        chosen = series.pick_default_tasks(self.AVAILABLE, preferred=["index"], featured=["index"])
        assert chosen == ["index"]


class TestNoteChanges:
    """A workload editing a task's note is the workload saying the thing it
    measures is no longer quite the same thing."""

    def points(self):
        return [point(task="range", day=d, revision="r1") for d in (1, 2, 3)]

    def test_marks_the_point_where_the_note_changed(self):
        notes = {"run-1": {"range": "legacy facets"},
                 "run-2": {"range": "legacy facets"},
                 "run-3": {"range": "json.facet"}}
        found = series.note_changes(self.points(), notes)
        assert len(found) == 1
        assert found[0]["task"] == "range"
        assert found[0]["text"] == "json.facet"
        assert found[0]["x"].startswith("2026-01-03")

    def test_an_unchanging_note_is_not_an_event(self):
        notes = {f"run-{d}": {"range": "json.facet"} for d in (1, 2, 3)}
        assert series.note_changes(self.points(), notes) == []

    def test_the_first_note_seen_is_not_a_change(self):
        # Otherwise every task with a note would be marked at its first run.
        notes = {"run-1": {"range": "json.facet"}}
        assert series.note_changes(self.points(), notes) == []

    def test_no_notes_at_all_is_quiet(self):
        assert series.note_changes(self.points(), {}) == []


class TestReleaseNotes:
    def points(self):
        return [point(day=1, value=1.0), point(day=5, value=2.0)]

    def test_lands_on_the_first_run_of_that_version(self):
        found = series.release_notes(self.points(), [
            {"version": "9.11.0", "text": "Fixes SOLR-12345.", "url": "https://example.invalid"}])
        assert len(found) == 1
        assert found[0]["x"].startswith("2026-01-01")
        assert found[0]["kind"] == "release"

    def test_a_version_nothing_was_benchmarked_at_is_skipped(self):
        # Better a missing marker than one floating at a guessed position.
        assert series.release_notes(self.points(), [
            {"version": "9.99.0", "text": "never ran"}]) == []

    def test_a_note_can_name_one_task(self):
        found = series.release_notes(self.points(), [
            {"version": "9.11.0", "text": "facet fix", "task": "range"}])
        assert found[0]["task"] == "range"
