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
"""The command line.

``--dry-run`` gets the most attention: it is the command a reviewer uses to
check a matrix expansion without burning benchmark time, so it must be correct,
offline and fast.
"""

import pytest
import yaml

from solrorbit.tools.launchr import cli


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A directory with a minimal launchr.yaml, as the current directory."""
    document = {
        "solr_versions": ["9.0.0", "9.11.0"],
        "workloads": ["nyc_taxis"],
        "storage": {"backend": "local", "path": str(tmp_path / "results")},
    }
    (tmp_path / "launchr.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestDryRun:
    def test_prints_the_plan_and_runs_nothing(self, workspace, capsys):
        assert cli.main(["run", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "2 cell(s) in 1 provisioning group(s)" in out
        assert "Nothing was run (--dry-run)." in out

    def test_shows_the_exact_solr_orbit_command(self, workspace, capsys):
        cli.main(["run", "--dry-run"])
        out = capsys.readouterr().out
        assert "python -m solrorbit.benchmark run" in out
        assert "--pipeline=benchmark-only" in out

    def test_shows_the_environment_a_cluster_config_applies(self, workspace, capsys):
        # Reviewing a cluster-config translation is the point.
        cli.main(["run", "--dry-run"])
        assert "SOLR_HEAP=4g" in capsys.readouterr().out

    def test_shows_every_endpoint_of_a_preconfigured_cluster(self, tmp_path, monkeypatch, capsys):
        # build_argv targets every configured URL, so showing only the first
        # would make the printed command a different command from the real one.
        document = {
            "solr_versions": ["9.11.0"],
            "workloads": ["nyc_taxis"],
            "storage": {"backend": "local", "path": str(tmp_path / "results")},
            "provisioning_profiles": {"lab": {
                "provisioning": "preconfigured", "install_method": "none",
                "solr_url": "http://a.example:8983,http://b.example:8983",
            }},
            "defaults": {"provisioning": ["lab"]},
        }
        (tmp_path / "launchr.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert cli.main(["run", "--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "a.example:8983" in out
        assert "b.example:8983" in out

    def test_shows_where_results_would_go(self, workspace, capsys):
        cli.main(["run", "--dry-run"])
        assert "storage: local at" in capsys.readouterr().out

    def test_makes_no_network_calls(self, workspace, capsys, monkeypatch):
        # Pure config expansion: usable in CI with no connectivity.
        import requests

        def forbidden(*args, **kwargs):
            raise AssertionError("--dry-run must not touch the network")

        monkeypatch.setattr(requests, "get", forbidden)
        assert cli.main(["run", "--dry-run"]) == 0

    def test_writes_nothing_to_storage(self, workspace):
        cli.main(["run", "--dry-run"])
        assert not (workspace / "results").exists()

    def test_cli_versions_override_the_file(self, workspace, capsys):
        cli.main(["run", "--dry-run", "--versions", "9.7.0"])
        out = capsys.readouterr().out
        assert "1 cell(s)" in out and "9.7.0" in out

    def test_test_mode_appears_in_the_command(self, workspace, capsys):
        cli.main(["run", "--dry-run", "--test-mode"])
        assert "--test-mode" in capsys.readouterr().out


class TestValidateConfig:
    def test_prints_values_with_provenance(self, workspace, capsys):
        assert cli.main(["validate-config"]) == 0
        out = capsys.readouterr().out
        assert "launchr.yaml" in out
        assert "built-in default" in out
        assert "Configuration is valid." in out

    def test_reports_a_bad_config_without_a_traceback(self, tmp_path, monkeypatch, capsys):
        (tmp_path / "launchr.yaml").write_text(yaml.safe_dump({"nonsense": 1}))
        monkeypatch.chdir(tmp_path)
        assert cli.main(["validate-config"]) == 2
        assert "unknown top-level keys" in capsys.readouterr().err


class TestList:
    def test_plugins(self, capsys):
        assert cli.main(["list", "plugins"]) == 0
        out = capsys.readouterr().out
        assert "ec2, local, preconfigured" in out
        assert "docker, docker-ssh, none" in out
        assert "local, s3" in out

    def test_profiles_marks_the_defaults(self, workspace, capsys):
        cli.main(["list", "profiles"])
        assert "local-docker (default)" in capsys.readouterr().out

    def test_cluster_configs_show_what_they_apply(self, workspace, capsys):
        cli.main(["list", "cluster-configs"])
        out = capsys.readouterr().out
        assert "SOLR_HEAP=4g" in out
        assert "num_shards=1" in out

    def test_all_covers_everything(self, workspace, capsys):
        cli.main(["list"])
        out = capsys.readouterr().out
        assert "plugins" in out and "provisioning profiles" in out and "cluster configs" in out


class TestTopLevel:
    def test_no_subcommand_prints_help(self, capsys):
        assert cli.main([]) == 2
        assert "usage:" in capsys.readouterr().out

    def test_version(self, capsys):
        assert cli.main(["version"]) == 0
        assert "launchr" in capsys.readouterr().out

    def test_bad_version_timestamp_is_reported_cleanly(self, workspace, capsys):
        assert cli.main(["run", "--version-timestamp", "not-a-date"]) == 2
        assert "not an ISO-8601 timestamp" in capsys.readouterr().err

    def test_explicit_config_path(self, tmp_path, monkeypatch, capsys):
        config = tmp_path / "custom.yaml"
        config.write_text(yaml.safe_dump({"solr_versions": ["9.11.0"], "workloads": ["w"]}))
        monkeypatch.chdir(tmp_path)
        assert cli.main(["run", "--dry-run", "-c", str(config)]) == 0
        assert "1 cell(s)" in capsys.readouterr().out


class TestSolrPortOverride:
    """`--solr-port` exists because assuming 8983 is hostile to a Solr developer."""

    def test_overrides_the_profile_port(self, workspace, capsys):
        cli.main(["run", "--dry-run", "--solr-port", "19983"])
        assert "target-hosts=127.0.0.1:19983" in capsys.readouterr().out

    def test_default_is_the_profile_port(self, workspace, capsys):
        cli.main(["run", "--dry-run"])
        assert "target-hosts=127.0.0.1:8983" in capsys.readouterr().out

    def test_provenance_records_the_flag(self, workspace):
        from solrorbit.tools.launchr import config as config_module

        config = config_module.load("launchr.yaml", env={})
        config_module.apply_solr_port(config, 19983)
        assert config.profile("local-docker").port == 19983
        assert config.provenance.of("provisioning_profiles.local-docker.port") == "CLI flag"

    def test_applies_to_every_profile(self, tmp_path, monkeypatch):
        import yaml

        from solrorbit.tools.launchr import config as config_module

        document = {
            "solr_versions": ["9.11.0"],
            "workloads": ["w"],
            "provisioning_profiles": {
                "a": {"provisioning": "local", "install_method": "docker", "port": 8983},
                "b": {"provisioning": "local", "install_method": "docker", "port": 9000},
            },
            "defaults": {"provisioning": ["a"], "cluster_config": ["default-1s1r"]},
        }
        path = tmp_path / "launchr.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        config = config_module.load(path, env={})
        config_module.apply_solr_port(config, 19983)
        assert config.profile("a").port == 19983
        assert config.profile("b").port == 19983
