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
"""The local storage backend.

These assertions are written to be reusable: when a cloud backend arrives, the
same suite should run against it, which is what makes "identical layout,
identical code paths" a tested claim rather than an aspiration.
"""

import pytest

from solrorbit.tools.launchr.errors import StorageError
from solrorbit.tools.launchr.storage import get_backend
from solrorbit.tools.launchr.storage.local import LocalStorageBackend


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(tmp_path / "results")


class TestRoundTrip:
    def test_write_then_read(self, storage):
        storage.write("a.json", b"{}")
        assert storage.read("a.json") == b"{}"

    def test_creates_intermediate_directories(self, storage):
        storage.write("runs/nyc_taxis/2026-10-15/run-a1b2c3/results.json", b"{}")
        assert storage.exists("runs/nyc_taxis/2026-10-15/run-a1b2c3/results.json")

    def test_exists_is_false_before_writing(self, storage):
        assert storage.exists("nope.json") is False

    def test_reading_something_absent_is_an_error(self, storage):
        with pytest.raises(StorageError, match="Could not read"):
            storage.read("nope.json")


class TestImmutability:
    def test_overwrite_is_refused_by_default(self, storage):
        # Silently replacing a stored report is a data-integrity bug that is
        # nearly impossible to notice afterwards.
        storage.write("a.json", b"first")
        with pytest.raises(StorageError, match="immutable"):
            storage.write("a.json", b"second")
        assert storage.read("a.json") == b"first"

    def test_overwrite_is_possible_when_asked_explicitly(self, storage):
        storage.write("a.json", b"first")
        storage.write("a.json", b"second", overwrite=True)
        assert storage.read("a.json") == b"second"


class TestListing:
    def test_lists_recursively_and_sorted(self, storage):
        storage.write("runs/w/d/run-2/results.json", b"{}")
        storage.write("runs/w/d/run-1/results.json", b"{}")
        storage.write("summaries/s.yaml", b"{}")
        assert storage.list("runs") == [
            "runs/w/d/run-1/results.json", "runs/w/d/run-2/results.json",
        ]

    def test_empty_prefix_lists_everything(self, storage):
        storage.write("a.json", b"{}")
        storage.write("b/c.json", b"{}")
        assert storage.list("") == ["a.json", "b/c.json"]

    def test_absent_prefix_lists_nothing(self, storage):
        assert storage.list("runs") == []

    def test_partial_writes_are_not_listed(self, storage, tmp_path):
        # An atomic write uses a .tmp file; a crashed run must not leave
        # something reportr would try to parse.
        storage.write("a.json", b"{}")
        (storage.root / "leftover.json.tmp").write_bytes(b"half")
        assert storage.list("") == ["a.json"]


class TestPathSafety:
    @pytest.mark.parametrize("path", ["/etc/passwd", "../outside.json", "a/../../outside.json"])
    def test_paths_cannot_escape_the_root(self, storage, path):
        with pytest.raises(StorageError):
            storage.write(path, b"{}")

    def test_empty_path_is_rejected(self, storage):
        with pytest.raises(StorageError, match="relative"):
            storage.write("", b"{}")

    @pytest.mark.parametrize("prefix", ["/etc", "../outside", "runs/../../outside"])
    def test_a_list_prefix_cannot_escape_the_root_either(self, storage, prefix):
        # list() used to join the prefix on unchecked, so it could walk out of
        # the root and then raise ValueError on the way back in.
        with pytest.raises(StorageError):
            storage.list(prefix)

    def test_an_ordinary_prefix_still_lists(self, storage):
        storage.write("runs/a/results.json", b"{}")
        assert storage.list("runs") == ["runs/a/results.json"]

    def test_a_prefix_that_does_not_exist_is_empty_not_an_error(self, storage):
        assert storage.list("nothing-here") == []


class TestRegistry:
    def test_get_backend_by_name(self, tmp_path):
        assert isinstance(get_backend("local", str(tmp_path)), LocalStorageBackend)

    def test_unknown_backend_lists_the_alternatives(self, tmp_path):
        from solrorbit.tools.launchr.errors import ConfigError
        with pytest.raises(ConfigError, match="local"):
            get_backend("s3", str(tmp_path))

    def test_expands_a_user_relative_path(self):
        assert str(LocalStorageBackend("~/x").root).startswith("/")
