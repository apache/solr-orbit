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
"""Running commands on a provisioned instance.

OpenSSH rather than Fabric/paramiko: no new dependency, and ``ssh`` is present
anywhere this could plausibly run. The cost is that arguments cross a shell on
the far side, so every remote command is built from a list and quoted with
:func:`shlex.quote` -- never interpolated into a string.

**Host keys.** A freshly created instance has a host key nothing has seen
before, so strict checking cannot succeed on a first connection. Rather than
disable checking globally, each run gets its own throwaway ``known_hosts``
file: the first connection is trust-on-first-use within that file, and every
later connection in the same run is verified against it. A key that changes
mid-run -- which would mean something replaced the host under us -- still
fails. ``~/.ssh/known_hosts`` is never touched, so a benchmark run does not
leave a trail of dead host keys in the operator's own file.
"""

import logging
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from solrorbit.tools.launchr.errors import ProvisioningError
from solrorbit.tools.launchr.models import SshSpec

logger = logging.getLogger(__name__)

#: How long a single SSH command may take before it is abandoned. Generous:
#: this also covers `uv pip install`, which pulls a lot on a cold instance.
DEFAULT_TIMEOUT = 900

#: How long to keep retrying the first connection while cloud-init finishes.
BOOT_TIMEOUT = 300
_BOOT_POLL = 5


@dataclass
class CommandResult:
    """What a remote command did."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SshSession:
    """Commands and file transfers against one host."""

    def __init__(self, spec: SshSpec, *, known_hosts: Path, connect_timeout: int = 15):
        self.spec = spec
        self.known_hosts = Path(known_hosts)
        self.connect_timeout = connect_timeout

    def __repr__(self) -> str:
        return f"SshSession({self.spec.user}@{self.spec.host})"

    @property
    def _base_options(self) -> list[str]:
        options = [
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.connect_timeout}",
            # Trust on first use, but only within this run's own file.
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={self.known_hosts}",
            # An instance that reboots mid-run would otherwise hang the client.
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=6",
        ]
        if self.spec.key_path:
            # IdentitiesOnly stops ssh offering every key in the agent first,
            # which on a loaded agent trips MaxAuthTries before reaching ours.
            options += ["-i", self.spec.key_path, "-o", "IdentitiesOnly=yes"]
        if self.spec.port != 22:
            options += ["-p", str(self.spec.port)]
        return options

    @property
    def target(self) -> str:
        return f"{self.spec.user}@{self.spec.host}"

    def run(self, command: list[str] | str, *, timeout: int = DEFAULT_TIMEOUT,
            check: bool = True, log_output: bool = False) -> CommandResult:
        """Run one command remotely.

        ``command`` as a list is quoted for the remote shell. A plain string is
        passed through untouched, which is for scripts that genuinely need
        shell syntax -- pipes, redirection, ``&&``.
        """
        remote = command if isinstance(command, str) else " ".join(shlex.quote(c) for c in command)
        argv = ["ssh", *self._base_options, self.target, remote]
        logger.debug("ssh %s: %s", self.spec.host, remote)
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProvisioningError(
                f"Command on {self.target} timed out after {timeout}s: {remote}"
            ) from exc

        result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
        if log_output and result.stdout.strip():
            for line in result.stdout.rstrip().splitlines():
                logger.info("[%s] %s", self.spec.host, line)
        if check and not result.ok:
            raise ProvisioningError(
                f"Command failed on {self.target} (exit {result.returncode}): {remote}\n"
                f"{(result.stderr or result.stdout).strip()[:2000]}"
            )
        return result

    def upload(self, local: Path, remote: str, *, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Copy a local file to the instance."""
        argv = ["scp", *self._base_options, str(local), f"{self.target}:{remote}"]
        self._transfer(argv, f"uploading {local.name} to {self.target}:{remote}", timeout)

    def download(self, remote: str, local: Path, *, timeout: int = DEFAULT_TIMEOUT) -> None:
        """Copy a file off the instance."""
        local.parent.mkdir(parents=True, exist_ok=True)
        argv = ["scp", *self._base_options, f"{self.target}:{remote}", str(local)]
        self._transfer(argv, f"downloading {remote} from {self.target}", timeout)

    def _transfer(self, argv: list[str], what: str, timeout: int) -> None:
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProvisioningError(f"Timed out {what}") from exc
        if completed.returncode != 0:
            raise ProvisioningError(
                f"Failed {what} (exit {completed.returncode}): "
                f"{(completed.stderr or completed.stdout).strip()[:1000]}"
            )

    def wait_until_ready(self, *, timeout: int = BOOT_TIMEOUT) -> None:
        """Block until the instance accepts SSH and cloud-init has finished.

        Two separate waits, because they fail differently. SSH accepting a
        connection only means sshd is up; the user-data script that installs
        Docker may still be running, and a deploy that races it fails with a
        baffling "docker: command not found".
        """
        deadline = time.monotonic() + timeout
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.run(["true"], timeout=self.connect_timeout + 10, check=True)
                break
            except ProvisioningError as exc:
                last = exc
                time.sleep(_BOOT_POLL)
        else:
            raise ProvisioningError(
                f"{self.target} did not accept SSH within {timeout}s: {last}"
            )

        # `cloud-init status --wait` blocks until user-data is done and exits
        # non-zero if it failed, which is exactly the signal we want. It is
        # absent on some images, so a missing binary is not fatal.
        result = self.run(
            "command -v cloud-init >/dev/null 2>&1 && cloud-init status --wait || true",
            timeout=timeout, check=False,
        )
        if "status: error" in (result.stdout or ""):
            raise ProvisioningError(
                f"cloud-init failed on {self.target}; the instance is up but not configured. "
                f"Check /var/log/cloud-init-output.log. Output: {result.stdout.strip()[:500]}"
            )


def write_private_key(material: str, directory: Path, name: str) -> Path:
    """Write an ephemeral private key where only this user can read it.

    ``ssh`` refuses a key whose file is group- or world-readable, so the mode
    is not advisory. Created with ``0o600`` from the start rather than
    chmod-ed afterwards, which would leave a window where it is not.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.pem"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(material if material.endswith("\n") else material + "\n")
    return path
