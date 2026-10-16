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

The shared behavioural contract lives in ``storage_contract.py`` and runs here
and against S3 unchanged. What is left in this file is what only a filesystem
can be asked about.
"""

import pytest

from solrorbit.tools.launchr.errors import ConfigError, StorageError
from solrorbit.tools.launchr.storage import LocalStorageBackend, S3StorageBackend, backend_for, get_backend
from tests.tools.launchr.storage_contract import StorageContract


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(tmp_path / "results")


class TestLocalContract(StorageContract):
    """The shared suite, against the local filesystem."""


class TestFilesystemSpecifics:
    def test_partial_writes_are_not_listed(self, storage):
        # An atomic write uses a .tmp file; a crashed run must not leave
        # something reportr would try to parse.
        storage.write("a.json", b"{}")
        (storage.root / "leftover.json.tmp").write_bytes(b"half")
        assert storage.list("") == ["a.json"]

    def test_expands_a_user_relative_path(self):
        assert str(LocalStorageBackend("~/x").root).startswith("/")

    def test_write_is_atomic_leaving_no_temp_file(self, storage):
        storage.write("a.json", b"{}")
        assert [p.name for p in storage.root.rglob("*.tmp")] == []

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

    def test_s3_is_registered(self, tmp_path):
        assert isinstance(get_backend("s3", "s3://bucket/prefix"), S3StorageBackend)

    def test_unknown_backend_lists_the_alternatives(self, tmp_path):
        with pytest.raises(ConfigError, match="local, s3"):
            get_backend("gcs", str(tmp_path))

    def test_a_scheme_selects_its_backend(self):
        assert isinstance(backend_for("s3://bucket/prefix"), S3StorageBackend)

    def test_a_plain_path_selects_local(self, tmp_path):
        assert isinstance(backend_for(str(tmp_path)), LocalStorageBackend)

    def test_options_the_backend_does_not_take_are_an_error(self, tmp_path):
        # Silently dropping a setting someone wrote down is worse than failing.
        with pytest.raises(ConfigError, match="does not accept storage.options"):
            get_backend("local", str(tmp_path), {"region": "eu-north-1"})

    def test_storage_error_is_not_swallowed_as_a_config_error(self, storage):
        # get_backend maps TypeError to ConfigError; a StorageError raised for
        # a real reason must still surface as one.
        with pytest.raises(StorageError):
            storage.read("missing.json")
