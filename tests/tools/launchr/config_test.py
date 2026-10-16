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
"""Configuration loading: precedence, validation, and provenance."""

import os

import pytest
import yaml

from solrorbit.tools.launchr import config as config_module
from solrorbit.tools.launchr.errors import ConfigError


def write(tmp_path, document):
    path = tmp_path / "launchr.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


class TestPrecedence:
    def test_built_in_defaults_work_with_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = config_module.load(env={})
        assert config.storage_backend == "local"
        assert config.registry == "docker.io/library/solr"
        assert "local-docker" in config.profile_names

    def test_file_beats_built_in(self, tmp_path):
        path = write(tmp_path, {"registry": "ghcr.io/apache/solr"})
        assert config_module.load(path, env={}).registry == "ghcr.io/apache/solr"

    def test_env_beats_file(self, tmp_path):
        path = write(tmp_path, {"solr_versions": ["9.0.0"]})
        config = config_module.load(path, env={"SOLR_VERSIONS": "9.11.0,9.12.0"})
        assert config.solr_versions == ["9.11.0", "9.12.0"]

    def test_cli_beats_env(self, tmp_path):
        path = write(tmp_path, {"solr_versions": ["9.0.0"]})
        config = config_module.load(path, env={"SOLR_VERSIONS": "9.11.0"},
                                    overrides={"solr_versions": ["9.7.0"]})
        assert config.solr_versions == ["9.7.0"]

    def test_unset_cli_flag_does_not_clobber_the_file(self, tmp_path):
        path = write(tmp_path, {"registry": "ghcr.io/apache/solr"})
        config = config_module.load(path, env={}, overrides={"registry": None})
        assert config.registry == "ghcr.io/apache/solr"

    def test_empty_env_var_is_ignored(self, tmp_path):
        path = write(tmp_path, {"solr_versions": ["9.0.0"]})
        assert config_module.load(path, env={"SOLR_VERSIONS": ""}).solr_versions == ["9.0.0"]

    def test_nested_override_leaves_siblings_alone(self, tmp_path):
        path = write(tmp_path, {"storage": {"backend": "local", "path": "/tmp/x"}})
        config = config_module.load(path, env={}, overrides={"storage.path": "/tmp/y"})
        assert (config.storage_backend, config.storage_path) == ("local", "/tmp/y")

    def test_file_does_not_have_to_repeat_defaults(self, tmp_path):
        # A file naming only workloads still gets the default profile and config.
        path = write(tmp_path, {"workloads": [{"name": "nyc_taxis"}]})
        config = config_module.load(path, env={})
        assert config.default_profiles() == ["local-docker"]


class TestProvenance:
    def test_records_where_each_value_came_from(self, tmp_path):
        path = write(tmp_path, {"registry": "from-file"})
        config = config_module.load(path, env={"SOLR_VERSIONS": "9.11.0"},
                                    overrides={"storage.path": "./cli"})
        assert config.provenance.of("registry") == str(path)
        assert config.provenance.of("solr_versions") == "$SOLR_VERSIONS"
        assert config.provenance.of("storage.path") == "CLI flag"
        assert config.provenance.of("nightly_registry") == "built-in default"

    def test_describe_renders_every_value_with_its_source(self, tmp_path):
        config = config_module.load(write(tmp_path, {"registry": "x"}), env={})
        described = config.describe()
        assert "registry = 'x'" in described
        assert "built-in default" in described


class TestProfiles:
    def test_parses_a_profile(self, tmp_path):
        path = write(tmp_path, {"provisioning_profiles": {
            "p": {"provisioning": "local", "install_method": "docker", "nodes": 1, "port": 9000}}})
        profile = config_module.load(path, env={}).profile("p")
        assert (profile.provisioning, profile.install_method, profile.port) == ("local", "docker", 9000)

    def test_unknown_profile_lists_what_is_defined(self, tmp_path):
        config = config_module.load(write(tmp_path, {}), env={})
        with pytest.raises(ConfigError, match="local-docker"):
            config.profile("nope")

    def test_missing_provisioning_is_an_error(self, tmp_path):
        path = write(tmp_path, {"provisioning_profiles": {"p": {"install_method": "docker"}}})
        with pytest.raises(ConfigError, match="does not set 'provisioning'"):
            config_module.load(path, env={})

    def test_unknown_profile_key_is_an_error(self, tmp_path):
        # A silently ignored instance_type is exactly the kind of typo that
        # wastes a night of benchmarking.
        path = write(tmp_path, {"provisioning_profiles": {
            "p": {"provisioning": "local", "install_method": "docker", "instnace_type": "big"}}})
        with pytest.raises(ConfigError, match="unknown keys"):
            config_module.load(path, env={})

    def test_plugin_settings_live_under_options(self, tmp_path):
        path = write(tmp_path, {"provisioning_profiles": {
            "p": {"provisioning": "local", "install_method": "docker",
                  "options": {"anything": "goes"}}}})
        assert config_module.load(path, env={}).profile("p").options == {"anything": "goes"}

    def test_node_count_is_excluded_from_the_group_key(self, tmp_path):
        path = write(tmp_path, {"provisioning_profiles": {
            "two": {"provisioning": "local", "install_method": "docker", "nodes": 2},
            "three": {"provisioning": "local", "install_method": "docker", "nodes": 3}}})
        config = config_module.load(path, env={})
        assert config.profile("two").group_key == config.profile("three").group_key

    def test_differing_options_split_the_group(self, tmp_path):
        path = write(tmp_path, {"provisioning_profiles": {
            "a": {"provisioning": "local", "install_method": "docker", "options": {"x": 1}},
            "b": {"provisioning": "local", "install_method": "docker", "options": {"x": 2}}}})
        config = config_module.load(path, env={})
        assert config.profile("a").group_key != config.profile("b").group_key


class TestWorkloads:
    def test_bare_string_entry(self, tmp_path):
        path = write(tmp_path, {"workloads": ["nyc_taxis"]})
        workloads = config_module.load(path, env={}).workloads
        assert workloads[0].name == "nyc_taxis"
        assert workloads[0].test_procedures == (None,)

    def test_default_procedure_is_the_workloads_own(self, tmp_path):
        path = write(tmp_path, {"workloads": [{"name": "w"}]})
        assert config_module.load(path, env={}).workloads[0].test_procedures == (None,)

    def test_procedures_become_a_dimension(self, tmp_path):
        path = write(tmp_path, {"workloads": [{"name": "w", "test_procedures": ["a", "b"]}]})
        assert config_module.load(path, env={}).workloads[0].test_procedures == ("a", "b")

    def test_single_procedure_as_a_string(self, tmp_path):
        path = write(tmp_path, {"workloads": [{"name": "w", "test_procedures": "a"}]})
        assert config_module.load(path, env={}).workloads[0].test_procedures == ("a",)

    def test_env_var_gives_bare_names(self, tmp_path):
        config = config_module.load(write(tmp_path, {}), env={"LAUNCHR_WORKLOADS": "a,b"})
        assert [w.name for w in config.workloads] == ["a", "b"]

    def test_entry_without_a_name(self, tmp_path):
        path = write(tmp_path, {"workloads": [{"test_procedures": ["a"]}]})
        with pytest.raises(ConfigError, match="has no 'name'"):
            config_module.load(path, env={})


class TestValidation:
    def test_unknown_top_level_key(self, tmp_path):
        with pytest.raises(ConfigError, match="unknown top-level keys"):
            config_module.load(write(tmp_path, {"storge": {}}), env={})

    def test_default_profile_must_exist(self, tmp_path):
        path = write(tmp_path, {"defaults": {"provisioning": ["ghost"], "cluster_config": ["default-1s1r"]}})
        with pytest.raises(ConfigError, match="unknown profile 'ghost'"):
            config_module.load(path, env={})

    def test_default_cluster_config_must_exist(self, tmp_path):
        path = write(tmp_path, {"defaults": {"provisioning": ["local-docker"], "cluster_config": ["ghost"]}})
        with pytest.raises(ConfigError, match="unknown config 'ghost'"):
            config_module.load(path, env={})

    def test_bad_gc_is_caught_at_load_time(self, tmp_path):
        # Catching this at load means --dry-run catches it too, before any
        # infrastructure exists.
        path = write(tmp_path, {"cluster_configs": {"c": {"gc": "EpsilonGC"}},
                                "defaults": {"provisioning": ["local-docker"], "cluster_config": ["c"]}})
        with pytest.raises(ConfigError, match="Unknown gc"):
            config_module.load(path, env={})

    def test_aggregation_is_refused_with_an_explanation(self, tmp_path):
        # One iteration cannot be aggregated, and the invocation passes
        # --aggregate=false, so accepting this would put "aggregated: true" in
        # the report of a run that was not aggregated.
        path = write(tmp_path, {"benchmark": {"aggregate": True}})
        with pytest.raises(ConfigError, match="cannot aggregate"):
            config_module.load(path, env={})

    @pytest.mark.parametrize("key", ["password", "aws_secret_key", "api_key", "SOLR_TOKEN"])
    def test_credential_looking_keys_are_rejected(self, tmp_path, key):
        path = write(tmp_path, {"storage": {"backend": "local", "path": "/tmp", "options": {key: "x"}}})
        with pytest.raises(ConfigError, match="looks like a credential"):
            config_module.load(path, env={})

    def test_multi_iteration_is_refused_with_an_explanation(self, tmp_path):
        # Solr Orbit generates its own ids for iterations after the first, so
        # launchr cannot locate those reports yet.
        path = write(tmp_path, {"benchmark": {"iterations": 3}})
        with pytest.raises(ConfigError, match="supports 1"):
            config_module.load(path, env={})

    def test_zero_iterations(self, tmp_path):
        with pytest.raises(ConfigError, match="at least 1"):
            config_module.load(write(tmp_path, {"benchmark": {"iterations": 0}}), env={})

    def test_missing_config_file_is_an_error(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            config_module.load(tmp_path / "nope.yaml", env={})

    def test_malformed_yaml(self, tmp_path):
        path = tmp_path / "launchr.yaml"
        path.write_text("storage: {unclosed")
        with pytest.raises(ConfigError, match="Could not parse"):
            config_module.load(path, env={})

    def test_non_mapping_yaml(self, tmp_path):
        path = tmp_path / "launchr.yaml"
        path.write_text("- a\n- b\n")
        with pytest.raises(ConfigError, match="YAML mapping"):
            config_module.load(path, env={})

    def test_empty_file_is_fine(self, tmp_path):
        path = tmp_path / "launchr.yaml"
        path.write_text("")
        assert config_module.load(path, env={}).storage_backend == "local"


def test_repo_launchr_yaml_is_valid():
    """The checked-in launchr.yaml must load, since it is what a fresh checkout uses."""
    from pathlib import Path
    repo_config = Path(__file__).resolve().parents[3] / "launchr.yaml"
    assert repo_config.exists(), f"expected {repo_config} to exist"
    config = config_module.load(repo_config, env={})
    assert config.solr_versions, "the local-dev config should name some versions"
    assert config.workloads, "the local-dev config should name a workload"
    assert config.storage_backend == "local"


class TestDefaultStorageLocation:
    """A result store is the history of a machine's benchmarking, not an
    artifact of one shell session."""

    def test_defaults_under_solr_orbits_home(self, monkeypatch):
        monkeypatch.delenv("BENCHMARK_HOME", raising=False)
        monkeypatch.setattr(os.path, "expanduser", lambda p: "/home/someone" if p == "~" else p)
        assert config_module.default_storage_path() == "/home/someone/.solr-orbit/benchmark-results"

    def test_benchmark_home_moves_it(self, monkeypatch):
        # The same variable Solr Orbit already honours for everything it stores.
        monkeypatch.setenv("BENCHMARK_HOME", "/srv/orbit")
        assert config_module.default_storage_path() == "/srv/orbit/.solr-orbit/benchmark-results"

    def test_it_is_resolved_when_the_config_loads(self, monkeypatch):
        # Not frozen at import, or BENCHMARK_HOME would only work for whoever
        # set it before the first import.
        loaded = config_module.load(None, env={"BENCHMARK_HOME": "/srv/orbit"})
        assert loaded.storage_path == "/srv/orbit/.solr-orbit/benchmark-results"

    def test_it_is_not_the_working_directory(self, monkeypatch):
        # Running from somewhere else would silently start an empty history.
        monkeypatch.delenv("BENCHMARK_HOME", raising=False)
        loaded = config_module.load(None)
        assert not loaded.storage_path.startswith("./")
        assert ".solr-orbit" in loaded.storage_path


class TestStorageScheme:
    """An ``s3://`` path and ``storage.backend`` must agree, or say so."""

    def test_an_s3_path_selects_the_s3_backend(self, tmp_path):
        path = write(tmp_path, {"storage": {"path": "s3://solr-orbit/v1"}})
        config = config_module.load(path, env={})
        assert (config.storage_backend, config.storage_path) == ("s3", "s3://solr-orbit/v1")

    def test_the_inference_is_recorded_in_the_provenance(self, tmp_path):
        # validate-config prints where every value came from; an inferred one
        # must not claim to be a built-in default.
        path = write(tmp_path, {"storage": {"path": "s3://solr-orbit/v1"}})
        config = config_module.load(path, env={})
        assert "inferred" in config.provenance.of("storage.backend")

    def test_an_explicit_matching_backend_is_fine(self, tmp_path):
        path = write(tmp_path, {"storage": {"backend": "s3", "path": "s3://solr-orbit/v1"}})
        assert config_module.load(path, env={}).storage_backend == "s3"

    def test_a_contradiction_is_rejected(self, tmp_path):
        path = write(tmp_path, {"storage": {"backend": "local", "path": "s3://solr-orbit/v1"}})
        with pytest.raises(ConfigError, match="not both differently"):
            config_module.load(path, env={})

    def test_s3_backend_with_a_filesystem_path_is_rejected(self, tmp_path):
        path = write(tmp_path, {"storage": {"backend": "s3", "path": "/srv/results"}})
        with pytest.raises(ConfigError, match="not a s3 URI"):
            config_module.load(path, env={})

    def test_a_cli_override_can_switch_to_s3(self, tmp_path):
        path = write(tmp_path, {"storage": {"path": "/srv/results"}})
        config = config_module.load(path, env={}, overrides={"storage.path": "s3://solr-orbit/v1"})
        assert config.storage_backend == "s3"

    def test_options_round_trip(self, tmp_path):
        path = write(tmp_path, {
            "storage": {"path": "s3://solr-orbit/v1", "options": {"region": "eu-north-1"}},
        })
        assert config_module.load(path, env={}).storage_options == {"region": "eu-north-1"}

    def test_a_secret_in_storage_options_is_rejected(self, tmp_path):
        # The whole point of naming a profile is that the key never lands here.
        path = write(tmp_path, {
            "storage": {
                "path": "s3://solr-orbit/v1",
                "options": {"aws_secret_access_key": "AKIAnope"},
            },
        })
        with pytest.raises(ConfigError, match="looks like a credential"):
            config_module.load(path, env={})
