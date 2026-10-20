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
"""The lifecycle loop.

For each provisioning group: provision once, then for each cell deploy Solr,
health-check it, resolve where its version sits on the timeline, run Solr Orbit,
enrich the report, store it, undeploy. Tear the group down when its cells are
done.

Two invariants this module exists to guarantee:

**Failure isolation.** A cell that fails produces a ``failed`` report and does
not stop the next cell. A group whose provisioning fails fails only its own
cells.

**Nothing leaks.** ``undeploy`` and ``teardown`` run in ``finally`` blocks and
never raise, so a crash cannot leave a container running or an instance
billing.
"""

import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solrorbit.tools.launchr import enrich as enrich_module
from solrorbit.tools.launchr import health, orbit, retry, summary, translate
from solrorbit.tools.launchr.config import LaunchrConfig
from solrorbit.tools.launchr.errors import BenchmarkError, DeployError, LaunchrError
from solrorbit.tools.launchr.install import get_install_method
from solrorbit.tools.launchr.matrix import ProfileGroup, plan
from solrorbit.tools.launchr.models import (
    MatrixCell,
    OrbitInvocation,
    ProvisionedInfra,
    RunOutcome,
    SolrDeployment,
    new_run_id,
    new_session_id,
)
from solrorbit.tools.launchr.provisioning import get_strategy
from solrorbit.tools.launchr.storage import get_backend
from solrorbit.tools.launchr.versions import VersionCache, VersionTimeline

logger = logging.getLogger(__name__)


class Session:
    """One ``launchr run``."""

    def __init__(self, config: LaunchrConfig, *, session_id: str | None = None,
                 version_timestamp: datetime | None = None, branch: str | None = None):
        self.config = config
        self.session_id = session_id or new_session_id()
        self.started_at = datetime.now(timezone.utc)
        self.storage = get_backend(config.storage_backend, config.storage_path)
        self.timeline = VersionTimeline(
            VersionCache(config.version_cache_path), offline=config.offline
        )
        self.override_timestamp = version_timestamp
        self.override_branch = branch
        self.outcomes: list[RunOutcome] = []
        self._orbit_version, self._orbit_revision = _orbit_identity()

    # -- the loop ---------------------------------------------------------

    def run(self) -> int:
        """Execute the whole matrix. Returns a process exit code."""
        groups = plan(self.config)
        total = sum(len(g.cells) for g in groups)
        logger.info("Session %s: %d cell(s) in %d group(s); storage %s",
                    self.session_id, total, len(groups), self.storage.location)

        interrupted = False
        index = 0
        try:
            for group in groups:
                index = self._run_group(group, start_index=index, total=total)
        except KeyboardInterrupt:
            interrupted = True
            logger.warning("Session %s interrupted; infrastructure has been released",
                           self.session_id)

        finished_at = datetime.now(timezone.utc)
        self._write_summary(groups, finished_at)

        if interrupted:
            return 130

        failed = [o for o in self.outcomes if not o.completed]
        if failed:
            logger.error("Session %s finished with %d/%d cell(s) failed",
                         self.session_id, len(failed), len(self.outcomes))
            for outcome in failed:
                logger.error("  failed: %s -- %s", outcome.cell.describe(), outcome.error)
            return 1
        logger.info("Session %s finished: %d/%d cell(s) completed",
                    self.session_id, len(self.outcomes), len(self.outcomes))
        return 0

    def _run_group(self, group: ProfileGroup, *, start_index: int, total: int) -> int:
        strategy = get_strategy(group.profile.provisioning)
        index = start_index
        infra: ProvisionedInfra | None = None

        try:
            infra = retry.with_retries(
                lambda: strategy.provision(group.profile, nodes=group.nodes),
                what=f"provisioning {group.describe()}",
            )
        except Exception as exc:  # noqa: BLE001 - a group's cells all fail together
            logger.error("Could not provision %s: %s", group.describe(), exc)
            for cell in group.cells:
                index += 1
                self._record_unprovisioned(cell, exc)
            return index

        try:
            for cell in group.cells:
                index += 1
                logger.info("cell %d/%d  %s", index, total, cell.describe())
                self.outcomes.append(self._run_cell(cell, infra, strategy))
        finally:
            try:
                strategy.teardown(infra)
            except Exception as exc:  # noqa: BLE001 - teardown must never raise
                logger.error("Teardown of %s failed: %s", group.describe(), exc)
        return index

    # -- one cell ---------------------------------------------------------

    def _run_cell(self, cell: MatrixCell, infra: ProvisionedInfra, strategy) -> RunOutcome:
        outcome = RunOutcome(
            cell=cell,
            run_id=new_run_id(),
            session_id=self.session_id,
            status=RunOutcome.FAILED,
            started_at=datetime.now(timezone.utc),
        )
        cluster_config = translate.resolve(self.config.cluster_config(cell.cluster_config))
        install = get_install_method(
            infra.install_method,
            registry=self.config.registry,
            nightly_registry=self.config.nightly_registry,
        )

        workdir = Path(tempfile.mkdtemp(prefix=f"launchr-{outcome.run_id}-"))
        deployment: SolrDeployment | None = None
        report: dict | None = None
        argv: list[str] | None = None
        system_info = None
        version_info = None
        logs: dict[str, bytes] = {}

        try:
            deployment = retry.with_retries(
                lambda: install.deploy(infra, cell.solr_version, None, cluster_config),
                what=f"deploying Solr {cell.solr_version}",
            )
            system_info = health.probe(
                deployment.endpoints[0], timeout=float(infra.profile.startup_timeout)
            )
            deployment.system_info = system_info
            self._check_version(cell, system_info, managed=infra.install_method != "none")

            version_info = self.timeline.resolve(
                cell.solr_version, system_info,
                override_timestamp=self.override_timestamp,
                override_branch=self.override_branch,
                image_timestamp=_image_timestamp(deployment),
            )

            workload_params = self._workload_params(cell, cluster_config)
            test_run_id = _new_test_run_id()
            outcome.test_run_id = test_run_id
            argv = orbit.build_argv(
                cell, deployment,
                test_run_id=test_run_id,
                session_id=self.session_id,
                run_id=outcome.run_id,
                workload_params=workload_params,
                workload_repository=str(self.config.benchmark.get("workload_repository", "default")),
                test_mode=bool(self.config.benchmark.get("test_mode", False)),
                user_tags=dict(self.config.benchmark.get("user_tags", {}) or {}),
            )
            result = strategy.run_on_driver(infra, OrbitInvocation(
                argv=argv, test_run_id=test_run_id, log_path=workdir / "solr-orbit.log",
            ))
            if not result.ok:
                raise BenchmarkError(
                    f"Solr Orbit exited {result.returncode} for {cell.describe()}. "
                    f"Its output is in the stored logs/ directory."
                )
            report = _parse_report(result.report)
            outcome.status = RunOutcome.COMPLETED

        except KeyboardInterrupt:
            # Let an interrupt unwind: the finally block below undeploys Solr and
            # _run_group's releases the infrastructure on the way out.
            outcome.error = "interrupted"
            outcome.finished_at = datetime.now(timezone.utc)
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001 - one cell's failure is data, not a crash
            outcome.error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, LaunchrError):
                logger.error("Cell %s failed: %s", cell.describe(), exc)
            else:
                logger.exception("Cell %s failed unexpectedly", cell.describe())
            if deployment is not None:
                try:
                    logs = install.collect_logs(deployment)
                except Exception as log_exc:  # noqa: BLE001
                    logger.warning("Could not collect Solr logs: %s", log_exc)
            elif isinstance(exc, DeployError) and exc.logs:
                # A deploy that failed before returning a deployment carries the
                # log itself; there is nothing left to collect it from.
                logs = exc.logs

        finally:
            if deployment is not None:
                try:
                    install.undeploy(deployment)
                except Exception as exc:  # noqa: BLE001 - undeploy must never raise
                    logger.error("Undeploying Solr for %s failed: %s", cell.describe(), exc)

        outcome.finished_at = datetime.now(timezone.utc)
        try:
            self._store(cell, outcome, report, cluster_config, deployment, system_info,
                        version_info, argv, workdir, logs)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not store the report for %s: %s", cell.describe(), exc)
            outcome.status = RunOutcome.FAILED
            outcome.error = outcome.error or f"storage failed: {exc}"
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        return outcome

    # -- storage ----------------------------------------------------------

    def _cell_prefix(self, cell: MatrixCell, outcome: RunOutcome) -> str:
        date = self.started_at.strftime("%Y-%m-%d")
        return f"runs/{cell.workload}/{date}/{outcome.run_id}"

    def _store(self, cell: MatrixCell, outcome: RunOutcome, report: dict | None,
               cluster_config, deployment, system_info, version_info,
               argv: list[str] | None, workdir: Path, logs: dict[str, bytes]) -> None:
        prefix = self._cell_prefix(cell, outcome)
        block = enrich_module.build_block(
            cell=cell,
            outcome=outcome,
            cluster_config=cluster_config,
            workload_params=self._workload_params(cell, cluster_config),
            workload_repository=str(self.config.benchmark.get("workload_repository", "default")),
            benchmark=self.config.benchmark,
            argv=argv,
            deployment=deployment,
            system_info=system_info,
            version_info=version_info,
            infra_metadata=deployment.infra.metadata if deployment else None,
            workload_revision=enrich_module.workload_revision_of(report),
            user_labels=dict(self.config.benchmark.get("user_tags", {}) or {}),
            orbit_version=self._orbit_version,
            orbit_revision=self._orbit_revision,
        )
        enriched = enrich_module.enrich(report, block, cell=cell, test_run_id=outcome.test_run_id)
        # Through the retry policy like every other storage write: a transient
        # backend failure here would otherwise mark a finished benchmark failed
        # and leave no results.json to inspect.
        retry.with_retries(
            lambda: self.storage.write(f"{prefix}/results.json", _json_bytes(enriched)),
            what="writing the cell report",
            backoff=retry.STORAGE_BACKOFF,
        )
        outcome.result_path = f"{prefix}/results.json"

        if outcome.completed:
            return

        # Logs are stored for failures only: the thing you need, exactly when
        # you need it, without unbounded growth on the happy path.
        def write_log(name: str, data: bytes) -> None:
            retry.with_retries(
                lambda: self.storage.write(f"{prefix}/logs/{name}", data),
                what=f"writing {name}",
                backoff=retry.STORAGE_BACKOFF,
            )

        orbit_log = workdir / "solr-orbit.log"
        if orbit_log.exists():
            write_log("solr-orbit.log", orbit_log.read_bytes())
        for name, data in logs.items():
            write_log(name, data)

    def _write_summary(self, groups: list[ProfileGroup], finished_at: datetime) -> None:
        document = summary.build(
            self.session_id, self.started_at, finished_at, groups, self.outcomes,
            launchr_version=self._orbit_version,
        )
        path = summary.summary_path(self.session_id, self.started_at)
        try:
            retry.with_retries(
                lambda: self.storage.write(path, summary.render(document)),
                what="writing the session summary",
                backoff=retry.STORAGE_BACKOFF,
            )
            logger.info("Session summary: %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not write the session summary: %s", exc)

    # -- helpers ----------------------------------------------------------

    def _workload_params(self, cell: MatrixCell, cluster_config) -> dict[str, Any]:
        """Workload params for a cell. Shared with --dry-run, deliberately."""
        return translate.workload_params(
            cluster_config, self.config.workloads, cell.workload,
            test_mode=bool(self.config.benchmark.get("test_mode", False)),
        )

    def _check_version(self, cell: MatrixCell, system_info, *, managed: bool) -> None:
        """Warn, or fail, when the cluster is not running the version we asked for.

        For a cluster launchr deployed this is a real error -- the report would
        claim a version that did not run. For an externally managed one it is a
        configuration mistake worth failing on too, because the data point would
        be mislabelled either way.
        """
        reported = (system_info.solr_version or "").strip()
        wanted = cell.solr_version.strip()
        if not reported or reported == wanted:
            return
        # A SNAPSHOT image reports its base version, e.g. 10.0.0-SNAPSHOT -> 10.0.0.
        # Only that exact relationship: a prefix test would accept a cluster
        # reporting 9.1 for a 9.11.0 cell.
        if wanted.upper() == f"{reported}-SNAPSHOT".upper():
            return
        message = (
            f"Solr reports version {reported!r} but this cell is {wanted!r}. "
            f"The data point would be mislabelled."
        )
        if managed:
            raise BenchmarkError(message)
        raise BenchmarkError(
            message + " An externally managed cluster runs whatever it runs; set "
            "--versions to match it."
        )

    def _record_unprovisioned(self, cell: MatrixCell, exc: Exception) -> None:
        """Record a cell that never got as far as a deployment."""
        now = datetime.now(timezone.utc)
        outcome = RunOutcome(
            cell=cell, run_id=new_run_id(), session_id=self.session_id,
            status=RunOutcome.FAILED, started_at=now, finished_at=now,
            error=f"provisioning failed: {type(exc).__name__}: {exc}",
        )
        cluster_config = translate.resolve(self.config.cluster_config(cell.cluster_config))
        try:
            self._store(cell, outcome, None, cluster_config, None, None, None, None,
                        Path(tempfile.gettempdir()), {})
        except Exception as store_exc:  # noqa: BLE001
            logger.error("Could not store the failed report for %s: %s", cell.describe(), store_exc)
        self.outcomes.append(outcome)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _image_timestamp(deployment: SolrDeployment | None) -> datetime | None:
    """When the deployed container image was built, if the install method said.

    The last-resort x-axis position, and the only one a nightly has.
    """
    raw = (deployment.metadata or {}).get("image_created") if deployment else None
    if not raw:
        return None
    try:
        # Docker reports RFC-3339 with nanoseconds, which fromisoformat
        # rejects before 3.11 and tolerates after; truncate to microseconds so
        # the behaviour does not depend on the interpreter.
        text = str(raw).replace("Z", "+00:00")
        if "." in text:
            head, _, tail = text.partition(".")
            fraction, sign, offset = tail.partition("+")
            text = f"{head}.{fraction[:6]}" + (f"{sign}{offset}" if sign else "")
        return datetime.fromisoformat(text)
    except ValueError:
        logger.debug("Could not parse the container image build date %r", raw)
        return None



def _json_bytes(document: dict) -> bytes:
    import json

    return json.dumps(document, indent=2, sort_keys=False, default=str).encode("utf-8")


def _parse_report(raw: bytes | None) -> dict:
    import json

    if not raw:
        raise BenchmarkError("Solr Orbit produced no report")
    try:
        report = json.loads(raw)
    except ValueError as exc:
        raise BenchmarkError(f"Solr Orbit's report is not valid JSON: {exc}") from exc
    if not isinstance(report, dict):
        raise BenchmarkError("Solr Orbit's report is not a JSON object")
    return report


def _new_test_run_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _orbit_identity() -> tuple[str | None, str | None]:
    """Solr Orbit's version and git revision, for the report's provenance."""
    try:
        from solrorbit import version as orbit_version

        return orbit_version.version(), orbit_version.revision()
    except Exception as exc:  # noqa: BLE001 - provenance is nice to have
        logger.debug("Could not determine the Solr Orbit version: %s", exc)
        return None, None


def run(config: LaunchrConfig, **kwargs) -> int:
    """Run a whole matrix. The entry point ``launchr run`` calls."""
    return Session(config, **kwargs).run()
