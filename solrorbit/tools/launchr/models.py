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
"""The dataclasses launchr's components exchange.

These are the plan's shared contracts in code form. Three groups:

* **Identity and configuration** -- :class:`ProfileSpec`, :class:`ClusterConfigSpec`,
  :class:`WorkloadSpec`, :class:`MatrixCell`.
* **Connectivity** -- :class:`SolrEndpoint` (where Solr listens) and
  :class:`SshSpec` (how a node is administered). They are deliberately separate:
  on a cloud instance Solr binds a private address while management goes through
  a public one or a bastion.
* **Results** -- :class:`SystemInfo`, :class:`VersionInfo`, :class:`OrbitResult`,
  :class:`RunOutcome`.
"""

from __future__ import annotations

import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

#: Number of hex characters in a generated id. Short enough to quote in a
#: conversation, long enough that a nightly will not collide for centuries.
_ID_CHARS = 6


def new_session_id() -> str:
    """Return a fresh id for one ``launchr run`` invocation."""
    return "session-" + uuid.uuid4().hex[:_ID_CHARS]


def new_run_id() -> str:
    """Return a fresh id for one matrix cell, i.e. one stored report."""
    return "run-" + uuid.uuid4().hex[:_ID_CHARS]


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------

#: Solr's default HTTP port, used when a URL omits one.
DEFAULT_SOLR_PORT = 8983

#: Read timeout, in seconds, for the driver's HTTP calls to Solr.
#:
#: Two hours, not a minute. This is a *per request* read timeout, and it has
#: to exceed the longest single operation a benchmark asks for -- which is
#: ``optimize``, a force-merge of the whole index behind one HTTP call. At the
#: previous 60s a full nyc_taxis run indexed all 165,346,692 documents over 86
#: minutes and then died there with "Read timed out": the client gave up on
#: Solr doing exactly what it had been asked to do.
#:
#: Two rather than one because the duration of that merge is not known in
#: advance and scales with the corpus, and being wrong costs the entire run at
#: its last step. A generous value is cheap here: this is not a production
#: SLA, and a genuinely hung cluster is still caught by the per-cell benchmark
#: timeout, which is the backstop that exists for it.
DEFAULT_CLIENT_TIMEOUT = 7200


@dataclass(frozen=True)
class SolrEndpoint:
    """How the load driver reaches one Solr node.

    The scheme is explicit because Solr may run behind TLS, and Solr Orbit's
    ``--target-hosts`` already understands ``https://host:port`` (see
    ``_parse_host_string`` in ``solrorbit/utils/opts.py``).
    """

    scheme: str = "http"
    host: str = "127.0.0.1"
    port: int = DEFAULT_SOLR_PORT
    verify_certs: bool = True

    def __str__(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def base_url(self) -> str:
        """The endpoint as a URL, with no trailing slash."""
        return str(self)

    @property
    def target_host(self) -> str:
        """The endpoint as Solr Orbit's ``--target-hosts`` wants it.

        Plain HTTP is rendered as ``host:port``, which Solr Orbit reads as the
        default scheme and which keeps log lines short. TLS is rendered with its
        scheme, because otherwise the information would be lost.
        """
        if self.scheme == "http":
            return f"{self.host}:{self.port}"
        return f"{self.scheme}://{self.host}:{self.port}"

    @classmethod
    def from_url(cls, url: str, *, verify_certs: bool = True) -> SolrEndpoint:
        """Parse ``http://host:port``, ``https://host``, or a bare ``host:port``."""
        raw = url.strip()
        if not raw:
            raise ValueError("Solr URL is empty")
        parsed = urllib.parse.urlsplit(raw if "://" in raw else f"http://{raw}")
        if not parsed.hostname:
            raise ValueError(f"Could not parse a host out of Solr URL {url!r}")
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Solr URL {url!r} has unsupported scheme {parsed.scheme!r}")
        return cls(
            scheme=parsed.scheme,
            host=parsed.hostname,
            port=parsed.port or DEFAULT_SOLR_PORT,
            verify_certs=verify_certs,
        )


@dataclass(frozen=True)
class SshSpec:
    """How launchr administers one node.

    Separate from :class:`SolrEndpoint` on purpose: the address Solr listens on
    and the address we manage it through are frequently different machines.

    There is no password field and there will not be one -- remote provisioning
    is key-only.
    """

    host: str
    user: str
    port: int = 22
    key_path: str | None = None
    bastion: SshSpec | None = None


@dataclass(frozen=True)
class NodeHandle:
    """One machine in a provisioned set."""

    name: str
    endpoint: SolrEndpoint | None = None
    ssh: SshSpec | None = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProfileSpec:
    """A named infrastructure configuration from ``provisioning_profiles``."""

    name: str
    provisioning: str
    install_method: str
    nodes: int = 1
    port: int = DEFAULT_SOLR_PORT
    solr_url: str | None = None
    startup_timeout: int = 300
    options: Mapping[str, Any] = field(default_factory=dict)

    @property
    def group_key(self) -> tuple:
        """Identity for grouping cells onto one provisioned set of machines.

        Node *count* is deliberately excluded: two profiles that differ only in
        ``nodes`` share one group, provisioned at the maximum count, and a cell
        wanting fewer uses a subset. Everything else that could change what the
        hardware is must be part of the key.
        """
        return (
            self.provisioning,
            self.install_method,
            self.port,
            self.solr_url,
            self.startup_timeout,
            tuple(sorted((str(k), repr(v)) for k, v in self.options.items())),
        )


@dataclass(frozen=True)
class ClusterConfigSpec:
    """A named Solr runtime configuration from ``cluster_configs``."""

    name: str
    heap: str | None = None
    gc: str | None = None
    solr_opts: str | None = None
    shards: int | None = None
    replicas: int | None = None


@dataclass(frozen=True)
class ResolvedClusterConfig:
    """A :class:`ClusterConfigSpec` translated into what actually gets applied.

    ``env`` is what the Solr process receives; ``workload_params`` is what Solr
    Orbit receives. Both are recorded in the report so a reader never has to
    guess what ``gc: "G1GC"`` meant on the day.
    """

    name: str
    env: Mapping[str, str] = field(default_factory=dict)
    workload_params: Mapping[str, Any] = field(default_factory=dict)
    spec: ClusterConfigSpec | None = None


@dataclass(frozen=True)
class WorkloadSpec:
    """A workload entry from ``workloads``."""

    name: str
    test_procedures: tuple[str | None, ...] = (None,)
    workload_params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MatrixCell:
    """One benchmark: a workload, a procedure, a version, a profile, a config."""

    workload: str
    test_procedure: str | None
    solr_version: str
    profile: str
    cluster_config: str

    @property
    def cell_id(self) -> str:
        """Stable, filesystem-safe identity for this cell."""
        procedure = self.test_procedure or "default"
        return "__".join(
            _slug(part)
            for part in (self.workload, procedure, self.solr_version, self.profile, self.cluster_config)
        )

    def describe(self) -> str:
        """A one-line human rendering, for logs and ``--dry-run``."""
        procedure = f"/{self.test_procedure}" if self.test_procedure else ""
        return f"{self.workload}{procedure} {self.solr_version} [{self.profile} {self.cluster_config}]"


def _slug(value: str) -> str:
    """Reduce a value to characters that are safe in a path segment."""
    return "".join(c if c.isalnum() or c in "._-" else "-" for c in str(value))


# ---------------------------------------------------------------------------
# Provisioning and deployment
# ---------------------------------------------------------------------------


@dataclass
class ProvisionedInfra:
    """The machines one provisioning profile group runs on."""

    profile: ProfileSpec
    strategy: str
    install_method: str
    nodes: list[NodeHandle] = field(default_factory=list)
    driver: NodeHandle | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    handles: dict[str, Any] = field(default_factory=dict)

    @property
    def endpoints(self) -> list[SolrEndpoint]:
        """Every node's Solr endpoint, in node order."""
        return [n.endpoint for n in self.nodes if n.endpoint is not None]


@dataclass
class SolrDeployment:
    """A running Solr, and how to reach it."""

    infra: ProvisionedInfra
    version: str
    image: str | None
    endpoints: list[SolrEndpoint]
    cluster_config: ResolvedClusterConfig
    handles: dict[str, Any] = field(default_factory=dict)
    system_info: SystemInfo | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    #: Read timeout in seconds for the driver's HTTP calls to Solr.
    client_timeout: int = DEFAULT_CLIENT_TIMEOUT

    @property
    def target_hosts(self) -> str:
        """Rendered for Solr Orbit's ``--target-hosts``."""
        return ",".join(e.target_host for e in self.endpoints)

    @property
    def client_options(self) -> str:
        """Rendered for Solr Orbit's ``--client-options``."""
        options = [f"timeout:{int(self.client_timeout)}"]
        if any(not e.verify_certs for e in self.endpoints):
            options.append("verify_certs:false")
        return ",".join(options)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemInfo:
    """Parsed from ``/solr/admin/info/system`` on the live cluster.

    This is the one call launchr always makes, and it answers three questions at
    once: is Solr healthy, what exactly is running, and when was it built.
    """

    solr_version: str
    solr_impl_version: str
    commit: str | None = None
    build_timestamp: datetime | None = None
    lucene_version: str | None = None
    jvm_vendor: str | None = None
    jvm_version: str | None = None
    mode: str | None = None

    @property
    def cloud_mode(self) -> bool:
        """Whether Solr reports running in SolrCloud mode.

        Solr Orbit only supports SolrCloud, so a false here is worth failing on
        before a benchmark starts rather than part-way through.
        """
        return bool(self.mode) and "cloud" in self.mode.lower()


@dataclass(frozen=True)
class VersionInfo:
    """Where a Solr version sits on the chart's x-axis, and how we know."""

    version: str
    timestamp: datetime
    source: str
    precision: str
    kind: str
    commit: str | None = None
    branch: str | None = None
    branch_source: str | None = None


@dataclass(frozen=True)
class OrbitInvocation:
    """Everything a driver needs in order to run Solr Orbit once."""

    argv: list[str]
    test_run_id: str
    log_path: Path


@dataclass
class OrbitResult:
    """What came back from running Solr Orbit."""

    returncode: int
    test_run_id: str
    report: bytes | None
    log_path: Path
    aggregated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.report is not None


@dataclass
class RunOutcome:
    """The fate of one matrix cell."""

    cell: MatrixCell
    run_id: str
    session_id: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    test_run_id: str | None = None
    result_path: str | None = None
    error: str | None = None

    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def completed(self) -> bool:
        return self.status == RunOutcome.COMPLETED
