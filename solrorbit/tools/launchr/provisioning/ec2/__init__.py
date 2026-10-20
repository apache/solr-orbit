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
"""Dedicated EC2 instances, with the load driver on its own machine.

The first strategy whose output is publishable, because it is the first that
separates the driver from the cluster. ``local`` co-locates them, which makes
the driver's own CPU use part of what the benchmark measures.

**Shape.** One driver instance and ``nodes`` Solr instances, all in a single
subnet so every run shares an availability zone -- two Solr nodes in different
AZs would put inter-AZ latency in the middle of every replica operation and
make the numbers incomparable with a single-AZ run.

**No infrastructure-as-code tool.** boto3 directly, which is already a core
dependency: no CLI binary, no provider plugin, no state file to lose. What
replaces the state file is a pair of records -- cloud tags on everything
created, and a ledger entry in launchr's own storage (see
:mod:`solrorbit.tools.launchr.ledger`). Teardown works off either, so a
crashed orchestrator is recoverable without having kept anything local.
"""

import logging
import math
import re
import os
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

from solrorbit.tools.launchr import ledger, orbit_ini
from solrorbit.tools.launchr.errors import ConfigError, ProvisioningError
from solrorbit.tools.launchr.models import (
    NodeHandle,
    OrbitInvocation,
    OrbitResult,
    ProfileSpec,
    ProvisionedInfra,
    SolrEndpoint,
    SshSpec,
)
from solrorbit.tools.launchr.provisioning.ec2 import aws
from solrorbit.tools.launchr.provisioning.ec2.ssh import (
    CommandResult,
    SshSession,
    write_private_key,
)

logger = logging.getLogger(__name__)

#: Profile options this strategy understands. An unknown one is a typo worth
#: failing on: silently ignoring `instance_typ` would run the wrong hardware
#: and the report would look perfectly normal.
KNOWN_OPTIONS = frozenset({
    "region", "aws_profile", "instance_type", "driver_instance_type", "ami",
    "ssh_user", "ssh_cidr", "extra_ssh_cidrs", "subnet_id", "availability_zone",
    "volume_gb", "driver_volume_gb", "volume_type", "wheel",
    "data_volume", "driver_data_volume", "host_tuning",
})

#: Where Solr's index goes.
#:
#: A dedicated volume by default, not the instance root. The root volume is
#: sized for an operating system and sits at the gp3 baseline of 3000 IOPS and
#: 125 MB/s; a merge-heavy indexing run against that is plausibly measuring
#: the disk rather than Solr, which is the one thing a version-comparison
#: benchmark must not do. Separating it also means the index's throughput can
#: be raised without paying for a larger root disk.
#:
#: ``mode: root`` puts it back on the root volume -- cheaper, and fine for a
#: --test-mode smoke run.
DEFAULT_DATA_VOLUME: dict[str, Any] = {
    "mode": "ebs",
    # Large enough for any current workload without thinking about it:
    # nyc_taxis indexes to roughly 40 GB across the cluster, and force-merge
    # transiently needs room for a second copy of what it is merging.
    "size_gb": 500,
    "type": "gp3",
    # Well above the 3000/125 baseline. gp3 bills provisioned IOPS and
    # throughput separately from capacity, so this is a few dollars a month
    # pro-rated to the hours a run actually lasts.
    "iops": 16000,
    "throughput_mbps": 1000,
}

#: The driver's corpus cache volume.
#:
#: Sized for several workloads rather than one: nyc_taxis alone is 84.6 GB on
#: disk and the cache is shared by every cell in a session, so the root
#: volume runs out partway through a download, hours in.
DEFAULT_DRIVER_DATA_VOLUME: dict[str, Any] = {
    "mode": "ebs",
    # "auto" sizes it from the corpora the configured workloads declare; an
    # explicit number wins. See _auto_corpus_size_gb.
    "size_gb": "auto",
    "type": "gp3",
    # Modest next to the Solr nodes': the driver reads the corpus
    # sequentially at roughly 30 MB/s during indexing, well inside the
    # baseline. Capacity is what it needs, not throughput.
    "iops": 3000,
    "throughput_mbps": 250,
}

#: Kernel settings applied to Solr nodes before Solr starts.
#:
#: Defaults chosen to remove variance rather than to maximise a number:
#: transparent huge pages off, swapping effectively disabled, and the CPU
#: governor pinned where the instance exposes one. Set any value to ``null``
#: to leave the machine alone.
DEFAULT_HOST_TUNING: dict[str, Any] = {
    "transparent_hugepages": "never",
    "swappiness": 1,
    "cpu_governor": "performance",
}

DEFAULTS: dict[str, Any] = {
    "region": "eu-north-1",
    "instance_type": "m7i.2xlarge",
    "driver_instance_type": "m7i.large",
    "ssh_user": "ec2-user",
    "volume_gb": 100,
    "driver_volume_gb": 50,
    "volume_type": "gp3",
}

#: Paths on the driver, relative to its home directory.
#:
#: Resolved against the *real* home rather than written with a leading ``~``.
#: Every remote argv is quoted with :func:`shlex.quote` before it crosses the
#: SSH shell -- which is what keeps a workload name from turning into shell
#: syntax -- and quoting also suppresses tilde expansion, so a ``~`` path
#: arrives at the far side as a literal directory called "~" and the command
#: fails with exit 127.
REMOTE_VENV = "orbit-venv"
REMOTE_PYTHON = f"{REMOTE_VENV}/bin/python"
#: Where Solr Orbit writes its reports. A fresh instance has no config file,
#: so this is the documented default rather than something read back.
REMOTE_REPORT = ".solr-orbit/benchmarks/test-runs/{test_run_id}/test_run.json"

#: Where Solr's data lives on a Solr node, always a bind mount into the
#: container.
#:
#: Bind-mounted rather than left to Docker. The Solr image declares
#: ``VOLUME /var/solr``, so without this Docker creates an *anonymous* volume
#: per container; ``docker rm`` does not remove it, and a six-version matrix
#: strands six copies of a 40 GB index on the disk. A named host path is also
#: the only way to put the index on a different volume from the root.
DATA_DIR = "/var/solr-data"

#: Where the *driver's* dedicated volume is mounted.
#:
#: Named separately because it holds something different: corpora, not an
#: index. One nyc_taxis is 84.6 GB on disk -- 79.8 GB decompressed plus the
#: 4.8 GB archive Solr Orbit keeps beside it -- and the cache is shared by
#: every cell and every workload in a session. On the root volume a matrix
#: of three large workloads would fill a 300 GB disk partway through a
#: download, hours in.
DRIVER_DATA_DIR = "/var/launchr-data"

#: Corpora live under the driver's data volume rather than at its root, so
#: the mount point itself stays empty and `lost+found`-style surprises do not
#: confuse Solr Orbit's cache.
CORPUS_SUBDIR = "corpora"

#: Prepares a Solr node: Docker, host tuning, and the data directory.
#:
#: Rendered per profile rather than fixed, because what it tunes is part of
#: what a result means -- a benchmark that does not say what its kernel was
#: doing cannot be compared with one that does.
SOLR_USER_DATA = """#!/bin/bash
set -euxo pipefail
dnf install -y docker
systemctl enable --now docker
usermod -aG docker ec2-user

# ---- host tuning -------------------------------------------------------
# Unpinned THP or a powersave governor are among the likelier causes of
# unexplained run-to-run variance. Each is applied only when the profile
# asked for it, and launchr reads the values back afterwards so the report
# records what the machine was actually doing, not what we requested.
{host_tuning}

{mount_data_volume}
# 8983 is the uid the Solr image runs as; the container cannot chown it itself.
chown -R 8983:8983 {data_dir}
chmod 775 {data_dir}
"""

#: Installs a Python new enough for Solr Orbit. Amazon Linux 2023 ships 3.9/3.11
#: and `requires-python` is >=3.12, so uv supplies a standalone interpreter
#: rather than hoping a distro package exists.
#:
#: `git` is not optional: Solr Orbit fetches the workloads repository with
#: `git clone` (utils/git.py), so without it every run fails at workload load
#: with "Error invoking 'git'".
#:
#: What is *not* installed here, and costs real time: `pbzip2`. Solr Orbit
#: hardcodes it for `.bz2` corpora (utils/io.py decompress) and falls back to
#: Python's single-threaded `bz2` when it is absent. Measured on this driver:
#: nyc_taxis is 4.8 GB compressed and 74.3 GiB -- just under 80 GB -- on disk,
#: and the stdlib path does ~2.6 GB/min on one core: 31 minutes, with the
#: other seven cores idle. Amazon Linux 2023 packages neither `pbzip2` nor
#: `lbzip2`, so it is not a one-line fix here.
#:
#: **The better answer is not to use bz2 at all.** The nyc_taxis workload
#: publishes a zstd variant of the same corpus behind a `use_zstd` parameter,
#: at essentially the same download size -- 4.81 GB against 4.82 GB. Measured
#: on 1000 real documents from this corpus, zstd decompresses about 73x
#: faster than bz2 (4156 MB/s against 57 MB/s), which turns half an hour into
#: roughly a minute. launchr asks for it by default -- see
#: `translate.DEFAULT_WORKLOAD_PARAMS` -- and a workload entry in the config
#: can override it:
#:
#:     workloads:
#:       - name: nyc_taxis
#:         workload_params: {use_zstd: false}
#:
#: One catch: only the *full* corpus has a zstd variant. `documents-1k.json.zst`
#: returns 403, which is why the default is off under `--test-mode`.
#:
#: `bzip2` is installed regardless, but it is single-threaded too and buys
#: nothing.
DRIVER_USER_DATA = """#!/bin/bash
set -euxo pipefail
dnf install -y tar gzip findutils git bzip2
export HOME=/home/ec2-user
curl -LsSf https://astral.sh/uv/install.sh | sh
install -o ec2-user -g ec2-user -d /home/ec2-user/.local/bin
chown -R ec2-user:ec2-user /home/ec2-user/.local /home/ec2-user/.cargo 2>/dev/null || true

{mount_data_volume}
mkdir -p {data_dir}/{corpus_subdir}
chown -R ec2-user:ec2-user {data_dir}
"""


#: Finds and mounts a dedicated data volume, if the profile attached one.
#:
#: The device is located by "the block device with no filesystem" rather than
#: by the /dev/sdb we asked EC2 for: on Nitro instances the kernel renames it
#: to /dev/nvme1n1, and the name we requested never appears.
MOUNT_DATA_VOLUME = """
mkdir -p {data_dir}
DATA_DISK=""
ROOT_DISK="$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null)"
for d in /dev/nvme?n1 /dev/xvd[b-z]; do
  [ -b "$d" ] || continue
  [ "$(basename "$d")" = "$ROOT_DISK" ] && continue
  if [ -z "$(lsblk -no FSTYPE "$d" 2>/dev/null)" ] && [ -z "$(lsblk -no MOUNTPOINT "$d" 2>/dev/null)" ]; then
    DATA_DISK="$d"; break
  fi
done
if [ -n "$DATA_DISK" ]; then
  mkfs.xfs -f "$DATA_DISK"
  echo "$DATA_DISK {data_dir} xfs defaults,noatime 0 2" >> /etc/fstab
  mount "{data_dir}"
fi
"""


class Ec2Provisioning:
    """Creates EC2 instances, runs the benchmark on a dedicated driver, destroys them."""

    API_VERSION: ClassVar[int] = 1
    name: ClassVar[str] = "ec2"
    creates_infrastructure: ClassVar[bool] = True

    def __init__(self, *, storage=None, session_id: str | None = None,
                 orbit_config: dict | None = None,
                 workloads: list[str] | None = None,
                 workload_repository_url: str | None = None):
        # Storage is optional so the strategy stays constructible by the plugin
        # registry's zero-argument probe; without it the ledger is skipped and
        # teardown falls back to tags alone.
        self.storage = storage
        self.session_id = session_id or "adhoc"
        #: Overrides for Solr Orbit's benchmark.ini on the driver, so a remote
        #: run is configured from launchr.yaml and nothing else.
        self.orbit_config = orbit_config or {}
        #: What the session will benchmark, so an auto-sized corpus volume
        #: can be big enough for it and no bigger.
        self.workloads = list(workloads or [])
        self.workload_repository_url = workload_repository_url
        self._key_dir: Path | None = None

    # -- lifecycle ---------------------------------------------------------

    def provision(self, profile: ProfileSpec, *, nodes: int) -> ProvisionedInfra:
        options = _options(profile)
        region = options["region"]
        aws_profile = options.get("aws_profile")
        ec2 = aws.client("ec2", region=region, profile=aws_profile)

        stack_id = f"{self.session_id}-{uuid.uuid4().hex[:4]}"
        subnet_id, _vpc_id, zone = _resolve_subnet(ec2, options)
        ami = options.get("ami") or aws.latest_ami(ec2)
        ssh_cidrs = _ssh_cidrs(options)

        # Recorded before anything exists, so a process killed mid-create is
        # still discoverable. See the ledger module's docstring.
        self._record_provisioning(stack_id, profile, options, region, zone, ami, nodes)

        security_group_id = None
        key_name = None
        created: list[str] = []
        try:
            security_group_id = aws.create_security_group(
                ec2, vpc_id=_vpc_id, session_id=stack_id,
                profile=profile.name, ssh_cidrs=ssh_cidrs,
                # The orchestrator health-checks Solr from outside the VPC.
                admin_ports=(profile.port,),
            )
            key_name, key_material = aws.create_key_pair(
                ec2, session_id=stack_id, profile=profile.name,
            )
            self._key_dir = Path(tempfile.mkdtemp(prefix=f"launchr-{stack_id}-"))
            key_path = write_private_key(key_material, self._key_dir, stack_id)

            common = dict(
                ami=ami, subnet_id=subnet_id, security_group_id=security_group_id,
                key_name=key_name, session_id=stack_id, profile=profile.name,
                volume_type=options["volume_type"],
            )
            tuning = _host_tuning(options)
            data_volume = _data_volume(options)
            driver_volume = self._resolve_driver_volume(options)
            solr_ids = aws.run_instances(
                ec2, count=nodes, role="solr", name_prefix=f"launchr-{stack_id}-solr",
                instance_type=options["instance_type"],
                user_data=SOLR_USER_DATA.format(
                    host_tuning=_render_host_tuning(tuning), data_dir=DATA_DIR,
                    mount_data_volume=MOUNT_DATA_VOLUME.format(data_dir=DATA_DIR)),
                volume_gb=int(options["volume_gb"]), data_volume=data_volume, **common,
            )
            # Accumulated as each batch launches, not after both: if the driver
            # cannot be launched -- no capacity for its type, an instance limit,
            # any transient API error -- the handler below must still know about
            # the Solr nodes that are already running and already billing.
            created += solr_ids
            driver_ids = aws.run_instances(
                ec2, count=1, role="driver", name_prefix=f"launchr-{stack_id}-driver",
                instance_type=options["driver_instance_type"],
                user_data=DRIVER_USER_DATA.format(
                    data_dir=DRIVER_DATA_DIR, corpus_subdir=CORPUS_SUBDIR,
                    mount_data_volume=MOUNT_DATA_VOLUME.format(data_dir=DRIVER_DATA_DIR)),
                volume_gb=int(options["driver_volume_gb"]),
                data_volume=driver_volume, **common,
            )
            created += driver_ids
            self._record_instances(stack_id, created)

            logger.info("Waiting for %d instance(s) to reach running", len(created))
            described = {d["InstanceId"]: d for d in aws.wait_until_running(ec2, created)}

            solr_nodes = [
                aws.to_instance(described[i], role="solr", name=f"solr-{n}")
                for n, i in enumerate(solr_ids, start=1)
            ]
            driver = aws.to_instance(described[driver_ids[0]], role="driver", name="driver")

            infra = _to_infra(
                profile, options, stack_id, solr_nodes, driver, key_path,
                region=region, zone=zone, ami=ami, subnet_id=subnet_id,
                security_group_id=security_group_id, key_name=key_name,
                aws_profile=aws_profile, ssh_cidrs=ssh_cidrs,
                data_volume=data_volume, driver_data_volume=driver_volume,
                host_tuning=tuning,
            )
            self._wait_for_ssh(infra)
            # Read the tuning back rather than trust that it applied: a
            # setting the kernel refused, or an instance with no cpufreq, is
            # exactly what a reader needs to know and cannot infer from the
            # request.
            infra.metadata["host_tuning_applied"] = self._observed_tuning(infra)
            return infra
        except Exception:
            # A half-built stack is the expensive failure: instances billing
            # with nothing to drive them. Clean up here rather than relying on
            # the orchestrator's finally, which only sees infra we returned.
            logger.error("Provisioning %s failed; cleaning up what was created", stack_id)
            self._destroy(ec2, stack_id, created, security_group_id, key_name,
                          reason="failed provisioning")
            raise

    def run_on_driver(self, infra: ProvisionedInfra, invocation: OrbitInvocation) -> OrbitResult:
        driver = infra.driver
        if driver is None or driver.ssh is None:
            raise ProvisioningError("This infrastructure has no driver to run the benchmark on")
        session = self._session(driver.ssh, infra)
        home = self._home(session, infra)
        self._install_orbit(session, infra, home)
        self._write_orbit_ini(session, home, infra)

        argv = _remote_argv(invocation.argv, home)
        remote = " ".join(shlex.quote(a) for a in argv)
        logger.info("Running Solr Orbit on %s", driver.ssh.host)

        invocation.log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        # Two failure shapes, and they must not be conflated.
        #
        # A *non-zero exit* is a failed benchmark, full stop. An earlier
        # version forgave any non-zero exit whenever a report file existed,
        # on the theory that the report is the contract. That was wrong: Solr
        # Orbit exits non-zero having still written a skeleton report with no
        # task metrics in it, and the cell was then published as completed
        # with no data in it.
        #
        # A *hang* is the one case worth forgiving, and it is the real shape
        # of apache/solr-orbit#106: the benchmark finishes, the report is on
        # disk, and the actor system never exits. Over SSH that surfaces as a
        # timeout rather than an exit code, which is what distinguishes the
        # two here -- `run_locally` tells them apart by watching the process.
        timed_out = False
        try:
            result = session.run(
                f"cd {shlex.quote(home)} && {remote} 2>&1",
                timeout=_benchmark_timeout(), check=False,
            )
        except ProvisioningError as exc:
            if "timed out" not in str(exc):
                raise
            timed_out = True
            result = CommandResult(returncode=124, stdout="", stderr=str(exc))

        elapsed = time.monotonic() - started
        invocation.log_path.write_text(
            f"$ {remote}\n\n{result.stdout}{result.stderr}", encoding="utf-8",
        )
        logger.info("Solr Orbit exited %d after %.0fs", result.returncode, elapsed)

        report = self._fetch_report(session, invocation, home)
        returncode = result.returncode
        if timed_out and report is not None:
            logger.warning(
                "Solr Orbit wrote its report but never exited; treating the cell as "
                "successful. See apache/solr-orbit#106."
            )
            returncode = 0
        if report is None and returncode != 0:
            tail = (result.stdout or result.stderr or "").strip().splitlines()[-25:]
            logger.error("Solr Orbit produced no report. Last output:\n%s", "\n".join(tail))
        return OrbitResult(
            returncode=returncode,
            test_run_id=invocation.test_run_id,
            report=report,
            log_path=invocation.log_path,
        )

    def teardown(self, infra: ProvisionedInfra) -> None:
        """Destroy everything provision created. Never raises."""
        handles = infra.handles or {}
        stack_id = handles.get("stack_id")
        if not stack_id:
            logger.debug("Nothing to tear down: no stack recorded on this infrastructure")
            return
        try:
            ec2 = aws.client("ec2", region=handles["region"], profile=handles.get("aws_profile"))
        except Exception as exc:  # noqa: BLE001 - teardown runs in a finally
            logger.error(
                "Could not reach EC2 to tear down %s: %s. Run `launchr teardown` once "
                "credentials work -- the instances are tagged and recorded.", stack_id, exc,
            )
            return
        self._destroy(
            ec2, stack_id,
            [i.instance_id for i in handles.get("instances", [])],
            handles.get("security_group_id"), handles.get("key_name"),
            reason="completed",
        )

    # -- internals ---------------------------------------------------------

    def _destroy(self, ec2, stack_id: str, instance_ids: list[str],
                 security_group_id: str | None, key_name: str | None, *, reason: str) -> None:
        try:
            aws.terminate(ec2, instance_ids)
            if security_group_id:
                aws.delete_security_group(ec2, security_group_id)
            if key_name:
                aws.delete_key_pair(ec2, key_name)
        except Exception as exc:  # noqa: BLE001 - teardown must never raise
            logger.error(
                "Teardown of %s did not finish cleanly: %s. "
                "Run `launchr teardown` to reclaim whatever is left.", stack_id, exc,
            )
            return
        finally:
            self._remove_key_file()
        if self.storage is not None:
            ledger.record_released(self.storage, stack_id, {
                "reason": reason,
                "instance_ids": instance_ids,
            })

    def _remove_key_file(self) -> None:
        if self._key_dir is None:
            return
        try:
            for path in self._key_dir.iterdir():
                path.unlink(missing_ok=True)
            self._key_dir.rmdir()
        except OSError as exc:
            logger.debug("Could not remove the ephemeral key directory: %s", exc)
        self._key_dir = None

    def _record_provisioning(self, stack_id, profile, options, region, zone, ami, nodes) -> None:
        if self.storage is None:
            return
        try:
            ledger.record_provisioned(self.storage, stack_id, {
                "session_id": self.session_id,
                "strategy": self.name,
                "profile": profile.name,
                "region": region,
                "availability_zone": zone,
                "ami": ami,
                "nodes": nodes,
                "instance_type": options["instance_type"],
                "driver_instance_type": options["driver_instance_type"],
                "instance_ids": [],
            })
        except Exception as exc:  # noqa: BLE001 - a ledger failure must not stop a run
            logger.warning("Could not record provisioning of %s: %s", stack_id, exc)

    def _record_instances(self, stack_id: str, instance_ids: list[str]) -> None:
        if self.storage is not None:
            ledger.record_instances(self.storage, stack_id, instance_ids)

    def _session(self, spec: SshSpec, infra: ProvisionedInfra) -> SshSession:
        return SshSession(spec, known_hosts=Path(infra.handles["known_hosts"]))

    def _resolve_driver_volume(self, options: dict) -> dict | None:
        """The driver's corpus volume, sizing it from the workloads if asked."""
        spec = _data_volume(options, key="driver_data_volume",
                            defaults=DEFAULT_DRIVER_DATA_VOLUME)
        if spec is None or str(spec.get("size_gb")).lower() != "auto":
            return spec

        repo = self.workload_repository_url or DEFAULT_WORKLOAD_REPO
        sized = _auto_corpus_size_gb(self.workloads, repo) if self.workloads else None
        if sized is None:
            logger.info("Sizing the corpus volume at the %d GB fallback", 
                        FALLBACK_CORPUS_VOLUME_GB)
            sized = FALLBACK_CORPUS_VOLUME_GB
        else:
            logger.info("Sized the corpus volume at %d GB for %s "
                        "(twice what the workloads declare)",
                        sized, ", ".join(self.workloads))
        return {**spec, "size_gb": sized}

    def _observed_tuning(self, infra: ProvisionedInfra) -> dict:
        """What the Solr nodes' kernels actually report, after user-data ran."""
        node = next((n for n in infra.nodes if n.ssh), None)
        if node is None:
            return {}
        probe = (
            'printf "thp=%s\\nswappiness=%s\\ngovernor=%s\\ndata_fs=%s\\n" '
            '"$(cat /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null | '
            'grep -oE \'\\[[a-z]+\\]\' | tr -d \'[]\')" '
            '"$(cat /proc/sys/vm/swappiness 2>/dev/null)" '
            '"$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo none)" '
            f'"$(findmnt -no SOURCE,FSTYPE {DATA_DIR} 2>/dev/null || echo root-volume)"'
        )
        try:
            result = self._session(node.ssh, infra).run(probe, check=False, timeout=60)
        except Exception as exc:  # noqa: BLE001 - provenance is never worth failing a run
            logger.debug("Could not read back host tuning: %s", exc)
            return {}
        observed = {}
        for line in (result.stdout or "").splitlines():
            key, _, value = line.partition("=")
            if key:
                observed[key.strip()] = value.strip()
        if observed:
            logger.info("Host tuning as applied: %s",
                        ", ".join(f"{k}={v}" for k, v in sorted(observed.items())))
        return observed

    def _wait_for_ssh(self, infra: ProvisionedInfra) -> None:
        targets = [n for n in infra.nodes if n.ssh] + ([infra.driver] if infra.driver else [])
        for node in targets:
            if node is None or node.ssh is None:
                continue
            logger.info("Waiting for %s (%s) to finish booting", node.name, node.ssh.host)
            self._session(node.ssh, infra).wait_until_ready()

    def _home(self, session: SshSession, infra: ProvisionedInfra) -> str:
        """The driver's home directory, resolved once and cached.

        Asked rather than assumed: the SSH user is AMI-dependent and so is its
        home, and every other remote path is built from this one.
        """
        cached = infra.handles.get("driver_home")
        if cached:
            return cached
        # A raw string, so the remote shell expands $HOME. Passing it through
        # the quoted list form would send the four characters "$HOME".
        home = session.run('printf %s "$HOME"').stdout.strip()
        if not home.startswith("/"):
            raise ProvisioningError(
                f"The driver reported a home directory of {home!r}, which is not an absolute path."
            )
        infra.handles["driver_home"] = home
        return home

    def _install_orbit(self, session: SshSession, infra: ProvisionedInfra, home: str) -> None:
        """Put this launchr's own Solr Orbit on the driver.

        The wheel is built from the working tree rather than pulled from PyPI,
        so the driver runs exactly the code the operator is testing -- which is
        the whole point when the thing under development is launchr itself.
        Idempotent: a second cell in the same session reuses the install.
        """
        python = f"{home}/{REMOTE_PYTHON}"
        if session.run(["test", "-x", python], check=False).ok:
            logger.debug("Solr Orbit already installed on %s", session.spec.host)
            return

        wheel = Path(infra.handles.get("wheel") or _build_wheel())
        remote_wheel = f"{home}/{wheel.name}"
        logger.info("Installing %s on %s", wheel.name, session.spec.host)
        session.upload(wheel, remote_wheel)
        uv = f"{home}/.local/bin/uv"
        session.run([
            uv, "venv", "--python", "3.12", f"{home}/{REMOTE_VENV}",
        ], timeout=900)
        session.run([
            uv, "pip", "install", "--python", python, remote_wheel,
        ], timeout=900)
        version = session.run(
            [python, "-c", "import solrorbit; print(solrorbit.__version__)"], check=False)
        logger.info("Driver has Solr Orbit %s", (version.stdout or "?").strip())

    def _write_orbit_ini(self, session: SshSession, home: str,
                         infra: ProvisionedInfra) -> None:
        """Place Solr Orbit's benchmark.ini on the driver before it runs.

        Written every cell rather than once: it is cheap, and it means a
        driver that somehow lost the file -- or that Solr Orbit bootstrapped
        itself on a previous cell -- still runs the configuration this
        session asked for.
        """
        # Point Solr Orbit's corpus cache at the driver's data volume when
        # there is one. Left at its default it lands under the home
        # directory on the root disk, where one nyc_taxis is 84.6 GB and a
        # multi-workload matrix runs out of space partway through a
        # download. An explicit setting in launchr.yaml still wins.
        overrides = dict(self.orbit_config)
        corpus_dir = (infra.metadata or {}).get("corpus_dir")
        if corpus_dir and "local.dataset.cache" not in (overrides.get("benchmarks") or {}):
            benchmarks = dict(overrides.get("benchmarks") or {})
            benchmarks["local.dataset.cache"] = corpus_dir
            overrides["benchmarks"] = benchmarks
        try:
            contents = orbit_ini.render(home, overrides)
        except Exception as exc:  # noqa: BLE001 - never fail a run over provenance
            logger.warning("Could not render benchmark.ini, letting Solr Orbit "
                           "bootstrap its own defaults: %s", exc)
            return

        remote = f"{home}/{orbit_ini.CONFIG_DIRNAME}/{orbit_ini.CONFIG_FILENAME}"
        with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False) as handle:
            handle.write(contents)
            local = Path(handle.name)
        try:
            session.run(["mkdir", "-p", f"{home}/{orbit_ini.CONFIG_DIRNAME}"])
            session.upload(local, remote)
            applied = orbit_ini.describe(overrides)
            infra.metadata["orbit_config"] = applied
            logger.info("Wrote %s (%s)", remote,
                        ", ".join(f"{s}.{k}={v}" for s, kv in sorted(applied.items())
                                  for k, v in sorted(kv.items())) or "defaults only")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write %s: %s", remote, exc)
        finally:
            local.unlink(missing_ok=True)

    def _fetch_report(self, session: SshSession, invocation: OrbitInvocation,
                      home: str) -> bytes | None:
        remote = f"{home}/{REMOTE_REPORT.format(test_run_id=invocation.test_run_id)}"
        if not session.run(["test", "-f", remote], check=False).ok:
            return None
        local = invocation.log_path.parent / f"{invocation.test_run_id}.json"
        try:
            session.download(remote, local)
            return local.read_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not fetch the report from the driver: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _data_volume(options: dict, *, key: str = "data_volume",
                 defaults: dict | None = None) -> dict | None:
    """A dedicated data volume spec, or ``None`` to use the root volume."""
    raw = options.get(key)
    spec = {**(defaults if defaults is not None else DEFAULT_DATA_VOLUME), **(raw or {})}
    mode = str(spec.get("mode", "ebs")).lower()
    if mode == "root":
        return None
    if mode != "ebs":
        raise ConfigError(
            f"{key}.mode must be 'ebs' or 'root', got {mode!r}"
        )
    size = spec.get("size_gb")
    # "auto" is resolved later, once the session's workloads are known.
    if str(size).lower() != "auto":
        try:
            if int(size) < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise ConfigError(
                f"{key}.size_gb must be a positive number of GB or 'auto', got {size!r}"
            ) from None
    return spec


#: Floor for an auto-sized corpus volume. Below this the volume costs
#: nothing to round up and a small miscalculation would be fatal.
#: Where workloads come from when nothing says otherwise; matches Solr
#: Orbit's own bundled default.
DEFAULT_WORKLOAD_REPO = "https://github.com/apache/solr-orbit-workloads"

MIN_CORPUS_VOLUME_GB = 50

#: Used when the corpora cannot be measured at all.
FALLBACK_CORPUS_VOLUME_GB = 500

#: Pulled out of the workload template with a regex rather than by rendering
#: it. Rendering needs Jinja, the workloads repository on disk and a full
#: Solr Orbit config; all we want is an order of magnitude to size a disk
#: with, and the answer is then doubled anyway.
_BYTES_FIELD = re.compile(r'"(?:un)?compressed-bytes"\s*:\s*(\d+)')


def _auto_corpus_size_gb(workloads: list[str], repo_url: str,
                         timeout: float = 10.0) -> int | None:
    """Twice what the named workloads' corpora declare, in GB.

    Doubled because Solr Orbit keeps the archive *and* the decompressed file:
    nyc_taxis is 4.8 GB compressed and 79.8 GB expanded, 84.6 GB on disk, and
    a volume sized for the expanded file alone fills up at the end of the
    download. The declared numbers already include both, so the doubling is
    headroom on top -- for the offset table, for a second workload added
    later, and for being wrong.

    Returns ``None`` when the sizes cannot be read, so the caller can fall
    back rather than provision something too small.
    """
    base = _raw_base_url(repo_url)
    if not base:
        return None
    total = 0
    for name in workloads:
        declared = _declared_corpus_bytes(f"{base}/{name}/workload.json", timeout)
        if declared is None:
            logger.info("Could not read corpus sizes for workload %r; "
                        "falling back to a fixed volume size", name)
            return None
        total += declared
    if total <= 0:
        return None
    gb = math.ceil(total * 2 / 1_000_000_000)
    return max(gb, MIN_CORPUS_VOLUME_GB)


def _raw_base_url(repo_url: str) -> str | None:
    """Turn a GitHub repository URL into one that serves raw files."""
    match = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", str(repo_url or "").strip())
    if not match:
        return None
    return f"https://raw.githubusercontent.com/{match.group(1)}/{match.group(2)}/main"


def _declared_corpus_bytes(url: str, timeout: float) -> int | None:
    """Sum every byte count a workload template declares, or ``None``."""
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 - sizing is best effort
        logger.debug("Could not fetch %s: %s", url, exc)
        return None
    found = [int(m) for m in _BYTES_FIELD.findall(body)]
    return sum(found) if found else None


def _host_tuning(options: dict) -> dict:
    """The kernel settings to apply, with unset values dropped."""
    raw = options.get("host_tuning")
    if raw is None:
        return dict(DEFAULT_HOST_TUNING)
    if not isinstance(raw, dict):
        raise ConfigError(
            f"options.host_tuning must be a mapping, got {type(raw).__name__}"
        )
    unknown = set(raw) - set(DEFAULT_HOST_TUNING)
    if unknown:
        raise ConfigError(
            f"Unknown host_tuning keys: {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(sorted(DEFAULT_HOST_TUNING))}."
        )
    merged = {**DEFAULT_HOST_TUNING, **raw}
    return {k: v for k, v in merged.items() if v is not None}


#: The Linux cpufreq governors. ``cpu_governor`` reaches a root shell on every
#: node, so it is checked against this set rather than merely quoted.
CPU_GOVERNORS = frozenset({
    "performance", "powersave", "ondemand", "conservative", "schedutil", "userspace",
})


def _render_host_tuning(tuning: dict) -> str:
    """Shell that applies ``tuning``, skipping what this machine cannot do."""
    lines: list[str] = []
    thp = tuning.get("transparent_hugepages")
    if thp:
        if thp not in ("never", "madvise", "always"):
            raise ConfigError(
                f"host_tuning.transparent_hugepages must be never, madvise or always, got {thp!r}"
            )
        lines.append(
            f'echo {thp} > /sys/kernel/mm/transparent_hugepage/enabled || true\n'
            f'echo {thp} > /sys/kernel/mm/transparent_hugepage/defrag || true'
        )
    swappiness = tuning.get("swappiness")
    if swappiness is not None:
        lines.append(f"sysctl -w vm.swappiness={int(swappiness)} || true")
    governor = tuning.get("cpu_governor")
    if governor:
        if governor not in CPU_GOVERNORS:
            # Validated rather than quoted: this is interpolated into a script
            # cloud-init runs as root, and the only safe values are governor
            # names. Its siblings above fail closed the same way, so a typo is
            # a config error rather than a different command.
            raise ConfigError(
                f"host_tuning.cpu_governor must be one of "
                f"{', '.join(sorted(CPU_GOVERNORS))}, got {governor!r}"
            )
        # Many instance families expose no cpufreq at all; absence is not a
        # failure, it just means the setting does not apply here.
        lines.append(
            f'for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do\n'
            f'  [ -w "$g" ] && echo {governor} > "$g" || true\n'
            f'done'
        )
    return "\n".join(lines) if lines else "# host_tuning: nothing requested"


def _options(profile: ProfileSpec) -> dict:
    unknown = set(profile.options) - KNOWN_OPTIONS
    if unknown:
        raise ConfigError(
            f"Provisioning profile {profile.name!r} has unknown ec2 options: "
            f"{', '.join(sorted(unknown))}. Known: {', '.join(sorted(KNOWN_OPTIONS))}."
        )
    return {**DEFAULTS, **dict(profile.options)}


def _resolve_subnet(ec2, options: dict) -> tuple[str, str, str]:
    if options.get("subnet_id"):
        vpc_id, zone = aws.subnet_details(ec2, options["subnet_id"])
        return options["subnet_id"], vpc_id, zone
    return aws.default_subnet(ec2, availability_zone=options.get("availability_zone"))


def _to_infra(profile, options, stack_id, solr_nodes, driver, key_path, *,
              region, zone, ami, subnet_id, security_group_id, key_name,
              aws_profile, ssh_cidrs, data_volume=None, driver_data_volume=None,
              host_tuning=None) -> ProvisionedInfra:
    user = options["ssh_user"]
    known_hosts = key_path.parent / "known_hosts"

    def ssh_for(instance):
        return SshSpec(host=instance.ssh_host, user=user, key_path=str(key_path))

    nodes = [
        NodeHandle(
            name=instance.name,
            # Solr binds and is reached on the private address: the driver is
            # in the same subnet, and routing load over the public interface
            # would measure the internet gateway rather than Solr.
            endpoint=SolrEndpoint(scheme="http", host=instance.private_ip, port=profile.port),
            ssh=ssh_for(instance),
        )
        for instance in solr_nodes
    ]
    return ProvisionedInfra(
        profile=profile,
        strategy=Ec2Provisioning.name,
        install_method=profile.install_method,
        nodes=nodes,
        driver=NodeHandle(name="driver", endpoint=None, ssh=ssh_for(driver)),
        metadata={
            "provider": "aws-ec2",
            "region": region,
            "availability_zone": zone,
            "ami": ami,
            "subnet_id": subnet_id,
            "nodes": len(solr_nodes),
            "instance_type": options["instance_type"],
            "driver_instance_type": options["driver_instance_type"],
            "volume": {"type": options["volume_type"], "size_gb": int(options["volume_gb"])},
            # Where the index actually sits, and on what. A result produced
            # on the gp3 baseline is not comparable with one produced at
            # 16000 IOPS, so this belongs in the report rather than in a
            # config file nobody reads alongside the chart.
            "data_volume": dict(data_volume) if data_volume else {"mode": "root"},
            "data_dir": DATA_DIR,
            "driver_data_volume": (dict(driver_data_volume) if driver_data_volume
                                   else {"mode": "root"}),
            "corpus_dir": (f"{DRIVER_DATA_DIR}/{CORPUS_SUBDIR}" if driver_data_volume
                           else None),
            "host_tuning_requested": dict(host_tuning or {}),
            "instances": [
                {"name": i.name, "id": i.instance_id, "type": i.instance_type,
                 "az": i.availability_zone, "private_ip": i.private_ip}
                for i in [*solr_nodes, driver]
            ],
        },
        handles={
            "stack_id": stack_id,
            "region": region,
            "aws_profile": aws_profile,
            "security_group_id": security_group_id,
            "key_name": key_name,
            "key_path": str(key_path),
            "known_hosts": str(known_hosts),
            "ssh_cidrs": list(ssh_cidrs),
            "instances": [*solr_nodes, driver],
        },
    )


def _remote_argv(argv: list[str], home: str) -> list[str]:
    """Retarget a locally-built argv at the driver's interpreter."""
    if argv and argv[0] == sys.executable:
        return [f"{home}/{REMOTE_PYTHON}", *argv[1:]]
    return list(argv)


def _benchmark_timeout() -> int:
    """How long a single cell may take, in seconds.

    Six hours by default: a full nyc_taxis corpus is hours of indexing, and a
    timeout that fires on a legitimate run throws away the most expensive
    thing launchr produces.
    """
    return int(os.environ.get("LAUNCHR_BENCHMARK_TIMEOUT", "21600"))


def _project_root() -> Path:
    """The directory holding pyproject.toml.

    Walked for rather than counted with ``parents[n]``: an off-by-one there
    pointed ``uv build`` at the package directory instead of the project and
    failed every cell, and the index would have to be edited again the moment
    this module moves.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ProvisioningError(
        "Could not find pyproject.toml above "
        f"{Path(__file__).resolve()}, so launchr cannot build a wheel for the driver. "
        "Set options.wheel to a prebuilt wheel."
    )


def _build_wheel() -> Path:
    """Build a wheel of the working tree, for installing on the driver."""
    root = _project_root()
    out = Path(tempfile.mkdtemp(prefix="launchr-wheel-"))
    logger.info("Building a Solr Orbit wheel from %s", root)
    completed = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise ProvisioningError(
            f"Could not build a Solr Orbit wheel to install on the driver:\n"
            f"{completed.stderr.strip()[:1000]}"
        )
    wheels = sorted(out.glob("*.whl"))
    if not wheels:
        raise ProvisioningError(f"uv build produced no wheel in {out}")
    return wheels[0]


def _ssh_cidrs(options: dict) -> list[str]:
    """Every range allowed to reach SSH and the Solr admin port.

    The first entry is this machine, detected now -- which is the right
    default and also the fragile part: a public address can change mid-run
    (a DHCP renewal, a VPN toggle, moving networks), and when it does a `/32`
    captured at provision time silently stops matching. The control
    connection then dies and an hours-long benchmark fails at the transport
    layer with nothing wrong with it.

    ``extra_ssh_cidrs`` is how a profile names stable ranges to open
    *alongside* it -- an office range, a VPN pool, a bastion -- so a changing
    laptop address is an inconvenience rather than a lost run.
    """
    primary = options.get("ssh_cidr") or f"{_public_ip()}/32"
    extra = options.get("extra_ssh_cidrs") or []
    if isinstance(extra, str):
        # A single range written without a list is the obvious mistake to
        # forgive; splitting on commas also makes it settable from one
        # environment variable.
        extra = [part.strip() for part in extra.split(",") if part.strip()]
    if not isinstance(extra, (list, tuple)):
        raise ConfigError(
            f"options.extra_ssh_cidrs must be a list of CIDR ranges, got {type(extra).__name__}"
        )

    cidrs: list[str] = []
    for value in [primary, *extra]:
        text = _normalise_cidr(str(value).strip())
        if text and text not in cidrs:
            cidrs.append(text)
    return cidrs


def _normalise_cidr(value: str) -> str:
    """Return ``value`` as a CIDR range, rejecting what is not one.

    A bare address is the obvious slip and is widened to a single-host range
    rather than refused: AWS requires the prefix and its own error for a
    missing one is not especially clear. Anything genuinely malformed fails
    here, where the message can name the offending value.
    """
    import ipaddress

    if not value:
        return ""
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ConfigError(f"{value!r} is not a valid CIDR range: {exc}") from None
    # strict=False already collapsed a host address to /32 or /128; rendering
    # the network back is what adds the prefix AWS insists on.
    return str(network)


def _public_ip() -> str:
    """This machine's public address, for the SSH ingress rule.

    Narrowing SSH to one address is the difference between a benchmark host
    and an open port. If it cannot be determined, that is a hard failure
    rather than a fallback to 0.0.0.0/0 -- set ``options.ssh_cidr`` instead.
    """
    import urllib.request

    for url in ("https://checkip.amazonaws.com", "https://api.ipify.org"):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                address = response.read().decode().strip()
            if address:
                return address
        except Exception as exc:  # noqa: BLE001 - try the next source
            logger.debug("Could not read a public IP from %s: %s", url, exc)
    raise ProvisioningError(
        "Could not determine this machine's public IP for the SSH rule. "
        "Set options.ssh_cidr on the profile."
    )
