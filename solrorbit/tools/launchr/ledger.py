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
"""A record of what launchr created, so a leak is detectable later.

Cloud tags already say what exists *right now*, and ``launchr teardown``
queries them. This ledger answers a different question: what did launchr
*intend* to exist, and was it ever cleaned up? That matters because a tag
query only sees the account, region and credentials you happen to be using,
whereas the ledger travels with the results -- so a leak provisioned from a
laptop is visible to the next nightly, in CI, in a different shell.

**Append-only, two files per stack.**

``infra/<stack-id>/provisioned.json``
    Written before anything is created, so an orchestrator killed mid-create
    still leaves a trace. It names the region and profile, which is what a
    later reconciliation needs in order to go looking.
``infra/<stack-id>/instances.json``
    Written once the instance ids exist, which is necessarily after the
    provisioned record. A second file rather than a rewrite, because stored
    records are immutable.
``infra/<stack-id>/released.json``
    Written only after teardown has actually succeeded.

A stack with the first and not the second is a suspected leak. Nothing is ever
deleted or rewritten, which keeps this compatible with the storage backend's
immutability rule and leaves an audit trail of every run's infrastructure.

A suspected leak is not a confirmed one: someone may have terminated the
instances by hand. Reconciliation therefore always checks the cloud before
acting, and records a release either way.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from solrorbit.tools.launchr.errors import StorageError
from solrorbit.tools.launchr.storage import StorageBackend

logger = logging.getLogger(__name__)

PREFIX = "infra"
PROVISIONED = "provisioned.json"
INSTANCES = "instances.json"
RELEASED = "released.json"


@dataclass
class LedgerEntry:
    """One stack's record."""

    stack_id: str
    provisioned: dict[str, Any]
    released: dict[str, Any] | None = None
    instances: dict[str, Any] | None = None

    @property
    def leaked(self) -> bool:
        """Whether this stack was created and never recorded as cleaned up."""
        return self.released is None

    @property
    def region(self) -> str | None:
        return self.provisioned.get("region")

    @property
    def profile(self) -> str | None:
        return self.provisioned.get("profile")

    @property
    def created_at(self) -> datetime | None:
        raw = self.provisioned.get("created_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def age(self) -> str:
        created = self.created_at
        if created is None:
            return "unknown age"
        delta = datetime.now(timezone.utc) - created
        hours = delta.total_seconds() / 3600
        return f"{hours:.1f}h old" if hours < 48 else f"{delta.days}d old"

    def instance_ids(self) -> list[str]:
        """The ids to terminate.

        The amendment wins when present: the provisioned record is written
        before the instances exist, so its list is always empty.
        """
        source = self.instances or self.provisioned
        return [str(i) for i in source.get("instance_ids", [])]

    def describe(self) -> str:
        where = f"{self.region or '?'}/{self.profile or '?'}"
        count = len(self.instance_ids())
        return f"{self.stack_id}  {where}  {count} instance(s)  {self.age}"


def _path(stack_id: str, name: str) -> str:
    return f"{PREFIX}/{stack_id}/{name}"


def record_provisioned(storage: StorageBackend, stack_id: str, record: dict) -> None:
    """Note that a stack is being created.

    Called *before* the cloud calls, not after: an orchestrator killed partway
    through creating instances is exactly the case this exists to catch, and a
    record written afterwards would never exist for it. The cost is an
    occasional record for a stack that failed before creating anything, which
    reconciliation resolves harmlessly by finding nothing to terminate.
    """
    document = {"stack_id": stack_id, "created_at": _now(), **record}
    storage.write(_path(stack_id, PROVISIONED), _json(document))
    logger.debug("Recorded provisioning of %s", stack_id)


def record_instances(storage: StorageBackend, stack_id: str, instance_ids: list[str]) -> None:
    """Amend a stack's record with the ids that now exist.

    Never raises: failing here would abort a run whose infrastructure is
    already up, and the tag-based sweep still finds the instances.
    """
    try:
        storage.write(_path(stack_id, INSTANCES),
                      _json({"stack_id": stack_id, "instance_ids": list(instance_ids),
                             "recorded_at": _now()}))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record instance ids for %s: %s", stack_id, exc)


def record_released(storage: StorageBackend, stack_id: str, detail: dict | None = None) -> None:
    """Note that a stack was successfully torn down.

    Never raises: this runs at the end of a teardown that has already
    succeeded, and failing here would turn a clean run into a failed one while
    leaving nothing actually leaked. A missing release record costs one
    needless reconciliation check later.
    """
    document = {"stack_id": stack_id, "released_at": _now(), **(detail or {})}
    path = _path(stack_id, RELEASED)
    try:
        # Already released is the normal outcome of a belt-and-braces second
        # teardown -- a run's own finally block and a later reconciliation can
        # both reach the same stack. Nothing to do, and nothing to warn about.
        if storage.exists(path):
            logger.debug("%s was already recorded as released", stack_id)
            return
        storage.write(path, _json(document))
        logger.debug("Recorded release of %s", stack_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Tore down %s but could not record it in the ledger: %s. "
            "A later `launchr teardown` will re-check it and find nothing to do.",
            stack_id, exc,
        )


def entries(storage: StorageBackend) -> list[LedgerEntry]:
    """Every recorded stack, newest first."""
    try:
        paths = storage.list(PREFIX)
    except StorageError as exc:
        logger.warning("Could not read the infrastructure ledger: %s", exc)
        return []

    found: dict[str, LedgerEntry] = {}
    releases: dict[str, dict] = {}
    instances: dict[str, dict] = {}
    for path in sorted(paths):
        parts = path.split("/")
        if len(parts) != 3 or parts[0] != PREFIX:
            continue
        stack_id, name = parts[1], parts[2]
        document = _read(storage, path)
        if document is None:
            continue
        if name == PROVISIONED:
            found[stack_id] = LedgerEntry(stack_id=stack_id, provisioned=document)
        elif name == RELEASED:
            releases[stack_id] = document
        elif name == INSTANCES:
            instances[stack_id] = document

    for stack_id, entry in found.items():
        entry.released = releases.get(stack_id)
        entry.instances = instances.get(stack_id)

    return sorted(found.values(), key=lambda e: e.provisioned.get("created_at") or "", reverse=True)


def leaked(storage: StorageBackend) -> list[LedgerEntry]:
    """Stacks recorded as created and never recorded as released."""
    return [entry for entry in entries(storage) if entry.leaked]


def _read(storage: StorageBackend, path: str) -> dict | None:
    try:
        document = json.loads(storage.read(path).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - a damaged record must not hide the others
        logger.warning("Ignoring unreadable ledger entry %s: %s", path, exc)
        return None
    return document if isinstance(document, dict) else None


def _json(document: dict) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
