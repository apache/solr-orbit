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
"""Build and run the Solr Orbit command line.

Every launchr cell, on every kind of infrastructure, runs the same shape of
command::

    python -m solrorbit.benchmark run --pipeline=benchmark-only --target-hosts=...

Solr Orbit is invoked through ``sys.executable -m`` rather than a ``solr-orbit``
binary on ``PATH``, so launchr always drives the interpreter and the Solr Orbit
version it was itself installed with.

Two things are deliberately absent from the argv:

``--cluster-config``
    Solr Orbit does not apply a cluster-config under ``benchmark-only`` -- it
    only records the names in the report. launchr applies heap/GC/opts to the
    Solr process itself and records what it applied.

``--distribution-version``
    Solr Orbit derives it from the live cluster, which is more trustworthy than
    anything launchr could assert.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from solrorbit import paths
from solrorbit.tools.launchr.errors import BenchmarkError, ConfigError
from solrorbit.tools.launchr.models import (
    MatrixCell,
    OrbitInvocation,
    OrbitResult,
    SolrDeployment,
)

logger = logging.getLogger(__name__)

ORBIT_MODULE = "solrorbit.benchmark"
PIPELINE = "benchmark-only"

#: Report filenames Solr Orbit writes, by whether the run was aggregated.
TEST_RUN_REPORT = "test_run.json"
AGGREGATED_REPORT = "aggregated_test_run.json"


# ---------------------------------------------------------------------------
# Where Solr Orbit puts its reports
# ---------------------------------------------------------------------------


def orbit_root() -> Path:
    """Return Solr Orbit's ``node.root.dir``.

    Read from ``~/.solr-orbit/benchmark.ini`` (honouring ``BENCHMARK_HOME``) so
    launchr follows the same configuration the benchmark itself does. Falls back
    to the documented default when no config file exists yet, which is the case
    on a machine that has never run Solr Orbit.
    """
    # Imported lazily: solrorbit.config pulls in a good deal of the package.
    from solrorbit import config as orbit_config

    config_file = orbit_config.ConfigFile()
    if config_file.present:
        try:
            parser = config_file.load()
            root = parser.get("node", "root.dir", fallback=None)
            if root:
                return Path(os.path.expanduser(root))
        except Exception as exc:  # noqa: BLE001 - a malformed ini is not fatal here
            logger.warning("Could not read node.root.dir from %s: %s", config_file.location, exc)
    return Path(paths.benchmark_confdir()) / "benchmarks"


def report_path(test_run_id: str, *, aggregated: bool = False, root: Path | None = None) -> Path:
    """Return the path Solr Orbit writes a given run's report to."""
    base = root if root is not None else orbit_root()
    if aggregated:
        return base / "aggregated_results" / test_run_id / AGGREGATED_REPORT
    return base / "test-runs" / test_run_id / TEST_RUN_REPORT


# ---------------------------------------------------------------------------
# Building the argv
# ---------------------------------------------------------------------------


def _validate_tag(key: str, value: str) -> None:
    """Reject user tags Solr Orbit's parser cannot round-trip.

    ``extract_user_tags_from_string`` splits on ``,`` and then on ``:``, so a
    key or value containing either is silently mangled or raises deep inside
    Solr Orbit. Failing here names the offending tag.
    """
    for field, text in (("key", key), ("value", value)):
        if "," in text or ":" in text:
            raise ConfigError(
                f"User tag {field} {text!r} contains ',' or ':', which Solr Orbit's "
                f"--user-tag parser uses as separators. Choose a different {field}."
            )


def render_user_tags(tags: dict[str, object]) -> str:
    """Render a tag dict as Solr Orbit's ``--user-tag`` format."""
    parts = []
    for key, value in tags.items():
        text = "" if value is None else str(value)
        _validate_tag(str(key), text)
        parts.append(f"{key}:{text}")
    return ",".join(parts)


def build_argv(cell: MatrixCell, deployment: SolrDeployment, *, test_run_id: str,
               session_id: str, run_id: str, workload_params: dict,
               workload_repository: str = "default", test_mode: bool = False,
               user_tags: dict | None = None,
               include_tasks: str | None = None, exclude_tasks: str | None = None) -> list[str]:
    """Build the full Solr Orbit command line for one cell."""
    tags = {
        "launchr-session": session_id,
        "launchr-run": run_id,
        "launchr-cluster-config": cell.cluster_config,
        "launchr-profile": cell.profile,
    }
    tags.update(user_tags or {})

    argv = [
        sys.executable, "-m", ORBIT_MODULE, "run",
        f"--pipeline={PIPELINE}",
        f"--target-hosts={deployment.target_hosts}",
        f"--client-options={deployment.client_options}",
        f"--workload={cell.workload}",
        f"--workload-repository={workload_repository}",
        f"--test-run-id={test_run_id}",
        f"--user-tag={render_user_tags(tags)}",
        # Both are fixed because config validation rejects any other value:
        # launchr cannot locate the reports of a multi-iteration run.
        "--test-iterations=1",
        "--aggregate=false",
        "--on-error=abort",
    ]
    if cell.test_procedure:
        argv.append(f"--test-procedure={cell.test_procedure}")
    if workload_params:
        # JSON rather than k:v pairs: Solr Orbit accepts a JSON object here
        # (utils/opts.to_dict) and it sidesteps comma and colon escaping.
        argv.append(f"--workload-params={json.dumps(workload_params, separators=(',', ':'))}")
    if test_mode:
        argv.append("--test-mode")
    if include_tasks:
        argv.append(f"--include-tasks={include_tasks}")
    elif exclude_tasks:
        argv.append(f"--exclude-tasks={exclude_tasks}")
    return argv


def describe_argv(argv: list[str]) -> str:
    """Render an argv for humans, with the interpreter shortened."""
    if argv and argv[0] == sys.executable:
        rendered = ["python", *argv[1:]]
    else:
        rendered = list(argv)
    return " ".join(_quote(a) for a in rendered)


def _quote(arg: str) -> str:
    return f"'{arg}'" if any(c in arg for c in " \"'{}") else arg


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


#: How often the echo loop polls the log file while Solr Orbit runs.
_ECHO_INTERVAL = 0.25

#: How long to let Solr Orbit shut down after it has written its report, before
#: launchr stops waiting and terminates its process group.
#:
#: Solr Orbit can hang in its actor-system shutdown *after* a successful
#: benchmark: the report is on disk and ``SUCCESS`` is printed, but the process
#: never exits. launchr's contract is that a valid report exists, not that the
#: child exited tidily, so it collects the report and moves on rather than
#: letting one cell stall an overnight matrix.
#:
#: See apache/solr-orbit#106 for the underlying Thespian problem.
DEFAULT_SHUTDOWN_GRACE = 60.0

#: How long to wait for a signalled process to actually die.
_KILL_GRACE = 10.0

#: How many times to re-check that a killed process group is really empty, and
#: how long to pause between checks.
_SWEEP_ATTEMPTS = 5
_SWEEP_INTERVAL = 0.3


def run_locally(invocation: OrbitInvocation, *, echo: bool = True,
                env: dict | None = None,
                shutdown_grace: float = DEFAULT_SHUTDOWN_GRACE) -> OrbitResult:
    """Run Solr Orbit as a subprocess on this machine.

    Output goes **straight to a file**, not through a pipe, and the file is
    tailed for the live echo. That indirection is not stylistic. Solr Orbit's
    actor system can leave child processes running after the main process exits
    ("Could not terminate all internal processes within timeout"), and those
    children inherit the stdout file descriptor. With a pipe, the read loop
    waits for EOF, EOF needs *every* writer to close, and launchr would hang
    forever on a benchmark that had already succeeded. Waiting on the direct
    child is unambiguous; what its orphans do with the file is harmless.

    See apache/solr-orbit#106.

    The echo exists because a benchmark takes a long time and a silent terminal
    is indistinguishable from a hung one. Solr Orbit's interactive progress
    rendering only appears on a real TTY, so what reaches the log is the
    line-oriented output.
    """
    invocation.log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Running: %s", describe_argv(invocation.argv))

    with invocation.log_path.open("wb") as log:
        log.write(f"$ {describe_argv(invocation.argv)}\n\n".encode())
        log.flush()
        process = subprocess.Popen(
            invocation.argv,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env if env is not None else os.environ.copy(),
            # Its own process group, so launchr can clean up the whole tree --
            # Solr Orbit's actor system forks children that outlive it -- without
            # signalling itself.
            start_new_session=True,
        )
        # With start_new_session=True the child is its own process-group leader,
        # so its pid *is* the group id. Captured now, because once the child is
        # reaped os.getpgid() raises and the group can no longer be looked up --
        # while its orphaned children are still very much alive.
        group = process.pid
        path = report_path(invocation.test_run_id)
        returncode, abandoned = _wait_and_echo(
            process, invocation.log_path, report=path, echo=echo,
            shutdown_grace=shutdown_grace, group=group,
            report_owner=invocation.test_run_id,
        )

    report = path.read_bytes() if path.exists() else None
    if report is None and returncode == 0:
        raise BenchmarkError(
            f"Solr Orbit exited 0 but wrote no report at {path}. "
            f"See {invocation.log_path} for its output."
        )
    if abandoned and report is not None:
        # The benchmark produced its result; only the shutdown misbehaved.
        logger.warning(
            "Solr Orbit wrote its report but did not exit within %.0fs; its process group was "
            "terminated. Treating the cell as successful.", shutdown_grace,
        )
        returncode = 0

    return OrbitResult(
        returncode=returncode,
        test_run_id=invocation.test_run_id,
        report=report,
        log_path=invocation.log_path,
        aggregated=False,
    )


def _wait_and_echo(process: subprocess.Popen, log_path: Path, *, report: Path,
                   echo: bool, shutdown_grace: float, group: int,
                   report_owner: str) -> tuple[int, bool]:
    """Wait for ``process``, echoing its growing log file meanwhile.

    Returns ``(exit code, abandoned)``. ``abandoned`` is true when the report
    appeared but the process had to be terminated because it would not exit.

    Termination is governed by the process, never by the output stream, so
    orphaned grandchildren holding the log file cannot stall it.
    """
    reader = log_path.open("rb") if echo else None
    if reader is not None:
        reader.seek(0, os.SEEK_END)
    report_seen_at: float | None = None
    try:
        while True:
            finished = process.poll() is not None
            _drain(reader)
            if finished:
                _drain(reader)  # the child may have written between poll() and read()
                _sweep(group, report_owner)
                return process.returncode, False

            if report_seen_at is None and report.exists():
                report_seen_at = time.monotonic()
                logger.debug("Report %s has appeared; allowing %.0fs for shutdown",
                             report, shutdown_grace)
            elif report_seen_at is not None and time.monotonic() - report_seen_at > shutdown_grace:
                _terminate_group(process, group, report_owner)
                _drain(reader)
                return process.returncode or 0, True

            time.sleep(_ECHO_INTERVAL)
    finally:
        if reader is not None:
            reader.close()


def _drain(reader) -> None:
    """Echo whatever has been appended to the log since the last read."""
    if reader is None:
        return
    chunk = reader.read()
    if chunk:
        sys.stdout.write(chunk.decode("utf-8", errors="replace"))
        sys.stdout.flush()


def _terminate_group(process: subprocess.Popen, group: int, test_run_id: str) -> None:
    """Kill a process and every child it forked.

    **SIGKILL, not SIGTERM, and deliberately so.** This runs only after the
    report is already on disk, so there is nothing left for the process to
    flush -- and SIGTERM is actively harmful here: Solr Orbit's actor system
    responds to it by forking *replacement* processes, which then outlive the
    cleanup that provoked them. SIGKILL cannot be caught, so nothing can fork
    in response to it.
    """
    logger.warning("Sending SIGKILL to the Solr Orbit process group %d", group)
    _signal_group(group, signal.SIGKILL)
    try:
        process.wait(timeout=_KILL_GRACE)
    except subprocess.TimeoutExpired:
        logger.error("Solr Orbit's main process survived SIGKILL; continuing anyway")
    _sweep(group, test_run_id)


def _sweep(group: int, test_run_id: str) -> None:
    """Make sure nothing of this cell's Solr Orbit run is left running.

    Two mechanisms, because one is not enough:

    * **The process group.** Catches anything still in the child's tree.
    * **The test-run id.** Solr Orbit's actor processes call ``setsid()``, which
      moves them into a *new* session and process group of their own, so
      ``killpg`` on the child's group cannot reach them -- and because they are
      reparented to init, neither can walking the child's descendants. What does
      identify them exactly is the ``--test-run-id`` launchr generated for this
      cell: a uuid that appears in their command line and nowhere else on the
      machine. See apache/solr-orbit#106.

    Without this, every cell would leave a pair of processes behind. Twenty
    cells in an overnight matrix would leave forty, holding memory and file
    descriptors for no reason.
    """
    for attempt in range(_SWEEP_ATTEMPTS):
        _signal_group(group, signal.SIGKILL, quiet=True)
        survivors = _stragglers(test_run_id)
        if not survivors:
            return
        if attempt == 0:
            logger.info("Solr Orbit left %d process(es) outside its process group; "
                        "terminating them by test-run id", len(survivors))
        for process in survivors:
            try:
                process.kill()
            except Exception as exc:  # noqa: BLE001 - it may have exited meanwhile
                logger.debug("Could not kill pid %s: %s", getattr(process, "pid", "?"), exc)
        time.sleep(_SWEEP_INTERVAL)

    remaining = _stragglers(test_run_id)
    if remaining:
        logger.warning(
            "Solr Orbit left %d process(es) behind that would not die (pids: %s). They are "
            "harmless but will linger.",
            len(remaining), ", ".join(str(p.pid) for p in remaining),
        )


def _stragglers(test_run_id: str):
    """Processes still carrying this cell's test-run id. Never includes launchr."""
    try:
        import psutil
    except ImportError:  # pragma: no cover - psutil is a hard dependency
        return []

    found = []
    own_pid = os.getpid()
    for process in psutil.process_iter(["pid", "cmdline"]):
        if process.info["pid"] == own_pid:
            continue
        cmdline = process.info.get("cmdline") or []
        if any(test_run_id in str(arg) for arg in cmdline):
            found.append(process)
    return found


def _signal_group(group: int, signal_number: int, *, quiet: bool = False) -> None:
    if group == os.getpgrp() or group <= 0:
        # Defensive: never signal launchr's own group. Cannot happen while the
        # child is started in a new session, but the cost of being wrong here is
        # killing the orchestrator.
        logger.debug("Refusing to signal process group %s", group)
        return
    try:
        os.killpg(group, signal_number)
    except ProcessLookupError:
        pass  # Nothing left in the group.
    except OSError as exc:
        if not quiet:
            logger.debug("Could not signal process group %s: %s", group, exc)
