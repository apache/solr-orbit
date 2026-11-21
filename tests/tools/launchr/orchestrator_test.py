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
"""The lifecycle loop, against fake plugins.

This is the heaviest test file in launchr, because it defends the two
properties most able to regress unnoticed:

* the lifecycle happens in the right order, and
* a failure is isolated -- it produces a report, it undeploys, it tears down,
  and it does not stop the next cell.
"""

import json
from datetime import datetime, timezone

import pytest
import yaml

from solrorbit.tools.launchr import health, orchestrator
from solrorbit.tools.launchr.config import load
from solrorbit.tools.launchr.errors import DeployError, ProvisioningError
from solrorbit.tools.launchr.models import (
    NodeHandle,
    OrbitResult,
    ProvisionedInfra,
    SolrDeployment,
    SolrEndpoint,
    SystemInfo,
    VersionInfo,
)

def system_info_for(version: str) -> SystemInfo:
    """What a healthy Solr of ``version`` would report."""
    return SystemInfo(
        solr_version=version.replace("-SNAPSHOT", ""),
        solr_impl_version=f"{version} abc1234 - jenkins - 2026-02-14 11:02:31",
        commit="abc1234",
        build_timestamp=datetime(2026, 2, 14, 11, 2, 31, tzinfo=timezone.utc),
        jvm_vendor="Eclipse Adoptium", jvm_version="21.0.5", mode="solrcloud",
    )


class Journal:
    """Records what happened, in order, and what Solr is currently pretending to be."""

    def __init__(self):
        self.events: list[str] = []
        #: Set by FakeInstall.deploy so the fake health probe can answer with
        #: the version that was actually deployed.
        self.deployed_version: str | None = None

    def record(self, event: str) -> None:
        self.events.append(event)

    def of_kind(self, prefix: str) -> list[str]:
        return [e for e in self.events if e.startswith(prefix)]


class FakeStrategy:
    name = "fake"

    def __init__(self, journal, *, fail_provision=False, orbit_returncode=0, orbit_report=None):
        self.journal = journal
        self.fail_provision = fail_provision
        self.orbit_returncode = orbit_returncode
        self.orbit_report = orbit_report

    def provision(self, profile, *, nodes):
        self.journal.record(f"provision:{profile.name}:{nodes}")
        if self.fail_provision:
            raise ProvisioningError("no capacity")
        endpoint = SolrEndpoint(port=profile.port)
        return ProvisionedInfra(
            profile=profile, strategy=self.name, install_method=profile.install_method,
            nodes=[NodeHandle(name="solr-1", endpoint=endpoint)],
            metadata={"provider": "fake", "nodes": nodes},
        )

    def run_on_driver(self, infra, invocation):
        self.journal.record("run_on_driver")
        invocation.log_path.parent.mkdir(parents=True, exist_ok=True)
        invocation.log_path.write_bytes(b"solr-orbit output\n")
        report = self.orbit_report
        if report is None and self.orbit_returncode == 0:
            report = {"workload": "w", "test-run-id": invocation.test_run_id,
                      "workload-revision": "0b99cd0", "results": {"op_metrics": []}}
        return OrbitResult(
            returncode=self.orbit_returncode,
            test_run_id=invocation.test_run_id,
            report=json.dumps(report).encode() if report is not None else None,
            log_path=invocation.log_path,
        )

    def teardown(self, infra):
        self.journal.record("teardown")


class FakeInstall:
    name = "fake-install"

    def __init__(self, journal, *, fail_deploy=False):
        self.journal = journal
        self.fail_deploy = fail_deploy
        self.deploy_calls = 0

    def deploy(self, infra, version, image, cluster_config):
        self.deploy_calls += 1
        self.journal.record(f"deploy:{version}")
        self.journal.deployed_version = version
        if self.fail_deploy:
            raise DeployError("Solr would not start")
        return SolrDeployment(infra=infra, version=version, image=f"solr:{version}",
                              endpoints=infra.endpoints, cluster_config=cluster_config,
                              handles={"container": "fake"})

    def undeploy(self, deployment):
        self.journal.record(f"undeploy:{deployment.version}")

    def collect_logs(self, deployment):
        self.journal.record("collect_logs")
        return {"solr-node-1.log": b"solr said something\n"}


class FakeTimeline:
    def __init__(self, *args, **kwargs):
        pass

    def resolve(self, version, system_info=None, **kwargs):
        return VersionInfo(version=version, timestamp=datetime(2026, 10, 4, tzinfo=timezone.utc),
                           source="apache-releases", precision="day", kind="release",
                           commit=system_info.commit if system_info else None)


@pytest.fixture
def journal():
    return Journal()


@pytest.fixture
def harness(monkeypatch, journal, tmp_path):
    """Wire the orchestrator up to fakes, and return a builder for sessions."""
    monkeypatch.setattr(orchestrator, "VersionTimeline", FakeTimeline)
    # The fake Solr reports whatever version was just deployed, so the
    # orchestrator's version-mismatch guard sees a consistent cluster.
    probe = lambda *a, **k: system_info_for(journal.deployed_version or "9.11.0")  # noqa: E731
    monkeypatch.setattr(health, "probe", probe)
    monkeypatch.setattr(orchestrator.health, "probe", probe)
    # Retry backoff is 10s/30s/90s; a failure test would otherwise sit here for
    # over two minutes.
    monkeypatch.setattr(orchestrator.retry.time, "sleep", lambda _: None)

    def build(*, versions=("9.11.0",), workloads=("w",), strategy_kwargs=None,
              install_kwargs=None, profiles=None, cluster_configs=None, defaults=None,
              benchmark=None):
        strategy = FakeStrategy(journal, **(strategy_kwargs or {}))
        install = FakeInstall(journal, **(install_kwargs or {}))
        monkeypatch.setattr(orchestrator, "get_strategy", lambda name: strategy)
        monkeypatch.setattr(orchestrator, "get_install_method", lambda name, **kw: install)

        document = {
            "solr_versions": list(versions),
            "workloads": list(workloads),
            "storage": {"backend": "local", "path": str(tmp_path / "results")},
            "provisioning_profiles": profiles or {
                "p": {"provisioning": "fake", "install_method": "fake-install"}},
            "cluster_configs": cluster_configs or {"c": {"heap": "1g", "shards": 1}},
            "defaults": defaults or {"provisioning": ["p"], "cluster_config": ["c"]},
        }
        if benchmark:
            document["benchmark"] = benchmark
        path = tmp_path / "launchr.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        session = orchestrator.Session(load(path, env={}))
        return session, strategy, install

    return build


def stored(tmp_path) -> list[str]:
    root = tmp_path / "results"
    if not root.exists():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


class TestHappyPath:
    def test_returns_success(self, harness):
        session, _, _ = harness()
        assert session.run() == 0

    def test_lifecycle_runs_in_order(self, harness, journal):
        session, _, _ = harness()
        session.run()
        assert journal.events == [
            "provision:p:1", "deploy:9.11.0", "run_on_driver", "undeploy:9.11.0", "teardown",
        ]

    def test_stores_a_report_per_cell(self, harness, tmp_path):
        session, _, _ = harness(versions=("9.0.0", "9.7.0", "9.11.0"))
        session.run()
        reports = [p for p in stored(tmp_path) if p.endswith("results.json")]
        assert len(reports) == 3

    def test_report_path_follows_the_agreed_layout(self, harness, tmp_path):
        session, _, _ = harness(workloads=("nyc_taxis",))
        session.run()
        report = [p for p in stored(tmp_path) if p.endswith("results.json")][0]
        parts = report.split("/")
        assert parts[0] == "runs" and parts[1] == "nyc_taxis"
        assert parts[2] == session.started_at.strftime("%Y-%m-%d")
        assert parts[3].startswith("run-")

    def test_each_cell_gets_its_own_run_id(self, harness):
        session, _, _ = harness(versions=("9.0.0", "9.11.0"))
        session.run()
        assert len({o.run_id for o in session.outcomes}) == 2

    def test_all_cells_share_the_session_id(self, harness):
        session, _, _ = harness(versions=("9.0.0", "9.11.0"))
        session.run()
        assert {o.session_id for o in session.outcomes} == {session.session_id}

    def test_successful_cells_store_no_logs(self, harness, tmp_path):
        # Logs on failure only: the thing you need, when you need it, without
        # unbounded growth on the happy path.
        session, _, _ = harness()
        session.run()
        assert not any("/logs/" in p for p in stored(tmp_path))

    def test_enriched_report_carries_the_resolved_metadata(self, harness, tmp_path):
        session, _, _ = harness()
        session.run()
        report_path = [p for p in stored(tmp_path) if p.endswith("results.json")][0]
        document = json.loads((tmp_path / "results" / report_path).read_text())
        block = document["launchr"]
        assert block["status"] == "completed"
        assert block["solr"]["commit"] == "abc1234"
        assert block["solr"]["version_timestamp_source"] == "apache-releases"
        assert block["cluster_config"]["applied_env"]["SOLR_HEAP"] == "1g"
        assert document["results"]["op_metrics"] == []

    def test_infrastructure_is_provisioned_once_for_many_cells(self, harness, journal):
        session, _, _ = harness(versions=("9.0.0", "9.7.0", "9.11.0"))
        session.run()
        assert len(journal.of_kind("provision")) == 1
        assert len(journal.of_kind("teardown")) == 1
        assert len(journal.of_kind("deploy")) == 3

    def test_solr_is_redeployed_per_cell(self, harness, install=None):
        # Each cell must start from an empty index, which means a fresh Solr.
        session, _, install = harness(versions=("9.0.0", "9.11.0"))
        session.run()
        assert install.deploy_calls == 2


class TestSummary:
    def test_writes_a_session_summary(self, harness, tmp_path):
        session, _, _ = harness()
        session.run()
        summaries = [p for p in stored(tmp_path) if p.startswith("summaries/")]
        assert len(summaries) == 1
        assert session.session_id in summaries[0]

    def test_summary_lists_cells_in_execution_order(self, harness, tmp_path):
        session, _, _ = harness(versions=("9.0.0", "9.7.0", "9.11.0"), workloads=("a", "b"))
        session.run()
        path = [p for p in stored(tmp_path) if p.startswith("summaries/")][0]
        document = yaml.safe_load((tmp_path / "results" / path).read_text())
        assert document["cells"] == 6
        assert document["completed"] == 6
        order = [(c["workload"], c["solr_version"]) for c in document["matrix"]]
        assert order == [
            ("a", "9.0.0"), ("a", "9.7.0"), ("a", "9.11.0"),
            ("b", "9.0.0"), ("b", "9.7.0"), ("b", "9.11.0"),
        ]

    def test_summary_records_result_paths(self, harness, tmp_path):
        session, _, _ = harness()
        session.run()
        path = [p for p in stored(tmp_path) if p.startswith("summaries/")][0]
        document = yaml.safe_load((tmp_path / "results" / path).read_text())
        assert document["matrix"][0]["result_path"].endswith("results.json")


class TestFailureIsolation:
    def test_a_failed_benchmark_does_not_stop_the_next_cell(self, harness, tmp_path):
        session, _, _ = harness(versions=("9.0.0", "9.11.0"),
                                strategy_kwargs={"orbit_returncode": 1})
        assert session.run() == 1
        assert len(session.outcomes) == 2
        assert all(o.status == "failed" for o in session.outcomes)
        assert len([p for p in stored(tmp_path) if p.endswith("results.json")]) == 2

    def test_a_failed_deploy_still_undeploys_and_tears_down(self, harness, journal):
        session, _, _ = harness(install_kwargs={"fail_deploy": True})
        session.run()
        assert "teardown" in journal.events

    def test_a_failed_cell_stores_its_logs(self, harness, tmp_path):
        session, _, _ = harness(strategy_kwargs={"orbit_returncode": 1})
        session.run()
        logs = [p for p in stored(tmp_path) if "/logs/" in p]
        assert any(p.endswith("logs/solr-orbit.log") for p in logs)
        assert any(p.endswith("logs/solr-node-1.log") for p in logs)

    def test_solr_logs_are_collected_before_undeploying(self, harness, journal):
        # Undeploying usually destroys them, so order matters.
        session, _, _ = harness(strategy_kwargs={"orbit_returncode": 1})
        session.run()
        assert journal.events.index("collect_logs") < journal.events.index("undeploy:9.11.0")

    def test_the_failure_reason_reaches_the_report(self, harness, tmp_path):
        session, _, _ = harness(install_kwargs={"fail_deploy": True})
        session.run()
        report = [p for p in stored(tmp_path) if p.endswith("results.json")][0]
        document = json.loads((tmp_path / "results" / report).read_text())
        assert document["launchr"]["status"] == "failed"
        assert "would not start" in document["launchr"]["error"]

    def test_failed_provisioning_fails_only_its_own_group(self, harness, tmp_path):
        session, _, install = harness(versions=("9.0.0", "9.11.0"),
                                      strategy_kwargs={"fail_provision": True})
        assert session.run() == 1
        assert len(session.outcomes) == 2
        assert install.deploy_calls == 0
        # Every cell still gets a report, so the failure is visible in storage.
        assert len([p for p in stored(tmp_path) if p.endswith("results.json")]) == 2

    def test_failed_provisioning_is_not_retried_per_cell(self, harness, journal):
        session, _, _ = harness(versions=("9.0.0", "9.11.0"),
                                strategy_kwargs={"fail_provision": True})
        session.run()
        # Retried within the group (4 attempts), not once per cell.
        assert len(journal.of_kind("provision")) == 4

    def test_an_unexpected_exception_is_still_isolated(self, harness, monkeypatch, tmp_path):
        def explode(*args, **kwargs):
            raise RuntimeError("something nobody anticipated")

        monkeypatch.setattr(orchestrator.health, "probe", explode)
        session, _, _ = harness(versions=("9.0.0", "9.11.0"))
        assert session.run() == 1
        assert len(session.outcomes) == 2
        assert all("RuntimeError" in o.error for o in session.outcomes)


class TestVersionMismatch:
    def test_a_cluster_running_the_wrong_version_fails_the_cell(self, harness, monkeypatch):
        # The data point would be mislabelled, which is worse than no data point.
        monkeypatch.setattr(orchestrator.health, "probe",
                            lambda *a, **k: SystemInfo(solr_version="9.10.0",
                                                       solr_impl_version="", mode="solrcloud"))
        session, _, _ = harness(versions=("9.11.0",))
        assert session.run() == 1
        assert "mislabelled" in session.outcomes[0].error

    def test_a_snapshot_reporting_its_base_version_is_accepted(self, harness, monkeypatch):
        # A 10.0.0-SNAPSHOT image reports solr-spec-version 10.0.0.
        monkeypatch.setattr(orchestrator.health, "probe",
                            lambda *a, **k: SystemInfo(solr_version="10.0.0",
                                                       solr_impl_version="", mode="solrcloud"))
        session, _, _ = harness(versions=("10.0.0-SNAPSHOT",))
        assert session.run() == 0

    def test_a_version_that_only_starts_the_same_is_rejected(self, harness, monkeypatch):
        # "9.11.0".startswith("9.1") is true, but 9.1 is not 9.11.0 and the
        # report would carry the wrong label.
        monkeypatch.setattr(orchestrator.health, "probe",
                            lambda *a, **k: SystemInfo(solr_version="9.1",
                                                       solr_impl_version="", mode="solrcloud"))
        session, _, _ = harness(versions=("9.11.0",))
        assert session.run() == 1
        assert "mislabelled" in session.outcomes[0].error


class TestFailedDeployKeepsItsLogs:
    def test_logs_read_by_the_install_method_are_stored(self, harness, tmp_path, monkeypatch):
        # A failed deploy leaves no SolrDeployment to collect logs from, so the
        # install method attaches what it read to the error instead.
        session, _, install = harness()

        def deploy(infra, version, image, cluster_config):
            raise DeployError("Solr would not start", logs={"solr.log": b"boom\n"})

        monkeypatch.setattr(install, "deploy", deploy)
        session.run()
        assert any(p.endswith("logs/solr.log") for p in stored(tmp_path))


class TestTeardownRobustness:
    def test_a_raising_teardown_does_not_fail_the_session(self, harness, journal):
        session, strategy, _ = harness()

        def angry_teardown(infra):
            journal.record("teardown")
            raise RuntimeError("teardown exploded")

        strategy.teardown = angry_teardown
        assert session.run() == 0

    def test_a_raising_undeploy_does_not_fail_the_cell(self, harness):
        session, _, install = harness()

        def angry_undeploy(deployment):
            raise RuntimeError("undeploy exploded")

        install.undeploy = angry_undeploy
        assert session.run() == 0
