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
"""The YAML session summary."""

from datetime import datetime, timezone

import yaml

from solrorbit.tools.launchr import summary
from solrorbit.tools.launchr.matrix import ProfileGroup
from solrorbit.tools.launchr.models import MatrixCell, ProfileSpec, RunOutcome

STARTED = datetime(2026, 10, 15, 2, 0, 0, tzinfo=timezone.utc)
FINISHED = datetime(2026, 10, 15, 4, 30, 0, tzinfo=timezone.utc)

PROFILE = ProfileSpec(name="local-docker", provisioning="local", install_method="docker")


def cell(workload="nyc_taxis", version="9.11.0"):
    return MatrixCell(workload=workload, test_procedure=None, solr_version=version,
                      profile="local-docker", cluster_config="default-1s1r")


def outcome(status=RunOutcome.COMPLETED, **kwargs):
    defaults = dict(cell=cell(), run_id="run-a1b2c3", session_id="session-f00ba7",
                    status=status, started_at=STARTED, finished_at=FINISHED,
                    test_run_id="tid", result_path="runs/nyc_taxis/2026-10-15/run-a1b2c3/results.json")
    defaults.update(kwargs)
    return RunOutcome(**defaults)


def group(cells=None):
    return ProfileGroup(profile=PROFILE, cells=cells or [cell()], nodes=1,
                        profile_names=["local-docker"])


class TestPath:
    def test_is_dated_and_named_by_session(self):
        assert summary.summary_path("session-f00ba7", STARTED) == \
            "summaries/2026-10-15-session-f00ba7.yaml"


class TestDocument:
    def test_counts_cells_by_outcome(self):
        document = summary.build("s", STARTED, FINISHED, [group()],
                                 [outcome(), outcome(RunOutcome.FAILED, error="boom")])
        assert (document["cells"], document["completed"], document["failed"]) == (2, 1, 1)

    def test_records_the_session_window(self):
        document = summary.build("s", STARTED, FINISHED, [group()], [outcome()])
        assert document["started_at"] == "2026-10-15T02:00:00Z"
        assert document["finished_at"] == "2026-10-15T04:30:00Z"

    def test_describes_each_provisioning_group(self):
        document = summary.build("s", STARTED, FINISHED, [group()], [outcome()])
        assert document["groups"] == [{
            "profiles": ["local-docker"], "provisioning": "local",
            "install_method": "docker", "nodes": 1,
        }]

    def test_each_matrix_entry_is_traceable_to_its_report(self):
        document = summary.build("s", STARTED, FINISHED, [group()], [outcome()])
        entry = document["matrix"][0]
        assert entry["run_id"] == "run-a1b2c3"
        assert entry["workload"] == "nyc_taxis"
        assert entry["solr_version"] == "9.11.0"
        assert entry["status"] == "completed"
        assert entry["result_path"].endswith("results.json")

    def test_a_failure_carries_its_reason(self):
        document = summary.build("s", STARTED, FINISHED, [group()],
                                 [outcome(RunOutcome.FAILED, error="DeployError: nope")])
        assert document["matrix"][0]["error"] == "DeployError: nope"

    def test_preserves_execution_order(self):
        outcomes = [outcome(cell=cell(version=v)) for v in ("9.0.0", "9.7.0", "9.11.0")]
        document = summary.build("s", STARTED, FINISHED, [group()], outcomes)
        assert [e["solr_version"] for e in document["matrix"]] == ["9.0.0", "9.7.0", "9.11.0"]


class TestRender:
    def test_round_trips_through_yaml(self):
        document = summary.build("s", STARTED, FINISHED, [group()], [outcome()])
        assert yaml.safe_load(summary.render(document)) == document

    def test_is_block_style_for_readability(self):
        rendered = summary.render(summary.build("s", STARTED, FINISHED, [group()], [outcome()])).decode()
        assert "session_id: s" in rendered
        assert "{" not in rendered.split("matrix:")[0]
