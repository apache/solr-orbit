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
"""Shared fixtures for the reportr tests."""

import copy
import json
from pathlib import Path

import pytest

RESOURCES = Path(__file__).parent / "resources"
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def away_from_the_repo_config(tmp_path, monkeypatch):
    """Run every reportr test somewhere without a reportr.yaml.

    ``config.load(None)`` picks up ``./reportr.yaml`` when one is there, so a
    suite run from the repository root silently inherits the repository's own
    settings -- and a test asserting a default would start failing the moment
    someone edits that file. Tests that want it ask for it by path.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def repo_config_path() -> str:
    """The repository's own reportr.yaml, for the tests that check it loads."""
    return str(REPO_ROOT / "reportr.yaml")


@pytest.fixture
def enriched_report() -> dict:
    """A real launchr-enriched report, trimmed to three operations."""
    return json.loads((RESOURCES / "enriched_report.json").read_text(encoding="utf-8"))


@pytest.fixture
def make_report(enriched_report):
    """Build variants of the report: a different version, line or status."""

    def build(*, version="9.11.0", timestamp="2026-10-04T00:00:00Z", run_id="run-aaaaaa",
              kind="release", branch=None, profile="local-docker", cluster_config="default-1s1r",
              status="completed", workload="nyc_taxis", test_mode=True, revision="a4684f1",
              procedure=None, source="apache-releases"):
        report = copy.deepcopy(enriched_report)
        block = report["launchr"]
        block["run_id"] = run_id
        block["status"] = status
        block["solr"].update({
            "version": version, "version_timestamp": timestamp, "version_kind": kind,
            "branch": branch, "version_timestamp_source": source,
        })
        block["infra"]["provisioning_profile"] = profile
        block["cluster_config"]["name"] = cluster_config
        block["workload"].update({"name": workload, "revision": revision,
                                  "test_procedure": procedure})
        block["benchmark"]["test_mode"] = test_mode
        report["workload"] = workload
        return report

    return build


@pytest.fixture
def storage(tmp_path, make_report):
    """A storage directory holding three reports of one workload."""
    root = tmp_path / "benchmark-results"
    versions = [("9.9.0", "2025-07-24T00:00:00Z", "run-aaa111"),
                ("9.10.1", "2026-01-20T00:00:00Z", "run-bbb222"),
                ("9.11.0", "2026-10-04T00:00:00Z", "run-ccc333")]
    for version, timestamp, run_id in versions:
        report = make_report(version=version, timestamp=timestamp, run_id=run_id)
        path = root / "runs" / "nyc_taxis" / "2026-10-15" / run_id / "results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report), encoding="utf-8")
    return root
