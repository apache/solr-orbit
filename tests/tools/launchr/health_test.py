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
"""Parsing ``/solr/admin/info/system``.

One response answers three questions -- is Solr up, what exactly is running,
and when was it built -- so this parser is on the critical path of every cell.
"""

from datetime import timezone

import pytest

from solrorbit.tools.launchr import health
from solrorbit.tools.launchr.errors import DeployError
from solrorbit.tools.launchr.models import SolrEndpoint


class TestImplVersionParsing:
    def test_release_build(self):
        commit, stamp = health.parse_impl_version("9.11.0 abc1234def5678 - jenkins - 2026-02-14 11:02:31")
        assert commit == "abc1234def5678"
        assert (stamp.year, stamp.month, stamp.day) == (2026, 2, 14)
        assert (stamp.hour, stamp.minute, stamp.second) == (11, 2, 31)
        assert stamp.tzinfo == timezone.utc

    def test_snapshot_build(self):
        commit, stamp = health.parse_impl_version("10.0.0-SNAPSHOT 9f8e7d6c5b4a - jan - 2026-10-14 03:17:45")
        assert commit == "9f8e7d6c5b4a"
        assert stamp.day == 14

    def test_builder_name_containing_spaces(self):
        commit, stamp = health.parse_impl_version("9.1.0 deadbeef - the release manager - 2023-01-02 03:04:05")
        assert commit == "deadbeef"
        assert stamp.year == 2023

    @pytest.mark.parametrize("value", ["", "nonsense", "9.11.0", "9.11.0 - jenkins - 2026-02-14 11:02:31"])
    def test_unparseable_strings_degrade_rather_than_raise(self, value):
        # A locally built image can carry anything here; that is not a reason to
        # fail a benchmark, because the release list may still place the version.
        assert health.parse_impl_version(value) == (None, None)


class TestSystemInfo:
    def test_release_response(self, info_system_release):
        info = health.parse_system_info(info_system_release)
        assert info.solr_version == "9.11.0"
        assert info.commit == "abc1234def5678"
        assert info.lucene_version == "9.12.0"
        assert info.jvm_vendor == "Eclipse Adoptium"
        assert info.jvm_version.startswith("21.0.5")
        assert info.cloud_mode is True

    def test_snapshot_response(self, info_system_snapshot):
        info = health.parse_system_info(info_system_snapshot)
        assert info.commit == "9f8e7d6c5b4a"
        assert info.build_timestamp is not None

    def test_empty_response_does_not_explode(self):
        info = health.parse_system_info({})
        assert info.solr_version == ""
        assert info.commit is None
        assert info.cloud_mode is False

    @pytest.mark.parametrize("mode,expected", [
        ("solrcloud", True), ("SolrCloud", True), ("std", False), ("user managed", False), (None, False),
    ])
    def test_cloud_mode_detection(self, mode, expected):
        assert health.parse_system_info({"mode": mode} if mode else {}).cloud_mode is expected


class TestProbe:
    def test_rejects_a_cluster_that_is_not_solrcloud(self, monkeypatch, info_system_release):
        # Solr Orbit only supports SolrCloud. Failing here beats failing deep
        # inside a benchmark with a less obvious message.
        payload = dict(info_system_release, mode="std")
        monkeypatch.setattr(health, "fetch", lambda endpoint, **kw: health.parse_system_info(payload))
        with pytest.raises(DeployError, match="not SolrCloud"):
            health.probe(SolrEndpoint())

    def test_accepts_non_cloud_when_not_required(self, monkeypatch, info_system_release):
        payload = dict(info_system_release, mode="std")
        monkeypatch.setattr(health, "fetch", lambda endpoint, **kw: health.parse_system_info(payload))
        assert health.probe(SolrEndpoint(), require_cloud=False).mode == "std"

    def test_retries_until_solr_answers(self, monkeypatch, info_system_release):
        calls = {"n": 0}

        def flaky(endpoint, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("not up yet")
            return health.parse_system_info(info_system_release)

        monkeypatch.setattr(health, "fetch", flaky)
        monkeypatch.setattr(health.time, "sleep", lambda _: None)
        assert health.probe(SolrEndpoint()).solr_version == "9.11.0"
        assert calls["n"] == 3

    def test_gives_up_with_the_last_error_attached(self, monkeypatch):
        monkeypatch.setattr(health, "fetch", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("refused")))
        monkeypatch.setattr(health.time, "sleep", lambda _: None)
        with pytest.raises(DeployError, match="refused"):
            health.probe(SolrEndpoint(), timeout=0.01)


class TestProbeCluster:
    """Multi-node readiness.

    Probing one node is not enough once a profile asks for two. A Solr that
    cannot reach ZooKeeper leaves the other node perfectly healthy and alone,
    and benchmarking then measures a one-node cluster while the report claims
    two -- a wrong number that looks entirely plausible.
    """

    @pytest.fixture
    def two_nodes(self):
        return [SolrEndpoint(host="10.0.0.1"), SolrEndpoint(host="10.0.0.2")]

    def _answer(self, monkeypatch, info_system_release):
        monkeypatch.setattr(
            health, "fetch", lambda endpoint, **kw: health.parse_system_info(info_system_release))
        monkeypatch.setattr(health.time, "sleep", lambda _: None)

    def test_a_single_node_needs_no_cluster_check(self, monkeypatch, info_system_release):
        self._answer(monkeypatch, info_system_release)
        monkeypatch.setattr(health, "live_nodes", lambda *a, **k: pytest.fail(
            "a one-node cluster must not be asked for its live nodes"))
        assert health.probe_cluster([SolrEndpoint()]).solr_version == "9.11.0"

    def test_every_node_is_probed(self, monkeypatch, info_system_release, two_nodes):
        seen = []
        monkeypatch.setattr(health, "fetch", lambda endpoint, **kw: (
            seen.append(endpoint.host), health.parse_system_info(info_system_release))[1])
        monkeypatch.setattr(health, "live_nodes", lambda *a, **k: ["10.0.0.1:8983_solr",
                                                                  "10.0.0.2:8983_solr"])
        monkeypatch.setattr(health.time, "sleep", lambda _: None)
        health.probe_cluster(two_nodes)
        assert seen == ["10.0.0.1", "10.0.0.2"]

    def test_it_waits_for_the_cluster_to_form(self, monkeypatch, info_system_release, two_nodes):
        self._answer(monkeypatch, info_system_release)
        calls = {"n": 0}

        def forming(*_args, **_kwargs):
            calls["n"] += 1
            return ["a_solr"] if calls["n"] < 3 else ["a_solr", "b_solr"]

        monkeypatch.setattr(health, "live_nodes", forming)
        health.probe_cluster(two_nodes)
        assert calls["n"] == 3

    def test_a_cluster_that_never_forms_is_a_clear_failure(self, monkeypatch,
                                                           info_system_release, two_nodes):
        self._answer(monkeypatch, info_system_release)
        monkeypatch.setattr(health, "live_nodes", lambda *a, **k: ["only-one_solr"])
        with pytest.raises(DeployError, match="1 live node"):
            health.probe_cluster(two_nodes, timeout=0.01)

    def test_the_failure_explains_why_it_matters(self, monkeypatch,
                                                 info_system_release, two_nodes):
        self._answer(monkeypatch, info_system_release)
        monkeypatch.setattr(health, "live_nodes", lambda *a, **k: [])
        with pytest.raises(DeployError, match="smaller cluster than the report claims"):
            health.probe_cluster(two_nodes, timeout=0.01)

    def test_an_unreadable_cluster_status_is_retried_not_fatal(self, monkeypatch,
                                                               info_system_release, two_nodes):
        self._answer(monkeypatch, info_system_release)
        calls = {"n": 0}

        def flaky(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] < 2:
                raise ConnectionError("collections API not up yet")
            return ["a_solr", "b_solr"]

        monkeypatch.setattr(health, "live_nodes", flaky)
        health.probe_cluster(two_nodes)
        assert calls["n"] == 2

    def test_no_endpoints_is_refused(self):
        with pytest.raises(DeployError, match="No Solr endpoints"):
            health.probe_cluster([])

    def test_live_nodes_reads_the_cluster_status_payload(self, monkeypatch):
        class Response:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"cluster": {"live_nodes": ["10.0.0.1:8983_solr", "10.0.0.2:8983_solr"]}}

        monkeypatch.setattr(health.requests, "get", lambda *a, **k: Response())
        assert health.live_nodes(SolrEndpoint()) == ["10.0.0.1:8983_solr", "10.0.0.2:8983_solr"]


class TestNightlyImplVersion:
    """A nightly's solr-impl-version stops after the commit.

    ``11.0.0-SNAPSHOT <sha> [snapshot build, details omitted]`` -- no builder,
    no timestamp. An all-or-nothing pattern threw away the commit along with
    the absent date, and the commit is the single most useful thing to know
    about a nightly: it says *which* main this was.
    """

    NIGHTLY = "11.0.0-SNAPSHOT 714d6ceff852e6dc743ef51ae094e4eaf8f3b3f9 [snapshot build, details omitted]"

    def test_the_commit_survives_a_missing_timestamp(self):
        commit, stamp = health.parse_impl_version(self.NIGHTLY)
        assert commit == "714d6ceff852e6dc743ef51ae094e4eaf8f3b3f9"
        assert stamp is None

    def test_a_release_build_still_yields_both(self):
        commit, stamp = health.parse_impl_version(
            "9.11.0 abc1234def - jenkins - 2026-02-14 11:02:31")
        assert commit == "abc1234def"
        assert stamp is not None and stamp.year == 2026

    def test_system_info_carries_the_nightly_commit(self):
        info = health.parse_system_info({
            "lucene": {"solr-spec-version": "11.0.0", "solr-impl-version": self.NIGHTLY},
            "mode": "solrcloud",
        })
        assert info.commit == "714d6ceff852e6dc743ef51ae094e4eaf8f3b3f9"
        assert info.build_timestamp is None

    @pytest.mark.parametrize("value", ["", "garbage", "9.11.0", "9.11.0 nothexadecimal"])
    def test_unparseable_strings_still_degrade_quietly(self, value):
        assert health.parse_impl_version(value) == (None, None)
