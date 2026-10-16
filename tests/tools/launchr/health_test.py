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
