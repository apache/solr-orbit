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
"""The infrastructure ledger.

What this protects is money: a stack recorded as created and never released
is an instance still billing. The assertions below are mostly about the
failure cases, because the happy path is the one that never needed a ledger.
"""

import json

import pytest

from solrorbit.tools.launchr import ledger
from solrorbit.tools.launchr.errors import StorageError
from solrorbit.tools.launchr.storage import LocalStorageBackend


@pytest.fixture
def storage(tmp_path):
    return LocalStorageBackend(tmp_path / "results")


def provision(storage, stack_id, **extra):
    ledger.record_provisioned(storage, stack_id, {
        "region": "eu-north-1", "profile": "ec2-2node", **extra,
    })


class TestRecording:
    def test_a_provisioned_stack_is_leaked_until_released(self, storage):
        provision(storage, "session-a-1234")
        assert [e.stack_id for e in ledger.leaked(storage)] == ["session-a-1234"]

    def test_releasing_clears_it(self, storage):
        provision(storage, "session-a-1234")
        ledger.record_released(storage, "session-a-1234", {"reason": "completed"})
        assert ledger.leaked(storage) == []

    def test_the_entry_survives_as_an_audit_trail(self, storage):
        # Nothing is deleted: the record of what ran is worth keeping, and it
        # keeps the ledger compatible with the backend's immutability rule.
        provision(storage, "session-a-1234")
        ledger.record_released(storage, "session-a-1234")
        assert len(ledger.entries(storage)) == 1
        assert ledger.entries(storage)[0].released is not None

    def test_instance_ids_are_amended_after_creation(self, storage):
        # The provisioned record is written before any instance exists, so its
        # list is empty by construction; the amendment is where the ids live.
        provision(storage, "session-a-1234", instance_ids=[])
        ledger.record_instances(storage, "session-a-1234", ["i-111", "i-222"])
        assert ledger.leaked(storage)[0].instance_ids() == ["i-111", "i-222"]

    def test_several_stacks_are_tracked_independently(self, storage):
        provision(storage, "session-a-1111")
        provision(storage, "session-b-2222")
        ledger.record_released(storage, "session-a-1111")
        assert [e.stack_id for e in ledger.leaked(storage)] == ["session-b-2222"]

    def test_region_is_recorded_so_a_sweep_knows_where_to_look(self, storage):
        # A tag query can only see the region you are already in, so a leak is
        # unfindable without this.
        provision(storage, "session-a-1234")
        assert ledger.leaked(storage)[0].region == "eu-north-1"


class TestResilience:
    """A ledger that breaks a run is worse than no ledger."""

    def test_releasing_never_raises_when_storage_fails(self, storage, monkeypatch):
        provision(storage, "session-a-1234")

        def explode(*_args, **_kwargs):
            raise StorageError("bucket on fire")

        monkeypatch.setattr(storage, "write", explode)
        ledger.record_released(storage, "session-a-1234")  # must not raise

    def test_recording_instances_never_raises(self, storage, monkeypatch):
        monkeypatch.setattr(storage, "write", lambda *a, **k: (_ for _ in ()).throw(
            StorageError("nope")))
        ledger.record_instances(storage, "session-a-1234", ["i-1"])  # must not raise

    def test_a_corrupt_entry_does_not_hide_the_others(self, storage):
        provision(storage, "session-good-1")
        storage.write("infra/session-bad-2/provisioned.json", b"{not json")
        assert [e.stack_id for e in ledger.leaked(storage)] == ["session-good-1"]

    def test_unrelated_paths_under_the_prefix_are_ignored(self, storage):
        provision(storage, "session-a-1234")
        storage.write("infra/stray.json", b"{}")
        storage.write("infra/a/b/c/deep.json", b"{}")
        assert len(ledger.entries(storage)) == 1

    def test_an_empty_store_has_no_entries(self, storage):
        assert ledger.entries(storage) == []
        assert ledger.leaked(storage) == []

    def test_provisioning_is_recorded_before_anything_exists(self, storage):
        # The whole point: a process killed between this call and run_instances
        # still leaves something for reconciliation to find.
        provision(storage, "session-a-1234")
        raw = json.loads(storage.read("infra/session-a-1234/provisioned.json"))
        assert raw["stack_id"] == "session-a-1234"
        assert "created_at" in raw


class TestDescription:
    def test_describe_names_the_stack_region_and_size(self, storage):
        provision(storage, "session-a-1234")
        ledger.record_instances(storage, "session-a-1234", ["i-1", "i-2", "i-3"])
        text = ledger.leaked(storage)[0].describe()
        assert "session-a-1234" in text
        assert "eu-north-1" in text
        assert "3 instance(s)" in text

    def test_an_unparseable_timestamp_reads_as_unknown_rather_than_crashing(self, storage):
        # Written directly, because record_provisioned stamps its own.
        storage.write("infra/s-2/provisioned.json",
                      b'{"stack_id": "s-2", "created_at": "whenever"}')
        entry = ledger.entries(storage)[0]
        assert entry.created_at is None
        assert entry.age == "unknown age"
        assert "unknown age" in entry.describe()

    def test_a_missing_timestamp_reads_as_unknown(self, storage):
        storage.write("infra/s-3/provisioned.json", b'{"stack_id": "s-3"}')
        assert ledger.entries(storage)[0].age == "unknown age"
