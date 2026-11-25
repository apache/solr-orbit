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
"""Building the site from stored reports."""

import json

import pytest

from solrorbit.tools.reportr import builder
from solrorbit.tools.reportr import config as config_module


@pytest.fixture
def built(storage, tmp_path):
    config = config_module.load(None, overrides={
        "storage.path": str(storage), "site.out": str(tmp_path / "site")})
    return builder.build(config), tmp_path / "site"


class TestOutput:
    def test_reads_every_report(self, built):
        result, _ = built
        assert result.reports_read == 3
        assert result.reports_charted == 3
        assert result.points > 0

    def test_writes_the_app_shell(self, built):
        _, site = built
        for name in ("index.html", "app.js", "style.css", "vendor/echarts.min.js"):
            assert (site / name).exists(), f"{name} missing from the site"

    def test_the_shell_ships_inside_reportr(self):
        # Updating the tool updates the site; there is no separate frontend build.
        assert (builder.SITE_DIR / "index.html").exists()
        assert (builder.SITE_DIR / "vendor" / "echarts.min.js").exists()

    def test_writes_a_data_file_per_workload(self, built):
        _, site = built
        assert (site / "data" / "nyc_taxis.json").exists()

    def test_the_catalogue_lists_the_workloads(self, built):
        _, site = built
        index = json.loads((site / "data" / "index.json").read_text())
        assert [w["name"] for w in index["workloads"]] == ["nyc_taxis"]
        assert index["workloads"][0]["runs"] == 3

    def test_copies_each_plotted_report_for_click_through(self, built):
        # Copied rather than linked, so the site is self-contained and needs no
        # bucket exposure.
        _, site = built
        copied = sorted(p.name for p in (site / "reports").glob("*.json"))
        assert copied == ["run-aaa111.json", "run-bbb222.json", "run-ccc333.json"]

    def test_a_copied_report_is_the_whole_report(self, built, storage):
        _, site = built
        copied = json.loads((site / "reports" / "run-aaa111.json").read_text())
        assert "launchr" in copied and "results" in copied


class TestWorkloadPayload:
    @pytest.fixture
    def payload(self, built):
        _, site = built
        return json.loads((site / "data" / "nyc_taxis.json").read_text())

    def test_points_are_ordered_by_version_date(self, payload):
        entry = [s for s in payload["series"] if s["task"] == "index"][0]
        dates = [p["x"] for p in entry["points"]]
        assert dates == sorted(dates)
        assert dates[0].startswith("2025-07-24")

    def test_every_version_is_present(self, payload):
        entry = [s for s in payload["series"] if s["task"] == "index"][0]
        assert {p["solr_version"] for p in entry["points"]} == {"9.9.0", "9.10.1", "9.11.0"}

    def test_tasks_are_classified(self, payload):
        kinds = payload["task_kinds"]
        assert kinds["index"] == "indexing"
        assert kinds["match-all"] == "query"
        assert kinds["create-collection"] == "lifecycle"

    def test_default_tasks_exclude_lifecycle(self, payload):
        assert "create-collection" not in payload["default_tasks"]
        assert "index" in payload["default_tasks"]

    def test_metrics_are_chosen_per_kind(self, payload):
        assert payload["metrics_by_kind"]["indexing"][0] == "throughput.mean"
        assert payload["metrics_by_kind"]["query"][0].startswith("service_time")

    def test_lines_carry_a_readable_label(self, payload):
        label = next(iter(payload["lines"].values()))["label"]
        assert "local-docker" in label and "default-1s1r" in label

    def test_one_line_for_one_configuration(self, payload):
        assert len(payload["lines"]) == 1


class TestSkipping:
    def test_a_failed_report_is_counted_but_not_charted(self, storage, tmp_path, make_report):
        failed = make_report(run_id="run-bad", status="failed")
        path = storage / "runs" / "nyc_taxis" / "2026-10-15" / "run-bad" / "results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(failed))

        config = config_module.load(None, overrides={
            "storage.path": str(storage), "site.out": str(tmp_path / "site")})
        result = builder.build(config)
        assert result.reports_read == 4
        assert result.reports_charted == 3
        assert any("run-bad" in reason for reason in result.skipped)

    def test_unparseable_json_is_skipped_not_fatal(self, storage, tmp_path):
        path = storage / "runs" / "nyc_taxis" / "2026-10-15" / "run-junk" / "results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json")
        config = config_module.load(None, overrides={
            "storage.path": str(storage), "site.out": str(tmp_path / "site")})
        result = builder.build(config)
        assert result.reports_charted == 3
        assert any("not valid JSON" in reason for reason in result.skipped)

    def test_an_empty_storage_still_produces_a_site(self, tmp_path):
        config = config_module.load(None, overrides={
            "storage.path": str(tmp_path / "nothing"), "site.out": str(tmp_path / "site")})
        result = builder.build(config)
        assert result.points == 0
        assert (tmp_path / "site" / "index.html").exists()


class TestSeparateWorkloads:
    def test_each_workload_gets_its_own_file(self, storage, tmp_path, make_report):
        other = make_report(run_id="run-geo", workload="geonames")
        path = storage / "runs" / "geonames" / "2026-10-15" / "run-geo" / "results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(other))

        config = config_module.load(None, overrides={
            "storage.path": str(storage), "site.out": str(tmp_path / "site")})
        result = builder.build(config)
        assert result.workloads == ["geonames", "nyc_taxis"]
        assert (tmp_path / "site" / "data" / "geonames.json").exists()


class TestWorkloadDescription:
    """Where the page's "about this workload" paragraph comes from."""

    def _payload(self, storage, tmp_path, overrides=None):
        config = config_module.load(None, overrides={
            "storage.path": str(storage), "site.out": str(tmp_path / "site")})
        if overrides:
            config.data["workloads"] = overrides
        builder.build(config)
        return json.loads((tmp_path / "site" / "data" / "nyc_taxis.json").read_text())

    def test_comes_from_the_workload_itself(self, storage, tmp_path, make_report):
        # Declared in the workloads repo, carried through by Solr Orbit. reportr
        # should not need to know anything about nyc_taxis to say what it is.
        for path in storage.glob("runs/*/*/*/results.json"):
            report = json.loads(path.read_text())
            report["workload-description"] = "Taxi rides in New York in 2015"
            path.write_text(json.dumps(report))
        assert self._payload(storage, tmp_path)["description"] == "Taxi rides in New York in 2015"

    def test_the_config_can_override_it(self, storage, tmp_path):
        for path in storage.glob("runs/*/*/*/results.json"):
            report = json.loads(path.read_text())
            report["workload-description"] = "the workload's own words"
            path.write_text(json.dumps(report))
        payload = self._payload(storage, tmp_path,
                                {"nyc_taxis": {"description": "the operator's words"}})
        assert payload["description"] == "the operator's words"

    def test_a_report_without_one_simply_has_none(self, storage, tmp_path):
        # Reports written before Solr Orbit carried the field, and workloads
        # that never declared it. The page hides the block rather than apologise.
        assert self._payload(storage, tmp_path)["description"] is None


class TestFeaturedTasks:
    def test_the_config_promotes_a_task_to_its_own_chart(self, storage, tmp_path):
        config = config_module.load(None, overrides={
            "storage.path": str(storage), "site.out": str(tmp_path / "site")})
        config.data["workloads"] = {"nyc_taxis": {"featured_tasks": ["index"]}}
        builder.build(config)
        payload = json.loads((tmp_path / "site" / "data" / "nyc_taxis.json").read_text())
        assert payload["featured_tasks"] == ["index"]
        assert "index" in payload["default_tasks"], "a featured task must not open hidden"

    def test_a_featured_task_the_reports_lack_is_dropped(self, storage, tmp_path):
        config = config_module.load(None, overrides={
            "storage.path": str(storage), "site.out": str(tmp_path / "site")})
        config.data["workloads"] = {"nyc_taxis": {"featured_tasks": ["not-a-task"]}}
        builder.build(config)
        payload = json.loads((tmp_path / "site" / "data" / "nyc_taxis.json").read_text())
        assert payload["featured_tasks"] == []


class TestWhatTheSitePublishes:
    """The published copy of a report is not the stored one."""

    @staticmethod
    def stored(tmp_path, reports):
        root = tmp_path / "store"
        for index, report in enumerate(reports):
            path = root / "runs" / "nyc_taxis" / "2026-10-04" / f"run-{index:06d}" / "results.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(report), encoding="utf-8")
        config = config_module.load(None, overrides={
            "storage.path": str(root), "site.out": str(tmp_path / "site")})
        return builder.build(config), tmp_path / "site"

    def test_a_copied_report_carries_nothing_about_the_machine_that_ran_it(self, tmp_path,
                                                                           make_report):
        # The site reads neither field, and a publicly hosted site should not
        # carry an interpreter path under someone's home directory or the
        # hostname of a lab cluster.
        report = make_report(run_id="run-000000")
        report["launchr"]["benchmark"]["command"] = ["/home/ci/.venv/bin/python", "-m", "solrorbit"]
        report["launchr"]["solr"]["endpoints"] = ["http://solr-lab.internal:8983"]
        _, site = self.stored(tmp_path, [report])
        text = (site / "reports" / "run-000000.json").read_text(encoding="utf-8")
        assert "/home/ci" not in text and "solr-lab.internal" not in text

    def test_a_report_from_a_newer_schema_is_skipped_not_fatal(self, tmp_path, make_report):
        # One such report in a mixed bucket used to abort the whole build:
        # SchemaTooNew is not a LaunchrError, so cli.py did not catch it either.
        newer = make_report(run_id="run-000001", version="9.10.0",
                            timestamp="2026-09-01T00:00:00Z")
        newer["launchr"]["schema_version"] = 99
        result, _ = self.stored(tmp_path, [make_report(run_id="run-000000"), newer])
        assert result.reports_charted == 1
        assert any("schema_version 99" in reason for reason in result.skipped)

    def test_non_finite_numbers_never_reach_a_json_file(self, tmp_path, make_report):
        # json.loads accepts NaN and json.dumps writes it back, but it is not
        # JSON: the browser's fetch().json() then refuses the whole file.
        report = make_report(run_id="run-000000")
        for operation in report["results"]["op_metrics"]:
            for value in operation.values():
                if isinstance(value, dict) and "mean" in value:
                    value["mean"] = float("nan")

        def refuse(constant):
            raise ValueError(f"not JSON: {constant}")

        _, site = self.stored(tmp_path, [report])
        for path in (site / "data" / "nyc_taxis.json", site / "reports" / "run-000000.json"):
            json.loads(path.read_text(encoding="utf-8"), parse_constant=refuse)
