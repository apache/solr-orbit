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
"""Reclaim infrastructure a run left behind.

A crashed orchestrator, a cancelled CI job, a closed laptop lid: each leaves
instances running and billing. ``launchr run`` tears down in a ``finally``,
but a process that is killed outright never reaches it, so this is the
backstop -- and it is deliberately usable without knowing anything about the
run that leaked.

**Two independent sources, because each covers the other's blind spot.**

*Cloud tags* say what exists right now. Authoritative about reality, but only
for the account, region and credentials in front of you.

*The ledger* in launchr's storage says what was ever created and never
released. It travels with the results, so a leak from someone's laptop is
visible to the nightly, and it names the region to go and look in -- which a
tag query cannot do, because you must already be in the right region to run
one.

Reconciliation takes the union: every region the ledger mentions is swept, and
anything tagged there is terminated whether or not the ledger knew about it.
A ledger entry whose instances are already gone is closed out rather than
retried forever.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from solrorbit.tools.launchr import ledger
from solrorbit.tools.launchr.provisioning.ec2 import aws
from solrorbit.tools.launchr.storage import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class Reclaimed:
    """What a teardown pass found and did."""

    regions: list[str] = field(default_factory=list)
    terminated: dict[str, list[str]] = field(default_factory=dict)
    closed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    security_groups: list[str] = field(default_factory=list)
    key_pairs: list[str] = field(default_factory=list)

    @property
    def instance_count(self) -> int:
        return sum(len(v) for v in self.terminated.values())

    def describe(self, *, dry_run: bool = False) -> str:
        verb = "Would terminate" if dry_run else "Terminated"
        lines = [f"regions swept: {', '.join(self.regions) or '(none)'}"]
        if self.terminated:
            lines.append(f"{verb} {self.instance_count} instance(s):")
            for stack, ids in sorted(self.terminated.items()):
                lines.append(f"  {stack}: {', '.join(ids)}")
        else:
            lines.append("No live launchr instances found.")
        if self.security_groups:
            lines.append(f"security groups: {len(self.security_groups)}")
        if self.key_pairs:
            lines.append(f"key pairs: {len(self.key_pairs)}")
        if self.closed:
            lines.append(f"ledger entries closed with nothing to do: {len(self.closed)}")
        for note in self.skipped:
            lines.append(f"skipped: {note}")
        return "\n".join(lines)


def reconcile(storage: StorageBackend | None, *, regions: list[str],
              aws_profile: str | None = None, older_than: timedelta | None = None,
              stack_id: str | None = None, dry_run: bool = False) -> Reclaimed:
    """Find and destroy leaked infrastructure.

    ``older_than`` guards the common mistake of running this while a benchmark
    is in progress: without it, a concurrent nightly's instances look exactly
    like a leak. With it, only stacks older than the window are touched.
    """
    result = Reclaimed()
    entries = {e.stack_id: e for e in ledger.leaked(storage)} if storage is not None else {}
    if stack_id:
        entries = {k: v for k, v in entries.items() if k == stack_id}

    sweep = sorted({*regions, *(e.region for e in entries.values() if e.region)})
    result.regions = sweep

    seen: set[str] = set()
    #: Regions actually queried. A region whose sweep failed proves nothing
    #: about what is running there, so its ledger entries must stay open.
    swept: set[str] = set()
    for region in sweep:
        try:
            ec2 = aws.client("ec2", region=region, profile=aws_profile)
            sessions = aws.find_sessions(ec2)
        except Exception as exc:  # noqa: BLE001 - one unreachable region must not stop the rest
            result.skipped.append(f"{region}: {exc}")
            continue
        swept.add(region)

        for found_stack, instances in sessions.items():
            if stack_id and found_stack != stack_id:
                continue
            if older_than is not None and not _older_than(instances, older_than):
                result.skipped.append(f"{found_stack}: younger than the --older-than window")
                continue
            ids = [i["InstanceId"] for i in instances]
            seen.add(found_stack)
            result.terminated[found_stack] = ids
            if dry_run:
                continue
            aws.terminate(ec2, ids)
            if storage is not None:
                ledger.record_released(storage, found_stack, {
                    "reason": "reclaimed by launchr teardown",
                    "instance_ids": ids,
                    "region": region,
                })

        if not dry_run:
            # Only stacks this pass actually terminated, or that have no live
            # instances at all. A concurrent run's security group and key must
            # survive: deleting them mid-benchmark would strip the cluster's
            # own ingress rules out from under it.
            live = {s for s in sessions if s not in result.terminated}
            result.security_groups += _sweep_groups(ec2, skip=live)
            result.key_pairs += _sweep_keys(ec2, skip=live)

    # A ledger entry with nothing live behind it: someone terminated by hand,
    # or provisioning failed before creating anything. Close it so it stops
    # being reported as a leak forever.
    #
    # Only where the sweep actually succeeded. Closing an entry because the
    # API call failed would mark a real leak as released and make it invisible
    # to every future run -- the one outcome this whole mechanism exists to
    # prevent.
    for entry_id, entry in entries.items():
        if entry_id in seen or dry_run:
            continue
        if entry.region:
            if entry.region not in swept:
                result.skipped.append(
                    f"{entry_id}: {entry.region} could not be swept, leaving the entry open")
                continue
        elif not swept or swept != set(sweep):
            result.skipped.append(
                f"{entry_id}: names no region and not every region was swept, leaving it open")
            continue
        result.closed.append(entry_id)
        if storage is not None:
            ledger.record_released(storage, entry_id, {
                "reason": "nothing found to reclaim; closed by launchr teardown",
            })
    return result


def _older_than(instances: list[dict], window: timedelta) -> bool:
    """Whether every instance in a stack launched before the window."""
    cutoff = datetime.now(timezone.utc) - window
    launches = [i.get("LaunchTime") for i in instances if i.get("LaunchTime")]
    return bool(launches) and all(t <= cutoff for t in launches)


def _sweep_groups(ec2, *, skip: set[str]) -> list[str]:
    """Delete launchr security groups no instance is using any more."""
    deleted = []
    for group_id, stack in aws.tagged_security_groups(ec2):
        if stack in skip:
            continue
        try:
            # delete_security_group fails while an ENI still references it,
            # which is exactly the "still in use" signal we want -- so a
            # failure here means "not orphaned yet", not "broken".
            ec2.delete_security_group(GroupId=group_id)
            deleted.append(group_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Security group %s is still in use: %s", group_id, exc)
    return deleted


def _sweep_keys(ec2, *, skip: set[str]) -> list[str]:
    """Delete launchr key pairs for stacks that are finished.

    Deleting a key pair does not lock anyone out of a *running* instance --
    the public key is already in its authorized_keys -- but removing one
    belonging to a live stack would still be a surprise, so skip those.
    """
    deleted = []
    for name, stack in aws.tagged_key_pairs(ec2):
        if stack in skip:
            continue
        try:
            ec2.delete_key_pair(KeyName=name)
            deleted.append(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not delete key pair %s: %s", name, exc)
    return deleted
