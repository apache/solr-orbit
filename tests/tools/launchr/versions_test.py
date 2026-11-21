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
"""Placing a version on the chart's x-axis.

The headline property: this works with no git clone and no GitHub token, and
degrades in precision rather than failing when the release list is unreachable.
"""

from datetime import datetime, timezone

import pytest

from solrorbit.tools.launchr import versions
from solrorbit.tools.launchr.errors import VersionResolutionError
from solrorbit.tools.launchr.models import SystemInfo


def system_info(**kwargs):
    defaults = dict(solr_version="9.11.0", solr_impl_version="9.11.0 abc123 - j - 2026-02-14 11:02:31",
                    commit="abc123", build_timestamp=datetime(2026, 2, 14, 11, 2, 31, tzinfo=timezone.utc))
    defaults.update(kwargs)
    return SystemInfo(**defaults)


class TestClassify:
    @pytest.mark.parametrize("version", ["9.11.0", "10.0.0", "9.0.0"])
    def test_releases(self, version):
        assert versions.classify(version) == versions.KIND_RELEASE

    @pytest.mark.parametrize("version", ["10.0.0-SNAPSHOT", "9.12.0-SNAPSHOT", "9.11.1-SNAPSHOT"])
    def test_snapshots(self, version):
        assert versions.classify(version) == versions.KIND_SNAPSHOT

    @pytest.mark.parametrize("version", ["main", "9", "9.11", "latest", ""])
    def test_anything_else(self, version):
        assert versions.classify(version) == versions.KIND_UNKNOWN


class TestInferBranch:
    def test_unreleased_major_zero_zero_is_main(self):
        assert versions.infer_branch("11.0.0-SNAPSHOT", {9, 10}) == "main"

    def test_released_major_gets_its_stable_branch(self):
        # Once 10.0.0 has shipped, 10.0.0-SNAPSHOT no longer means main.
        assert versions.infer_branch("10.0.0-SNAPSHOT", {9, 10}) == "branch_10x"

    def test_minor_development_is_the_major_branch(self):
        assert versions.infer_branch("9.12.0-SNAPSHOT", {9, 10}) == "branch_9x"

    def test_patch_development_is_the_release_branch(self):
        assert versions.infer_branch("9.11.1-SNAPSHOT", {9, 10}) == "branch_9_11"

    def test_releases_have_no_branch(self):
        assert versions.infer_branch("9.11.0", {9}) is None


class TestReleaseIndex:
    def test_reads_dates_from_the_project_json(self, solr_project):
        index = versions.ReleaseIndex.from_payload(solr_project)
        assert index.date("9.11.0") == datetime(2026, 10, 4, tzinfo=timezone.utc)
        assert index.date("9.0.0").year == 2022

    def test_knows_which_majors_have_shipped(self, solr_project):
        assert versions.ReleaseIndex.from_payload(solr_project).majors == {9, 10}

    def test_unknown_version_has_no_date(self, solr_project):
        assert versions.ReleaseIndex.from_payload(solr_project).date("9.99.0") is None

    def test_round_trips_through_the_cache_format(self, solr_project):
        index = versions.ReleaseIndex.from_payload(solr_project)
        assert versions.ReleaseIndex.from_payload(index.as_payload()).dates == index.dates


class TestTimeline:
    @pytest.fixture
    def timeline(self, monkeypatch, solr_project, tmp_path):
        monkeypatch.setattr(versions, "fetch_release_index",
                            lambda **kw: versions.ReleaseIndex.from_payload(solr_project))
        return versions.VersionTimeline(versions.VersionCache(tmp_path / "cache.json"))

    def test_release_uses_the_announcement_date(self, timeline):
        info = timeline.resolve("9.11.0", system_info())
        assert info.source == versions.SOURCE_APACHE_RELEASES
        assert info.precision == versions.PRECISION_DAY
        assert info.timestamp == datetime(2026, 10, 4, tzinfo=timezone.utc)
        assert info.kind == versions.KIND_RELEASE
        assert info.branch is None

    def test_commit_comes_from_the_cluster_even_for_a_release(self, timeline):
        # The release list knows the date; only the cluster knows what was built.
        assert timeline.resolve("9.11.0", system_info(commit="deadbeef")).commit == "deadbeef"

    def test_snapshot_uses_the_build_timestamp(self, timeline):
        info = timeline.resolve("10.1.0-SNAPSHOT", system_info(
            build_timestamp=datetime(2026, 10, 14, 3, 17, 45, tzinfo=timezone.utc)))
        assert info.source == versions.SOURCE_INFO_SYSTEM
        assert info.precision == versions.PRECISION_SECOND
        assert info.branch == "branch_10x"
        assert info.branch_source == "inferred"

    def test_unlisted_release_falls_back_to_the_build_timestamp(self, timeline):
        info = timeline.resolve("9.99.0", system_info())
        assert info.source == versions.SOURCE_INFO_SYSTEM
        assert info.kind == versions.KIND_RELEASE

    def test_explicit_timestamp_wins(self, timeline):
        when = datetime(2020, 1, 1, tzinfo=timezone.utc)
        info = timeline.resolve("9.11.0", system_info(), override_timestamp=when)
        assert info.timestamp == when
        assert info.source == versions.SOURCE_EXPLICIT

    def test_explicit_branch_wins_and_is_recorded_as_such(self, timeline):
        info = timeline.resolve("9.12.0-SNAPSHOT", system_info(), override_branch="feature/foo")
        assert (info.branch, info.branch_source) == ("feature/foo", versions.SOURCE_EXPLICIT)

    def test_no_source_can_answer(self, timeline):
        with pytest.raises(VersionResolutionError, match="--version-timestamp"):
            timeline.resolve("9.99.0", system_info(build_timestamp=None))

    def test_release_list_is_fetched_once_per_run(self, monkeypatch, solr_project, tmp_path):
        calls = {"n": 0}

        def counting(**kwargs):
            calls["n"] += 1
            return versions.ReleaseIndex.from_payload(solr_project)

        monkeypatch.setattr(versions, "fetch_release_index", counting)
        timeline = versions.VersionTimeline(versions.VersionCache(tmp_path / "c.json"))
        for version in ("9.0.0", "9.7.0", "9.11.0"):
            timeline.resolve(version, system_info())
        assert calls["n"] == 1


class TestOfflineBehaviour:
    def test_network_failure_degrades_to_the_build_timestamp(self, monkeypatch, tmp_path):
        # The whole point of the chain: launchr still produces a timestamp, and
        # the report says which source answered.
        def boom(**kwargs):
            raise ConnectionError("projects.apache.org unreachable")

        monkeypatch.setattr(versions, "fetch_release_index", boom)
        timeline = versions.VersionTimeline(versions.VersionCache(tmp_path / "c.json"))
        info = timeline.resolve("9.11.0", system_info())
        assert info.source == versions.SOURCE_INFO_SYSTEM
        assert info.timestamp == datetime(2026, 2, 14, 11, 2, 31, tzinfo=timezone.utc)

    def test_cache_answers_when_the_network_does_not(self, monkeypatch, solr_project, tmp_path):
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(versions, "fetch_release_index",
                            lambda **kw: versions.ReleaseIndex.from_payload(solr_project))
        versions.VersionTimeline(versions.VersionCache(cache_path)).resolve("9.11.0", system_info())
        assert cache_path.exists()

        def boom(**kwargs):
            raise ConnectionError("offline now")

        monkeypatch.setattr(versions, "fetch_release_index", boom)
        info = versions.VersionTimeline(versions.VersionCache(cache_path)).resolve("9.11.0", system_info())
        assert info.source == versions.SOURCE_APACHE_RELEASES

    def test_offline_mode_does_not_touch_the_network(self, monkeypatch, tmp_path):
        def boom(**kwargs):
            raise AssertionError("offline mode must not call out")

        monkeypatch.setattr(versions, "fetch_release_index", boom)
        timeline = versions.VersionTimeline(versions.VersionCache(tmp_path / "c.json"), offline=True)
        assert timeline.resolve("9.11.0", system_info()).source == versions.SOURCE_INFO_SYSTEM

    def test_unreadable_cache_is_a_warning_not_a_failure(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "cache.json"
        cache_path.write_text("{ not json")
        monkeypatch.setattr(versions, "fetch_release_index",
                            lambda **kw: (_ for _ in ()).throw(ConnectionError("down")))
        timeline = versions.VersionTimeline(versions.VersionCache(cache_path))
        assert timeline.resolve("9.11.0", system_info()).source == versions.SOURCE_INFO_SYSTEM
