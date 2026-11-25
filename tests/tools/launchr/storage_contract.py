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
"""The behaviour every storage backend must have, independent of where it stores.

This module is the executable form of the claim that launchr's layout is
"identical across backends". A backend that passes it can be swapped in under
reportr without reportr noticing, which is the whole point of the abstraction.

Subclass :class:`StorageContract` and supply a ``storage`` fixture. It is not
named ``*_test.py`` on purpose, so pytest collects it only through subclasses
and the suite never runs against an abstract base.
"""

import pytest

from solrorbit.tools.launchr.errors import StorageError


class StorageContract:
    """Assertions that must hold for local, S3, and anything added later."""

    # -- round trip --------------------------------------------------------

    def test_write_then_read(self, storage):
        storage.write("a.json", b"{}")
        assert storage.read("a.json") == b"{}"

    def test_creates_intermediate_directories(self, storage):
        # S3 has no directories, local does; neither may require the caller to
        # care, because the orchestrator writes nested run paths blind.
        storage.write("runs/nyc_taxis/2026-10-15/run-a1b2c3/results.json", b"{}")
        assert storage.exists("runs/nyc_taxis/2026-10-15/run-a1b2c3/results.json")

    def test_exists_is_false_before_writing(self, storage):
        assert storage.exists("nope.json") is False

    def test_reading_something_absent_is_an_error(self, storage):
        with pytest.raises(StorageError, match="Could not read"):
            storage.read("nope.json")

    def test_round_trips_bytes_unchanged(self, storage):
        # Reports are UTF-8 JSON and logs are arbitrary bytes; neither may be
        # re-encoded or newline-translated in transit.
        payload = b'{"note": "caf\xc3\xa9"}\r\n\x00\xff'
        storage.write("raw.bin", payload)
        assert storage.read("raw.bin") == payload

    # -- immutability ------------------------------------------------------

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

    # -- listing -----------------------------------------------------------

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

    def test_a_prefix_matches_whole_path_segments_only(self, storage):
        # "runs/nyc" must not match "runs/nyc_taxis/...". On S3 that is a raw
        # string prefix unless the backend appends the separator itself.
        storage.write("runs/nyc_taxis/d/run-1/results.json", b"{}")
        assert storage.list("runs/nyc") == []
        assert storage.list("runs/nyc_taxis") == ["runs/nyc_taxis/d/run-1/results.json"]

    # -- path safety -------------------------------------------------------

    @pytest.mark.parametrize("path", ["/etc/passwd", "../outside.json", "a/../../outside.json"])
    def test_paths_cannot_escape_the_root(self, storage, path):
        with pytest.raises(StorageError):
            storage.write(path, b"{}")

    def test_empty_path_is_rejected(self, storage):
        with pytest.raises(StorageError, match="relative"):
            storage.write("", b"{}")

    # -- identity ----------------------------------------------------------

    def test_location_is_printable(self, storage):
        # The orchestrator logs this at session start; it must never be empty
        # and must not be a repr of an object.
        assert storage.location
        assert "object at 0x" not in storage.location
