# SPDX-License-Identifier: Apache-2.0
#
# Modifications by Apache Solr contributors; see git log for details.
# Licensed under the Apache License, Version 2.0.
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.
# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import os
import re
import unittest.mock as mock

import pytest

from solrorbit import config, exceptions, test_run_orchestrator
from solrorbit.builder.solr_provisioner import SolrProvisioner
from solrorbit.utils import opts


@pytest.fixture
def running_in_docker():
    os.environ["BENCHMARK_RUNNING_IN_DOCKER"] = "true"
    # just yield anything to signal the fixture is ready
    yield True
    del os.environ["BENCHMARK_RUNNING_IN_DOCKER"]


@pytest.fixture
def benchmark_only_pipeline():
    test_pipeline_name = "benchmark-only"
    original = test_run_orchestrator.pipelines[test_pipeline_name]
    pipeline = test_run_orchestrator.Pipeline(test_pipeline_name, "Pipeline intended for unit-testing", mock.Mock())
    yield pipeline
    # restore prior pipeline!
    test_run_orchestrator.pipelines[test_pipeline_name] = original


@pytest.fixture
def unittest_pipeline():
    pipeline = test_run_orchestrator.Pipeline("unit-test-pipeline", "Pipeline intended for unit-testing", mock.Mock())
    yield pipeline
    del test_run_orchestrator.pipelines[pipeline.name]


def test_finds_available_pipelines():
    expected = [
        ["benchmark-only", "Assumes an already running search engine instance, runs a benchmark and publishes results"],
        ["from-sources", "Builds Solr from source (git clone + Gradle assemble), provisions it locally, "
                         "runs a benchmark, and tears down."],
        ["from-distribution", "Downloads a Solr distribution, provisions it locally, runs a benchmark, and tears down."],
        ["docker", "Starts Solr via Docker, runs a benchmark, and removes the container on teardown."],
    ]

    assert expected == test_run_orchestrator.available_pipelines()


def test_prevents_running_an_unknown_pipeline():
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "system", "test_run.id", "28a032d1-0b03-4579-ad2a-c65316f126e9")
    cfg.add(config.Scope.benchmark, "test_run", "pipeline", "invalid")
    cfg.add(config.Scope.benchmark, "builder", "distribution.version", "5.0.0")

    with pytest.raises(
            exceptions.SystemSetupError,
            match=r"Unknown pipeline \[invalid]. List the available pipelines with [\S]+? list pipelines."):
        test_run_orchestrator.run(cfg)


def test_passes_benchmark_only_pipeline_in_docker(running_in_docker, benchmark_only_pipeline):
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "system", "test_run.id", "28a032d1-0b03-4579-ad2a-c65316f126e9")
    cfg.add(config.Scope.benchmark, "test_run", "pipeline", "benchmark-only")

    test_run_orchestrator.run(cfg)

    benchmark_only_pipeline.target.assert_called_once_with(cfg)


def test_fails_without_benchmark_only_pipeline_in_docker(running_in_docker, unittest_pipeline):
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "system", "test_run.id", "28a032d1-0b03-4579-ad2a-c65316f126e9")
    cfg.add(config.Scope.benchmark, "test_run", "pipeline", "unit-test-pipeline")

    with pytest.raises(
            exceptions.SystemSetupError,
            match=re.escape(
                "Only the [benchmark-only] pipeline is supported by the Docker image.\n"
                "Add --pipeline=benchmark-only in your arguments and try again.\n"
                "For more details read the docs for the benchmark-only pipeline in "
                "https://solr.apache.org/guide/\n"
            )):
        test_run_orchestrator.run(cfg)


def test_runs_a_known_pipeline(unittest_pipeline):
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "system", "test_run.id", "28a032d1-0b03-4579-ad2a-c65316f126e9")
    cfg.add(config.Scope.benchmark, "test_run", "pipeline", "unit-test-pipeline")
    cfg.add(config.Scope.benchmark, "builder", "distribution.version", "")

    test_run_orchestrator.run(cfg)

    unittest_pipeline.target.assert_called_once_with(cfg)

def test_runs_a_default_pipeline(benchmark_only_pipeline):
    # with no pipeline specified, should default to benchmark-only
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "system", "test_run.id", "28a032d1-0b03-4579-ad2a-c65316f126e9")

    test_run_orchestrator.run(cfg)

    benchmark_only_pipeline.target.assert_called_once_with(cfg)


def test_check_cloud_mode_skipped_when_allow_unsupported_user_managed():
    # --allow-unsupported-user-managed must bypass the check entirely, without touching the network
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "client", "hosts", ["localhost:8983"])
    cfg.add(config.Scope.benchmark, "solr", "allow.unsupported.user.managed", True)

    with mock.patch("solrorbit.client.SolrAdminClient") as admin_client:
        test_run_orchestrator._check_cloud_mode(cfg)

    admin_client.assert_not_called()


def test_check_cloud_mode_raises_for_standalone_solr():
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "client", "hosts", opts.TargetHosts("localhost:8983"))
    cfg.add(config.Scope.benchmark, "solr", "allow.unsupported.user.managed", False)

    with mock.patch("solrorbit.client.SolrAdminClient") as admin_client:
        admin_client.return_value.is_cloud_mode.return_value = False
        with pytest.raises(exceptions.SystemSetupError, match="not running in SolrCloud"):
            test_run_orchestrator._check_cloud_mode(cfg)


TEST_RUN_ID = "28a032d1-0b03-4579-ad2a-c65316f126e9"


def _provisioned_cfg(root_dir, devices, params=None):
    cfg = config.Config()
    cfg.add(config.Scope.benchmark, "system", "test_run.id", TEST_RUN_ID)
    cfg.add(config.Scope.benchmark, "node", "root.dir", str(root_dir))
    cfg.add(config.Scope.benchmark, "telemetry", "devices", devices)
    cfg.add(config.Scope.benchmark, "telemetry", "params", params or {})
    cfg.add(config.Scope.benchmark, "builder", "distribution.version", "9.10.1")
    cfg.add(config.Scope.benchmark, "solr", "install_dir", str(root_dir / "install"))
    cfg.add(config.Scope.benchmark, "solr", "cache_dir", str(root_dir / "cache"))
    return cfg


def test_create_jvm_telemetry_devices_returns_only_enabled_devices(tmp_path):
    cfg = _provisioned_cfg(tmp_path, ["gc", "jfr", "segment-stats"])

    devices = test_run_orchestrator._create_jvm_telemetry_devices(cfg)

    assert sorted(device.command for device in devices) == ["gc", "jfr"]
    expected_log_root = os.path.join(str(tmp_path), "test-runs", TEST_RUN_ID, "telemetry")
    assert all(device.log_root == expected_log_root for device in devices)


def test_create_jvm_telemetry_devices_returns_nothing_without_telemetry(tmp_path):
    cfg = _provisioned_cfg(tmp_path, [])

    assert test_run_orchestrator._create_jvm_telemetry_devices(cfg) == []


def test_jvm_telemetry_devices_add_their_flags_to_solr_opts(tmp_path):
    cfg = _provisioned_cfg(tmp_path, ["gc", "jfr", "jit"], params={"gc-log-config": "gc*=debug"})
    devices = test_run_orchestrator._create_jvm_telemetry_devices(cfg)

    provisioner = SolrProvisioner(cache_dir=str(tmp_path / "cache"), telemetry_devices=devices)
    solr_opts = provisioner._build_env()["SOLR_OPTS"]

    log_root = os.path.join(str(tmp_path), "test-runs", TEST_RUN_ID, "telemetry")
    assert f"-Xlog:gc*=debug:file={os.path.join(log_root, 'gc.log')}" in solr_opts
    assert f"filename={os.path.join(log_root, 'profile.jfr')}" in solr_opts
    assert f"-XX:LogFile={os.path.join(log_root, 'jit.log')}" in solr_opts


@mock.patch("solrorbit.test_run_orchestrator.run_test")
@mock.patch("solrorbit.test_run_orchestrator.set_default_hosts")
@mock.patch("solrorbit.test_run_orchestrator._load_cluster_config", return_value=None)
@mock.patch("solrorbit.test_run_orchestrator.SolrProvisioner")
def test_from_distribution_passes_jvm_telemetry_devices(provisioner_class, load_cluster_config, set_default_hosts, run_test, tmp_path):
    cfg = _provisioned_cfg(tmp_path, ["gc", "jit"])

    test_run_orchestrator.solr_from_distribution(cfg)

    devices = provisioner_class.call_args.kwargs["telemetry_devices"]
    assert sorted(device.command for device in devices) == ["gc", "jit"]
    run_test.assert_called_once_with(cfg, external=True)


@mock.patch("solrorbit.test_run_orchestrator.run_test")
@mock.patch("solrorbit.test_run_orchestrator.set_default_hosts")
@mock.patch("solrorbit.test_run_orchestrator._load_cluster_config", return_value=None)
@mock.patch("solrorbit.test_run_orchestrator.SolrProvisioner")
@mock.patch("solrorbit.test_run_orchestrator.tarfile.open")
@mock.patch("solrorbit.test_run_orchestrator.glob.glob", return_value=["/src/solr-10.0.0-SNAPSHOT.tgz"])
@mock.patch("solrorbit.test_run_orchestrator.Builder")
@mock.patch("solrorbit.test_run_orchestrator.SourceRepository")
def test_from_sources_passes_jvm_telemetry_devices(source_repository, bldr, glob_glob, tarfile_open, provisioner_class,
                                                   load_cluster_config, set_default_hosts, run_test, tmp_path):
    tarfile_open.return_value.__enter__.return_value.getnames.return_value = ["solr-10.0.0-SNAPSHOT/bin/solr"]
    cfg = _provisioned_cfg(tmp_path, ["jfr"])

    test_run_orchestrator.solr_from_sources(cfg)

    devices = provisioner_class.call_args.kwargs["telemetry_devices"]
    assert [device.command for device in devices] == ["jfr"]
    run_test.assert_called_once_with(cfg, external=True)
