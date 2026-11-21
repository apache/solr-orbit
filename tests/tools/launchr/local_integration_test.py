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
"""End-to-end: launchr against real Docker and a real Solr.

This is the test that proves the pieces fit. It runs two Solr versions of one
workload in test mode, and asserts the properties the unit tests cannot:

* Solr really starts, and ``/solr/admin/info/system`` really yields a commit
  hash -- which is what the whole version-timeline design rests on.
* Reports land in the agreed layout, and are enriched.
* Nothing is left behind: no container, and none of the processes Solr Orbit's
  actor system leaks when it fails to shut down.

Opt-in, because it takes minutes and needs Docker::

    LAUNCHR_IT=1 uv run pytest tests/tools/launchr/local_integration_test.py -s

It lives here rather than in ``it/`` only because that package's shared
bootstrap is currently broken -- it tries to install a nonexistent "Solr 1.3.9"
metrics store, an OpenSearch leftover that fails every test in the directory.
Move it to ``it/`` once that is fixed.

``--test-mode`` keeps each cell to 1000 documents, so the whole run is minutes
rather than hours.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from solrorbit.tools.launchr import cli
from solrorbit.tools.launchr.install.docker import CONTAINER_PREFIX

#: Two releases, so the result is a line rather than a dot. Both are old enough
#: to be stable Docker tags and new enough to be supported (min is 9.0.0).
VERSIONS = ["9.9.0", "9.10.1"]
WORKLOAD = "nyc_taxis"
PORT = 8983

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("LAUNCHR_IT") != "1",
        reason="Set LAUNCHR_IT=1 to run the launchr integration test (needs Docker, takes minutes)",
    ),
    pytest.mark.skipif(
        shutil.which("docker") is None, reason="Docker is required for the launchr integration test"
    ),
]


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def running_launchr_containers() -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=30,
    )
    return [n for n in result.stdout.split() if n]


@pytest.fixture(scope="module")
def session_output(tmp_path_factory):
    """Run launchr once; every assertion below reads from this one run."""
    if not docker_available():
        pytest.skip("Docker daemon is not responding")

    workdir = tmp_path_factory.mktemp("launchr-it")
    results = workdir / "benchmark-results"
    config = {
        "solr_versions": VERSIONS,
        "workloads": [WORKLOAD],
        "storage": {"backend": "local", "path": str(results)},
        "provisioning_profiles": {
            "local-docker": {
                "provisioning": "local",
                "install_method": "docker",
                "nodes": 1,
                "port": PORT,
                # Pulling two images on a cold cache takes a while.
                "startup_timeout": 600,
            }
        },
        "cluster_configs": {"it": {"heap": "1g", "gc": "G1GC", "shards": 1, "replicas": 1}},
        "defaults": {"provisioning": ["local-docker"], "cluster_config": ["it"]},
        "benchmark": {"test_mode": True, "user_tags": {"intention": "integration-test"}},
    }
    config_path = workdir / "launchr.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    exit_code = cli.main(["run", "-c", str(config_path)])
    return exit_code, results


def reports(results: Path) -> list[Path]:
    return sorted(results.glob(f"runs/{WORKLOAD}/*/run-*/results.json"))


class TestTheRunSucceeds:
    def test_exit_code_is_zero(self, session_output):
        exit_code, _ = session_output
        assert exit_code == 0, "every cell should have completed"

    def test_one_report_per_version(self, session_output):
        _, results = session_output
        assert len(reports(results)) == len(VERSIONS)

    def test_reports_follow_the_agreed_layout(self, session_output):
        _, results = session_output
        for report in reports(results):
            # runs/<workload>/<yyyy-mm-dd>/<run-id>/results.json
            parts = report.relative_to(results).parts
            assert parts[0] == "runs" and parts[1] == WORKLOAD
            assert len(parts[2]) == len("2026-10-15")
            assert parts[3].startswith("run-")

    def test_a_summary_lists_the_session(self, session_output):
        _, results = session_output
        summaries = list(results.glob("summaries/*.yaml"))
        assert len(summaries) == 1
        document = yaml.safe_load(summaries[0].read_text())
        assert document["cells"] == len(VERSIONS)
        assert document["completed"] == len(VERSIONS)
        assert [c["solr_version"] for c in document["matrix"]] == VERSIONS


class TestEnrichment:
    @pytest.fixture
    def documents(self, session_output):
        _, results = session_output
        return [json.loads(p.read_text()) for p in reports(results)]

    def test_solr_orbits_own_keys_are_present(self, documents):
        for document in documents:
            assert "results" in document
            assert document["results"]["op_metrics"], "a real run produces operation metrics"
            assert document["workload"] == WORKLOAD

    def test_solr_orbit_can_parse_the_stored_report(self, documents):
        from solrorbit.metrics import TestRun

        for document in documents:
            assert TestRun.from_dict(document).workload_name == WORKLOAD

    def test_the_commit_hash_was_read_from_the_live_cluster(self, documents):
        # The proof that the health-check path really works: nothing else in the
        # system can produce this value.
        for document in documents:
            commit = document["launchr"]["solr"]["commit"]
            assert commit, "info/system should have yielded a commit hash"
            assert len(commit) >= 7

    def test_the_version_sits_on_the_timeline(self, documents):
        for document in documents:
            solr = document["launchr"]["solr"]
            assert solr["version_timestamp"], "every point needs an x position"
            assert solr["version_timestamp_source"] in ("apache-releases", "info-system")
            assert solr["version_kind"] == "release"

    def test_the_jvm_is_recorded(self, documents):
        for document in documents:
            assert document["launchr"]["solr"]["jvm"]["version"]

    def test_the_applied_cluster_config_is_recorded(self, documents):
        for document in documents:
            applied = document["launchr"]["cluster_config"]["applied_env"]
            assert applied["SOLR_HEAP"] == "1g"
            assert "UseG1GC" in applied["GC_TUNE"]

    def test_the_run_is_labelled_as_local(self, documents):
        # So a reporting layer never presents laptop data as production data.
        for document in documents:
            assert document["launchr"]["infra"]["provider"] == "local"

    def test_test_mode_is_recorded(self, documents):
        for document in documents:
            assert document["launchr"]["benchmark"]["test_mode"] is True

    def test_each_cell_has_its_own_run_id_and_shares_the_session(self, documents):
        run_ids = {d["launchr"]["run_id"] for d in documents}
        session_ids = {d["launchr"]["session_id"] for d in documents}
        assert len(run_ids) == len(VERSIONS)
        assert len(session_ids) == 1

    def test_the_versions_differ_between_reports(self, documents):
        # Two distinct data points is the whole point of running more than one.
        versions = {d["launchr"]["solr"]["version"] for d in documents}
        assert versions == set(VERSIONS)

    def test_the_commits_differ_between_versions(self, documents):
        commits = {d["launchr"]["solr"]["commit"] for d in documents}
        assert len(commits) == len(VERSIONS), "different Solr versions are different builds"


class TestCleanliness:
    def test_no_container_is_left_running(self, session_output):
        # A leaked container holds port 8983 and breaks the next run.
        _, _ = session_output
        assert running_launchr_containers() == []

    def test_successful_cells_stored_no_logs(self, session_output):
        _, results = session_output
        assert list(results.glob("runs/**/logs/*")) == []

    def test_no_solr_orbit_process_is_left_behind(self, session_output):
        # Solr Orbit hangs in its actor-system shutdown after a successful
        # benchmark and its actors call setsid() to escape the process group.
        # launchr terminates them by test-run id; without that, every cell
        # leaks a pair of processes.
        _, _ = session_output
        result = subprocess.run(["pgrep", "-f", "solrorbit.benchmark"],
                                capture_output=True, text=True)
        assert [p for p in result.stdout.split() if p] == []
