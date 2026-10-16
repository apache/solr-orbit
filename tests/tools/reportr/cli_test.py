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
"""The reportr command line."""

import json

import pytest

from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.reportr import cli
from solrorbit.tools.reportr import config as config_module


class TestBuild:
    def test_builds_and_reports_what_it_did(self, storage, tmp_path, capsys):
        code = cli.main(["build", "--local", str(storage), "--out", str(tmp_path / "site")])
        out = capsys.readouterr().out
        assert code == 0
        assert "nyc_taxis" in out
        assert "3 charted of 3 read" in out

    def test_local_is_shorthand_for_the_storage_path(self, storage, tmp_path):
        cli.main(["build", "--local", str(storage), "--out", str(tmp_path / "site")])
        assert (tmp_path / "site" / "data" / "nyc_taxis.json").exists()

    def test_metrics_can_be_overridden(self, storage, tmp_path):
        cli.main(["build", "--local", str(storage), "--out", str(tmp_path / "site"),
                  "--metrics", "error_rate"])
        payload = json.loads((tmp_path / "site" / "data" / "nyc_taxis.json").read_text())
        assert payload["metrics"] == ["error_rate"]

    def test_an_empty_storage_says_what_to_do(self, tmp_path, capsys):
        code = cli.main(["build", "--local", str(tmp_path / "empty"), "--out", str(tmp_path / "s")])
        assert code == 0
        assert "launchr run" in capsys.readouterr().out


class TestMetricsCommand:
    def test_lists_what_the_reports_could_chart(self, storage, capsys):
        code = cli.main(["metrics", "--local", str(storage)])
        out = capsys.readouterr().out
        assert code == 0
        assert "throughput.mean" in out
        assert "3/3" in out

    def test_marks_the_metrics_currently_charted(self, storage, capsys):
        cli.main(["metrics", "--local", str(storage)])
        assert "* currently charted" in capsys.readouterr().out

    def test_empty_storage(self, tmp_path, capsys):
        assert cli.main(["metrics", "--local", str(tmp_path / "empty")]) == 0
        assert "No reports" in capsys.readouterr().out


class TestTopLevel:
    def test_no_subcommand_prints_help(self, capsys):
        assert cli.main([]) == 2
        assert "usage:" in capsys.readouterr().out

    def test_version(self, capsys):
        assert cli.main(["version"]) == 0
        assert "reportr" in capsys.readouterr().out

    def test_a_bad_config_is_reported_without_a_traceback(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "reportr.yaml").write_text("nonsense: 1\n")
        monkeypatch.chdir(tmp_path)
        assert cli.main(["build"]) == 2
        assert "unknown top-level keys" in capsys.readouterr().err


class TestConfig:
    def test_defaults_work_with_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = config_module.load(None)
        assert config.storage_backend == "local"
        assert "throughput.mean" in config.metrics

    def test_a_cloud_backend_is_refused_for_now(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigError, match="local filesystem only"):
            config_module.load(None, overrides={"storage.backend": "s3"})

    def test_an_unlisted_workload_charts_every_task(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert config_module.load(None).tasks_for("anything") is None

    def test_a_listed_workload_is_curated(self, tmp_path, monkeypatch):
        (tmp_path / "reportr.yaml").write_text(
            "workloads:\n  nyc_taxis:\n    tasks: [index, range]\n")
        monkeypatch.chdir(tmp_path)
        assert config_module.load(None).tasks_for("nyc_taxis") == ["index", "range"]

    def test_the_repo_reportr_yaml_is_valid(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parents[3] / "reportr.yaml"
        assert repo.exists()
        assert config_module.load(repo).metrics
