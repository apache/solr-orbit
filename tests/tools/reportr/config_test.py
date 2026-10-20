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
"""Per-workload presentation settings in reportr.yaml."""

import pytest
import yaml

from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.reportr import config as config_module


def write(tmp_path, data) -> str:
    path = tmp_path / "reportr.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


class TestWorkloadSettings:
    def test_an_unlisted_workload_decides_everything_itself(self, tmp_path):
        config = config_module.load(write(tmp_path, {"workloads": {}}))
        assert config.tasks_for("nyc_taxis") is None
        assert config.description_for("nyc_taxis") is None
        assert config.default_tasks_for("nyc_taxis") is None
        assert config.featured_tasks_for("nyc_taxis") is None

    def test_reads_every_per_workload_key(self, tmp_path):
        config = config_module.load(write(tmp_path, {"workloads": {"nyc_taxis": {
            "description": "  165M taxi rides.  ",
            "tasks": ["index", "range", "match-all"],
            "default_tasks": ["index", "range"],
            "featured_tasks": ["range"],
        }}}))
        assert config.description_for("nyc_taxis") == "165M taxi rides."
        assert config.tasks_for("nyc_taxis") == ["index", "range", "match-all"]
        assert config.default_tasks_for("nyc_taxis") == ["index", "range"]
        assert config.featured_tasks_for("nyc_taxis") == ["range"]

    def test_the_default_metrics_chart_the_median_and_p90(self):
        # Both have to be extracted before the chart curation can prefer them.
        assert "service_time.p50" in config_module.DEFAULT_METRICS
        assert "service_time.p90" in config_module.DEFAULT_METRICS


class TestRejectsNonsense:
    def test_a_misspelled_workload_key_is_an_error(self, tmp_path):
        # Silently ignoring it would leave the operator wondering why the
        # setting they wrote does nothing.
        with pytest.raises(ConfigError, match="featured"):
            config_module.load(write(tmp_path, {
                "workloads": {"nyc_taxis": {"featured": ["range"]}}}))

    def test_a_workload_entry_must_be_a_mapping(self, tmp_path):
        with pytest.raises(ConfigError, match="must be a mapping"):
            config_module.load(write(tmp_path, {"workloads": {"nyc_taxis": ["range"]}}))

    def test_a_task_list_must_be_a_list(self, tmp_path):
        with pytest.raises(ConfigError, match="must be a list"):
            config_module.load(write(tmp_path, {
                "workloads": {"nyc_taxis": {"featured_tasks": "range"}}}))

    def test_featuring_a_task_the_site_leaves_out_is_an_error(self, tmp_path):
        # It would never appear, and nothing would say why.
        with pytest.raises(ConfigError, match="leaves out"):
            config_module.load(write(tmp_path, {"workloads": {"nyc_taxis": {
                "tasks": ["index"], "featured_tasks": ["range"]}}}))

    def test_defaulting_to_a_task_the_site_leaves_out_is_an_error(self, tmp_path):
        with pytest.raises(ConfigError, match="leaves out"):
            config_module.load(write(tmp_path, {"workloads": {"nyc_taxis": {
                "tasks": ["index"], "default_tasks": ["range"]}}}))


class TestShippedConfig:
    def test_the_repository_config_loads(self, repo_config_path):
        # It is the one a reader copies, so it has to be valid.
        config = config_module.load(repo_config_path)
        assert config.description_for("nyc_taxis")
        assert config.featured_tasks_for("nyc_taxis")


class TestAnnotations:
    def test_reads_a_release_note(self, tmp_path):
        config = config_module.load(write(tmp_path, {"annotations": [
            {"version": "9.11.0", "text": "Fixes SOLR-12345.",
             "url": "https://example.invalid", "task": "range"}]}))
        found = config.annotations_for("nyc_taxis")
        assert len(found) == 1 and found[0]["task"] == "range"

    def test_a_note_can_be_scoped_to_one_workload(self, tmp_path):
        config = config_module.load(write(tmp_path, {"annotations": [
            {"version": "9.11.0", "text": "only here", "workload": "geonames"}]}))
        assert config.annotations_for("geonames")
        assert config.annotations_for("nyc_taxis") == []

    def test_a_note_without_a_version_has_nowhere_to_go(self, tmp_path):
        with pytest.raises(ConfigError, match="version"):
            config_module.load(write(tmp_path, {"annotations": [{"text": "orphan"}]}))

    def test_a_note_without_text_explains_nothing(self, tmp_path):
        with pytest.raises(ConfigError, match="text"):
            config_module.load(write(tmp_path, {"annotations": [{"version": "9.11.0"}]}))

    def test_a_misspelled_annotation_key_is_an_error(self, tmp_path):
        with pytest.raises(ConfigError, match="unknown keys"):
            config_module.load(write(tmp_path, {"annotations": [
                {"version": "9.11.0", "text": "x", "lnik": "typo"}]}))


class TestDefaultStorageLocation:
    def test_reads_where_launchr_writes(self, monkeypatch):
        # Otherwise `reportr build` with no arguments would look at an empty
        # directory and report an empty site.
        from solrorbit.tools.launchr import config as launchr_config
        monkeypatch.setenv("BENCHMARK_HOME", "/srv/orbit")
        assert config_module.load(None).storage_path == launchr_config.default_storage_path()

    def test_it_is_not_the_working_directory(self, monkeypatch):
        monkeypatch.delenv("BENCHMARK_HOME", raising=False)
        loaded = config_module.load(None)
        assert ".solr-orbit" in loaded.storage_path
        assert not loaded.storage_path.startswith("./")
