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
"""Add launchr's metadata to a Solr Orbit report.

Solr Orbit's ``test_run.json`` is copied **verbatim** and a single ``launchr``
key is added. Nothing in Solr Orbit's own key space is touched, so
``TestRun.from_dict()`` still parses a stored report and ``solr-orbit compare``
still consumes it.

The ``launchr`` block carries what a chart needs and a benchmark cannot know
about itself: where the version sits on the timeline, what hardware ran it, and
what configuration was actually applied.
"""

from datetime import datetime, timezone
from typing import Any, Mapping

from solrorbit.tools.launchr.models import (
    MatrixCell,
    ResolvedClusterConfig,
    RunOutcome,
    SolrDeployment,
    SystemInfo,
    VersionInfo,
)

#: Bumped when the ``launchr`` block changes incompatibly. reportr refuses a
#: report whose schema_version it does not understand rather than mis-reading it.
SCHEMA_VERSION = 1


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    stamped = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return stamped.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_block(*, cell: MatrixCell, outcome: RunOutcome, cluster_config: ResolvedClusterConfig,
                workload_params: Mapping[str, Any], workload_repository: str,
                benchmark: Mapping[str, Any], argv: list[str] | None,
                deployment: SolrDeployment | None = None,
                system_info: SystemInfo | None = None,
                version_info: VersionInfo | None = None,
                infra_metadata: Mapping[str, Any] | None = None,
                workload_revision: str | None = None,
                user_labels: Mapping[str, Any] | None = None,
                orbit_version: str | None = None,
                orbit_revision: str | None = None) -> dict:
    """Build the ``launchr`` block for one cell."""
    # What was actually applied, which is not what was asked for when nothing
    # deployed Solr. An externally managed cluster (install_method: none) runs
    # whatever it was started with, and a cell that failed before deploying
    # applied nothing at all; in both cases the requested values stay in the
    # heap/gc/solr_opts fields above, where they read as a request.
    install_method = deployment.infra.install_method if deployment else None
    applied_env = dict(cluster_config.env) if install_method not in (None, "none") else {}

    solr: dict[str, Any] = {"version": cell.solr_version}
    if deployment is not None:
        solr["image"] = deployment.image
        solr["endpoints"] = [str(e) for e in deployment.endpoints]
    if system_info is not None:
        solr["impl_version"] = system_info.solr_impl_version or None
        solr["commit"] = system_info.commit
        solr["lucene_version"] = system_info.lucene_version
        solr["mode"] = system_info.mode
        solr["jvm"] = {"vendor": system_info.jvm_vendor, "version": system_info.jvm_version}
    if version_info is not None:
        solr["version_timestamp"] = _iso(version_info.timestamp)
        solr["version_timestamp_source"] = version_info.source
        solr["version_timestamp_precision"] = version_info.precision
        solr["version_kind"] = version_info.kind
        solr["branch"] = version_info.branch
        solr["branch_source"] = version_info.branch_source

    infra: dict[str, Any] = {
        "provisioning_profile": cell.profile,
        "install_method": deployment.infra.install_method if deployment else None,
        "provisioning": deployment.infra.strategy if deployment else None,
    }
    if infra_metadata:
        infra.update(infra_metadata)
    # What the *install method* recorded, as opposed to what provisioning did:
    # the image, the network mode, and on a multi-node cluster which node is
    # also running ZooKeeper. That last one is an asymmetry between otherwise
    # identical nodes, and a reader comparing them should not have to discover
    # it by reading launchr's source.
    if deployment is not None and deployment.metadata:
        infra["deployment"] = dict(deployment.metadata)

    block: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": outcome.run_id,
        "session_id": outcome.session_id,
        "cell_id": cell.cell_id,
        "status": outcome.status,
        "started_at": _iso(outcome.started_at),
        "finished_at": _iso(outcome.finished_at),
        "solr": solr,
        "infra": infra,
        "cluster_config": {
            "name": cluster_config.name,
            "heap": cluster_config.spec.heap if cluster_config.spec else None,
            "gc": cluster_config.spec.gc if cluster_config.spec else None,
            "shards": cluster_config.spec.shards if cluster_config.spec else None,
            "replicas": cluster_config.spec.replicas if cluster_config.spec else None,
            "solr_opts": cluster_config.spec.solr_opts if cluster_config.spec else None,
            "applied_env": applied_env,
            "workload_params": dict(cluster_config.workload_params),
        },
        "workload": {
            "name": cell.workload,
            "test_procedure": cell.test_procedure,
            "repository": workload_repository,
            "revision": workload_revision,
            "params": dict(workload_params),
        },
        "benchmark": {
            "iterations": int(benchmark.get("iterations", 1)),
            "aggregated": bool(benchmark.get("aggregate", False)),
            "test_mode": bool(benchmark.get("test_mode", False)),
            "orbit_version": orbit_version,
            "orbit_revision": orbit_revision,
            "command": list(argv) if argv else None,
        },
        "user_labels": dict(user_labels or {}),
    }
    if outcome.error:
        block["error"] = outcome.error
    return block


def enrich(report: dict | None, launchr_block: dict, *, cell: MatrixCell,
           test_run_id: str | None = None) -> dict:
    """Return the stored report: Solr Orbit's keys verbatim, plus ``launchr``.

    ``report`` is ``None`` for a failed cell that never produced one. The result
    then carries only enough identity to be readable, and no ``results`` key --
    which is how reportr tells a failure from a success.
    """
    if report is None:
        enriched: dict[str, Any] = {"workload": cell.workload}
        if cell.test_procedure:
            enriched["test_procedure"] = cell.test_procedure
        if test_run_id:
            enriched["test-run-id"] = test_run_id
    else:
        enriched = dict(report)
    enriched["launchr"] = launchr_block
    return enriched


def workload_revision_of(report: dict | None) -> str | None:
    """Pull Solr Orbit's recorded workload revision out of a report."""
    if not report:
        return None
    revision = report.get("workload-revision")
    return str(revision) if revision else None
