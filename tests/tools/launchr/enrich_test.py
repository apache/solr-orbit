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
"""Report enrichment.

The contract this file defends: every key Solr Orbit wrote survives untouched,
so ``solr-orbit compare`` and ``TestRun.from_dict()`` still work on a stored
report. Everything launchr adds lives under one key.
"""

from datetime import datetime, timezone

import pytest

from solrorbit.tools.launchr import enrich, health, translate
from solrorbit.tools.launchr.models import (
    ClusterConfigSpec,
    MatrixCell,
    NodeHandle,
    ProfileSpec,
    ProvisionedInfra,
    RunOutcome,
    SolrDeployment,
    SolrEndpoint,
    VersionInfo,
)

CELL = MatrixCell(workload="nyc_taxis", test_procedure=None, solr_version="9.11.0",
                  profile="local-docker", cluster_config="default-1s1r")


@pytest.fixture
def cluster_config():
    return translate.resolve(ClusterConfigSpec(name="default-1s1r", heap="4g", gc="G1GC",
                                               shards=1, replicas=1))


@pytest.fixture
def deployment(cluster_config):
    profile = ProfileSpec(name="local-docker", provisioning="local", install_method="docker")
    endpoint = SolrEndpoint()
    infra = ProvisionedInfra(
        profile=profile, strategy="local", install_method="docker",
        nodes=[NodeHandle(name="solr-1", endpoint=endpoint)],
        metadata={"provider": "local", "nodes": 1, "host": {"os": "Darwin 27.0.0"}},
    )
    return SolrDeployment(infra=infra, version="9.11.0", image="docker.io/library/solr:9.11.0",
                          endpoints=[endpoint], cluster_config=cluster_config)


@pytest.fixture
def outcome():
    now = datetime(2026, 10, 15, 2, 0, 15, tzinfo=timezone.utc)
    return RunOutcome(cell=CELL, run_id="run-a1b2c3", session_id="session-f00ba7",
                      status=RunOutcome.COMPLETED, started_at=now,
                      finished_at=datetime(2026, 10, 15, 2, 41, 3, tzinfo=timezone.utc),
                      test_run_id="tid")


def block(outcome, cluster_config, deployment=None, system_info=None, version_info=None, **kwargs):
    defaults = dict(
        cell=CELL, outcome=outcome, cluster_config=cluster_config,
        workload_params={"num_shards": 1}, workload_repository="default",
        benchmark={"iterations": 1, "aggregate": False, "test_mode": True},
        argv=["python", "-m", "solrorbit.benchmark", "run"],
        deployment=deployment, system_info=system_info, version_info=version_info,
        infra_metadata=deployment.infra.metadata if deployment else None,
    )
    defaults.update(kwargs)
    return enrich.build_block(**defaults)


class TestOrbitKeysAreUntouched:
    def test_every_key_survives_byte_identical(self, orbit_report, outcome, cluster_config):
        import copy
        original = copy.deepcopy(orbit_report)
        enriched = enrich.enrich(orbit_report, block(outcome, cluster_config), cell=CELL)
        for key, value in original.items():
            assert enriched[key] == value, f"Solr Orbit's {key!r} was modified"

    def test_the_only_added_key_is_launchr(self, orbit_report, outcome, cluster_config):
        before = set(orbit_report)
        enriched = enrich.enrich(dict(orbit_report), block(outcome, cluster_config), cell=CELL)
        assert set(enriched) - before == {"launchr"}

    def test_solr_orbit_can_still_parse_the_stored_report(self, orbit_report, outcome, cluster_config):
        # The contract that keeps `solr-orbit compare` working on stored data.
        from solrorbit.metrics import TestRun
        enriched = enrich.enrich(dict(orbit_report), block(outcome, cluster_config), cell=CELL)
        test_run = TestRun.from_dict(enriched)
        assert test_run.workload_name == orbit_report["workload"]
        assert test_run.test_run_id == orbit_report["test-run-id"]

    def test_results_are_preserved_for_reportr(self, orbit_report, outcome, cluster_config):
        enriched = enrich.enrich(dict(orbit_report), block(outcome, cluster_config), cell=CELL)
        assert enriched["results"]["op_metrics"] == orbit_report["results"]["op_metrics"]


class TestLaunchrBlock:
    def test_identity(self, outcome, cluster_config):
        b = block(outcome, cluster_config)
        assert b["schema_version"] == enrich.SCHEMA_VERSION
        assert b["run_id"] == "run-a1b2c3"
        assert b["session_id"] == "session-f00ba7"
        assert b["cell_id"] == CELL.cell_id
        assert b["status"] == "completed"

    def test_timestamps_are_utc_iso(self, outcome, cluster_config):
        b = block(outcome, cluster_config)
        assert b["started_at"] == "2026-10-15T02:00:15Z"
        assert b["finished_at"] == "2026-10-15T02:41:03Z"

    def test_records_the_commit_the_cluster_reported(self, outcome, cluster_config, deployment,
                                                     info_system_release):
        info = health.parse_system_info(info_system_release)
        b = block(outcome, cluster_config, deployment=deployment, system_info=info)
        assert b["solr"]["commit"] == "abc1234def5678"
        assert b["solr"]["impl_version"].startswith("9.11.0 abc1234def5678")
        assert b["solr"]["jvm"]["vendor"] == "Eclipse Adoptium"
        assert b["solr"]["image"] == "docker.io/library/solr:9.11.0"

    def test_records_the_timestamp_source_alongside_the_timestamp(self, outcome, cluster_config):
        info = VersionInfo(version="9.11.0", timestamp=datetime(2026, 10, 4, tzinfo=timezone.utc),
                           source="apache-releases", precision="day", kind="release",
                           commit="abc", branch=None)
        b = block(outcome, cluster_config, version_info=info)
        assert b["solr"]["version_timestamp"] == "2026-10-04T00:00:00Z"
        assert b["solr"]["version_timestamp_source"] == "apache-releases"
        assert b["solr"]["version_timestamp_precision"] == "day"
        assert b["solr"]["version_kind"] == "release"

    def test_records_branch_and_how_it_was_decided(self, outcome, cluster_config):
        info = VersionInfo(version="10.1.0-SNAPSHOT", timestamp=datetime.now(timezone.utc),
                           source="info-system", precision="second", kind="snapshot",
                           branch="branch_10x", branch_source="inferred")
        b = block(outcome, cluster_config, version_info=info)
        assert (b["solr"]["branch"], b["solr"]["branch_source"]) == ("branch_10x", "inferred")

    def test_records_what_was_asked_for_and_what_was_applied(self, outcome, cluster_config, deployment):
        # A reader should never have to guess what gc: "G1GC" meant on the day.
        cc = block(outcome, cluster_config, deployment=deployment)["cluster_config"]
        assert cc["heap"] == "4g" and cc["gc"] == "G1GC"
        assert cc["applied_env"]["SOLR_HEAP"] == "4g"
        assert "UseG1GC" in cc["applied_env"]["GC_TUNE"]
        assert cc["workload_params"] == {"num_shards": 1, "replication_factor": 1}

    def test_an_externally_managed_cluster_applied_nothing(self, outcome, cluster_config, deployment):
        # install_method: none cannot set heap or GC on a cluster someone else
        # started, so claiming it did would be a false record.
        deployment.infra.install_method = "none"
        cc = block(outcome, cluster_config, deployment=deployment)["cluster_config"]
        assert cc["applied_env"] == {}
        # The request itself is still recorded, where it reads as a request.
        assert cc["heap"] == "4g" and cc["gc"] == "G1GC"

    def test_a_cell_that_never_deployed_applied_nothing(self, outcome, cluster_config):
        cc = block(outcome, cluster_config)["cluster_config"]
        assert cc["applied_env"] == {}
        assert cc["heap"] == "4g"

    def test_records_the_infrastructure(self, outcome, cluster_config, deployment):
        infra = block(outcome, cluster_config, deployment=deployment)["infra"]
        assert infra["provisioning_profile"] == "local-docker"
        assert infra["provisioning"] == "local"
        assert infra["install_method"] == "docker"
        assert infra["provider"] == "local"

    def test_records_the_workload_revision_from_the_orbit_report(self, orbit_report, outcome,
                                                                 cluster_config):
        revision = enrich.workload_revision_of(orbit_report)
        b = block(outcome, cluster_config, workload_revision=revision)
        assert b["workload"]["revision"] == orbit_report["workload-revision"]

    def test_records_the_exact_command(self, outcome, cluster_config):
        assert block(outcome, cluster_config)["benchmark"]["command"][:2] == ["python", "-m"]

    def test_records_test_mode(self, outcome, cluster_config):
        assert block(outcome, cluster_config)["benchmark"]["test_mode"] is True


class TestFailedCells:
    def test_a_failure_still_produces_a_readable_report(self, cluster_config):
        now = datetime.now(timezone.utc)
        outcome = RunOutcome(cell=CELL, run_id="run-x", session_id="session-y",
                             status=RunOutcome.FAILED, started_at=now, finished_at=now,
                             error="DeployError: Solr did not start")
        enriched = enrich.enrich(None, block(outcome, cluster_config), cell=CELL,
                                 test_run_id="tid")
        assert enriched["workload"] == "nyc_taxis"
        assert enriched["launchr"]["status"] == "failed"
        assert "Solr did not start" in enriched["launchr"]["error"]

    def test_a_failure_has_no_results_key(self, cluster_config):
        # Which is how reportr tells a failure from a success.
        now = datetime.now(timezone.utc)
        outcome = RunOutcome(cell=CELL, run_id="r", session_id="s", status=RunOutcome.FAILED,
                             started_at=now, finished_at=now, error="boom")
        enriched = enrich.enrich(None, block(outcome, cluster_config), cell=CELL)
        assert "results" not in enriched

    def test_metadata_resolved_before_the_failure_is_kept(self, cluster_config, deployment,
                                                          info_system_release):
        # A cell that died during the benchmark still knows what it deployed.
        now = datetime.now(timezone.utc)
        outcome = RunOutcome(cell=CELL, run_id="r", session_id="s", status=RunOutcome.FAILED,
                             started_at=now, finished_at=now, error="benchmark failed")
        info = health.parse_system_info(info_system_release)
        b = block(outcome, cluster_config, deployment=deployment, system_info=info)
        assert b["solr"]["commit"] == "abc1234def5678"


def test_workload_revision_of_handles_a_missing_report():
    assert enrich.workload_revision_of(None) is None
    assert enrich.workload_revision_of({}) is None
