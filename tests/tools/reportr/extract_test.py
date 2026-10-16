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
"""Turning an enriched report into plottable points.

The two behaviours that matter: tolerate a metric a report does not carry, and
refuse a schema this code does not understand.
"""

import pytest

from solrorbit.tools.reportr import extract


class TestMetricKeys:
    @pytest.mark.parametrize("stat,expected", [
        ("p50", "50_0"), ("p99", "99_0"), ("p99_9", "99_9"), ("p100", "100_0"),
        ("mean", "mean"), ("median", "median"), ("min", "min"),
    ])
    def test_percentiles_use_solr_orbits_spelling(self, stat, expected):
        assert extract.percentile_key(stat) == expected

    def test_parse_splits_family_and_stat(self):
        assert extract.parse_metric("service_time.p99") == ("service_time", "99_0")

    def test_a_metric_without_a_dot_is_a_scalar(self):
        assert extract.parse_metric("error_rate") == ("error_rate", None)


class TestExtract:
    def test_pulls_the_requested_metric(self, enriched_report):
        points = extract.extract(enriched_report, ["throughput.mean"])
        assert points
        index = [p for p in points if p.task == "index"][0]
        assert index.value > 0
        assert index.unit == "docs/s"

    def test_x_is_the_version_timestamp_not_the_run_date(self, make_report):
        report = make_report(version="9.9.0", timestamp="2025-07-24T00:00:00Z")
        point = extract.extract(report, ["throughput.mean"])[0]
        assert (point.x.year, point.x.month, point.x.day) == (2025, 7, 24)

    def test_carries_the_provenance_a_tooltip_needs(self, make_report):
        point = extract.extract(make_report(run_id="run-xyz"), ["throughput.mean"])[0]
        assert point.run_id == "run-xyz"
        assert point.timestamp_source == "apache-releases"
        assert point.commit
        assert point.test_mode is True
        assert point.workload_revision == "a4684f1"

    def test_a_missing_metric_is_skipped_not_an_error(self, enriched_report):
        # Which percentiles exist depends on how many samples the run produced.
        points = extract.extract(enriched_report, ["service_time.p99_99"])
        assert points == []

    def test_a_missing_metric_does_not_lose_the_others(self, enriched_report):
        points = extract.extract(enriched_report, ["service_time.p99_99", "throughput.mean"])
        assert {p.metric for p in points} == {"throughput.mean"}

    def test_scalar_metrics(self, enriched_report):
        points = extract.extract(enriched_report, ["error_rate"])
        assert points and all(p.metric == "error_rate" for p in points)

    def test_tasks_can_be_restricted(self, enriched_report):
        points = extract.extract(enriched_report, ["throughput.mean"], tasks=["index"])
        assert {p.task for p in points} == {"index"}

    def test_unlisted_tasks_means_every_task(self, enriched_report):
        points = extract.extract(enriched_report, ["throughput.mean"])
        assert len({p.task for p in points}) > 1


class TestWhatIsNotCharted:
    def test_a_failed_run_is_skipped(self, make_report):
        assert extract.extract(make_report(status="failed"), ["throughput.mean"]) == []

    def test_a_report_without_a_launchr_block_is_skipped(self, enriched_report):
        del enriched_report["launchr"]
        assert extract.extract(enriched_report, ["throughput.mean"]) == []

    def test_a_report_without_results_is_skipped(self, enriched_report):
        enriched_report["results"] = {}
        assert extract.extract(enriched_report, ["throughput.mean"]) == []

    def test_a_report_with_no_timestamp_cannot_be_placed(self, enriched_report):
        enriched_report["launchr"]["solr"]["version_timestamp"] = None
        assert extract.extract(enriched_report, ["throughput.mean"]) == []

    def test_a_newer_schema_is_refused_rather_than_misread(self, enriched_report):
        enriched_report["launchr"]["schema_version"] = extract.SUPPORTED_SCHEMA_VERSION + 1
        with pytest.raises(extract.SchemaTooNew, match="Upgrade Solr Orbit"):
            extract.extract(enriched_report, ["throughput.mean"])

    def test_the_current_schema_is_accepted(self, enriched_report):
        enriched_report["launchr"]["schema_version"] = extract.SUPPORTED_SCHEMA_VERSION
        assert extract.extract(enriched_report, ["throughput.mean"])


class TestLineIdentity:
    def test_groups_by_where_and_how_it_ran(self, make_report):
        block = make_report(profile="ec2-3node", cluster_config="big")["launchr"]
        line = extract.line_of(block)
        assert line.profile == "ec2-3node"
        assert line.cluster_config == "big"
        assert line.version_kind == "release"

    def test_a_laptop_run_is_a_different_line_from_ec2(self, make_report):
        a = extract.line_of(make_report(profile="local-docker")["launchr"])
        b = extract.line_of(make_report(profile="ec2-3node")["launchr"])
        assert a.id != b.id

    def test_branches_are_different_lines(self, make_report):
        a = extract.line_of(make_report(kind="snapshot", branch="main")["launchr"])
        b = extract.line_of(make_report(kind="snapshot", branch="branch_9x")["launchr"])
        assert a.id != b.id
        assert a.label.startswith("main")

    def test_test_mode_does_not_split_a_line(self, make_report):
        # Charted like any other run; surfaced in the tooltip instead.
        a = extract.line_of(make_report(test_mode=True)["launchr"])
        b = extract.line_of(make_report(test_mode=False)["launchr"])
        assert a.id == b.id

    def test_workload_revision_does_not_split_a_line(self, make_report):
        # A workload change gets an annotation, so the trend stays continuous.
        a = extract.line_of(make_report(revision="aaa")["launchr"])
        b = extract.line_of(make_report(revision="bbb")["launchr"])
        assert a.id == b.id

    def test_the_id_is_filesystem_and_url_safe(self, make_report):
        line = extract.line_of(make_report(branch="feature/odd name")["launchr"])
        assert "/" not in line.id and " " not in line.id


class TestIntrospection:
    def test_lists_the_tasks_a_report_carries(self, enriched_report):
        assert "index" in extract.tasks_in(enriched_report)

    def test_lists_the_metrics_a_report_could_supply(self, enriched_report):
        available = extract.metrics_in(enriched_report)
        assert "throughput.mean" in available
        assert "error_rate" in available
        assert any(m.startswith("service_time.p") for m in available)

    def test_percentile_keys_are_rendered_readably(self, enriched_report):
        available = extract.metrics_in(enriched_report)
        assert not any("_0" in m for m in available), "50_0 should render as p50"


class TestWorkloadHints:
    """A workload can ask for how it is presented, through the meta block Solr
    Orbit already merges onto every operation."""

    def test_a_report_with_no_hints_asks_for_nothing(self, enriched_report):
        assert extract.hints(enriched_report) == {
            "description": None, "featured": [], "default": []}

    def test_a_task_can_ask_for_a_chart_of_its_own(self, enriched_report):
        ops = enriched_report["results"]["op_metrics"]
        ops[0]["meta"] = {"reportr.chart": "own"}
        assert extract.hints(enriched_report)["featured"] == [ops[0]["task"]]

    def test_any_other_chart_value_is_not_a_promotion(self, enriched_report):
        enriched_report["results"]["op_metrics"][0]["meta"] = {"reportr.chart": "shared"}
        assert extract.hints(enriched_report)["featured"] == []

    def test_a_task_can_ask_to_be_on_by_default(self, enriched_report):
        ops = enriched_report["results"]["op_metrics"]
        ops[1]["meta"] = {"reportr.default": True}
        assert extract.hints(enriched_report)["default"] == [ops[1]["task"]]

    def test_the_workload_can_describe_itself(self, enriched_report):
        # Workload-level meta_data reaches every operation, so the first wins.
        for op in enriched_report["results"]["op_metrics"]:
            op["meta"] = {"reportr.description": "  165M taxi rides.  "}
        assert extract.hints(enriched_report)["description"] == "165M taxi rides."

    def test_json_and_yaml_spellings_of_true_both_count(self, enriched_report):
        ops = enriched_report["results"]["op_metrics"]
        ops[0]["meta"] = {"reportr.default": "yes"}
        ops[1]["meta"] = {"reportr.default": "false"}
        assert extract.hints(enriched_report)["default"] == [ops[0]["task"]]

    def test_meta_that_is_not_a_mapping_is_ignored(self, enriched_report):
        enriched_report["results"]["op_metrics"][0]["meta"] = "nonsense"
        assert extract.hints(enriched_report)["featured"] == []

    def test_the_workloads_own_description_field_is_used(self, enriched_report):
        enriched_report["workload-description"] = "  Taxi rides in New York in 2015  "
        assert extract.hints(enriched_report)["description"] == "Taxi rides in New York in 2015"

    def test_a_fuller_paragraph_in_meta_wins_over_the_command_line_label(self, enriched_report):
        # The description field is specified as under 80 characters for CLI use.
        enriched_report["workload-description"] = "Taxi rides in New York in 2015"
        for op in enriched_report["results"]["op_metrics"]:
            op["meta"] = {"reportr.description": "165 million rides, and what they exercise."}
        assert extract.hints(enriched_report)["description"].startswith("165 million")


class TestWhatATaskIsMeasuredOn:
    """A query held at a fixed request rate says nothing through its
    throughput: that number is the rate that was asked for."""

    def test_a_throttled_task_is_read_as_latency(self, enriched_report):
        op = enriched_report["results"]["op_metrics"][0]
        op["schedule"] = {"target_throughput": 3.0, "target_throughput_unit": "ops/s"}
        assert extract.measure_of(op) == extract.MEASURE_LATENCY

    def test_an_unthrottled_task_is_read_as_throughput(self, enriched_report):
        op = enriched_report["results"]["op_metrics"][0]
        op["schedule"] = {"target_throughput": None, "clients": 8}
        assert extract.measure_of(op) == extract.MEASURE_THROUGHPUT

    def test_a_report_without_a_schedule_falls_back_to_latency(self, enriched_report):
        # Reports written before Solr Orbit recorded it. Latency is the safe
        # reading: it is meaningful either way.
        op = enriched_report["results"]["op_metrics"][0]
        op.pop("schedule", None)
        assert extract.measure_of(op) == extract.MEASURE_LATENCY

    def test_measures_maps_every_task(self, enriched_report):
        found = extract.measures(enriched_report)
        tasks = [op["task"] for op in enriched_report["results"]["op_metrics"]]
        assert set(found) == set(tasks)


class TestTaskNotes:
    def test_a_task_can_record_how_it_is_set_up(self, enriched_report):
        ops = enriched_report["results"]["op_metrics"]
        ops[0]["meta"] = {"reportr.note": "  json.facet, not the legacy component  "}
        assert extract.notes(enriched_report) == {
            ops[0]["task"]: "json.facet, not the legacy component"}

    def test_a_task_without_a_note_is_absent(self, enriched_report):
        assert extract.notes(enriched_report) == {}
