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
"""Read ``/solr/admin/info/system`` and make sense of it.

This is the one HTTP call launchr always makes, and it answers three questions
at once: is Solr up, what exactly is running (version plus the git commit that
was built), and when was it built. The build timestamp is the fallback x-axis
position for any version the release list cannot place.

It needs a live Solr between deploy and execute, which is why launchr owns the
Solr lifecycle instead of delegating to Solr Orbit's ``docker`` pipeline.
"""

import logging
import re
import time
from datetime import datetime, timezone

import requests

from solrorbit.tools.launchr.errors import DeployError
from solrorbit.tools.launchr.models import SolrEndpoint, SystemInfo

logger = logging.getLogger(__name__)

#: ``solr-impl-version`` comes in two shapes. A release build::
#:
#:     9.11.0 abc1234def - jenkins - 2026-02-14 11:02:31
#:     ^^^^^^ ^^^^^^^^^^   ^^^^^^^   ^^^^^^^^^^^^^^^^^^^
#:     version  commit     builder    build timestamp
#:
#: and a nightly, which stops after the commit::
#:
#:     11.0.0-SNAPSHOT 714d6ceff852e6dc... [snapshot build, details omitted]
#:
#: Everything after the commit is therefore optional. It has to be: an
#: all-or-nothing pattern threw away the nightly's commit hash as well as its
#: absent timestamp, and the commit is the single most useful thing to know
#: about a nightly -- it is what says *which* main this was.
#:
#: The builder field is free text, so it is matched non-greedily and the
#: timestamp is anchored to the end of that optional group.
_IMPL_VERSION = re.compile(
    r"^(?P<version>\S+)\s+"
    r"(?P<commit>[0-9a-fA-F]{7,40})\b"
    r"(?:\s+-\s+(?P<builder>.*?)\s+-\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\s*)?"
    r".*$"
)

SYSTEM_INFO_PATH = "/solr/admin/info/system"


def parse_impl_version(impl_version: str) -> tuple[str | None, datetime | None]:
    """Pull the commit hash and build timestamp out of ``solr-impl-version``.

    Either half may be absent and the other still useful: a nightly carries a
    commit but no timestamp. Returns ``(None, None)`` only for a string that
    does not match at all -- a locally built image may carry anything here,
    and that is not a reason to fail a benchmark.
    """
    match = _IMPL_VERSION.match(impl_version.strip()) if impl_version else None
    if not match:
        logger.debug("Could not parse solr-impl-version %r", impl_version)
        return None, None

    stamp = None
    raw = match.group("timestamp")
    if raw:
        try:
            # Solr writes this in UTC without a zone designator.
            stamp = datetime.fromisoformat(raw.replace(" ", "T")).replace(tzinfo=timezone.utc)
        except ValueError:
            logger.debug("Could not parse build timestamp out of %r", impl_version)
    return match.group("commit"), stamp


def parse_system_info(payload: dict) -> SystemInfo:
    """Build a :class:`SystemInfo` from a parsed ``info/system`` response."""
    lucene = payload.get("lucene") or {}
    jvm = payload.get("jvm") or {}
    jvm_spec = jvm.get("spec") or {}

    impl_version = lucene.get("solr-impl-version") or ""
    commit, build_timestamp = parse_impl_version(impl_version)

    return SystemInfo(
        solr_version=lucene.get("solr-spec-version") or "",
        solr_impl_version=impl_version,
        commit=commit,
        build_timestamp=build_timestamp,
        lucene_version=lucene.get("lucene-spec-version"),
        jvm_vendor=jvm_spec.get("vendor") or jvm.get("vendor") or jvm.get("name"),
        jvm_version=jvm.get("version"),
        mode=payload.get("mode"),
    )


def fetch(endpoint: SolrEndpoint, *, timeout: float = 10.0) -> SystemInfo:
    """Fetch and parse ``info/system`` once. Raises on any failure."""
    url = f"{endpoint.base_url}{SYSTEM_INFO_PATH}?wt=json"
    response = requests.get(url, timeout=timeout, verify=endpoint.verify_certs)
    response.raise_for_status()
    return parse_system_info(response.json())


def probe(endpoint: SolrEndpoint, *, timeout: float = 120.0, interval: float = 2.0,
          require_cloud: bool = True) -> SystemInfo:
    """Poll ``info/system`` until Solr answers, then sanity-check what answered.

    :param timeout: how long to keep trying before giving up, in seconds.
    :param require_cloud: fail when Solr is not in SolrCloud mode. Solr Orbit
        supports only SolrCloud, and failing here produces a far clearer message
        than failing inside a benchmark.
    """
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while True:
        try:
            info = fetch(endpoint)
            break
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
            last_error = exc
            if time.monotonic() >= deadline:
                raise DeployError(
                    f"Solr at {endpoint} did not answer {SYSTEM_INFO_PATH} within "
                    f"{timeout:.0f}s. Last error: {last_error}"
                ) from last_error
            time.sleep(interval)

    if require_cloud and not info.cloud_mode:
        raise DeployError(
            f"Solr at {endpoint} reports mode {info.mode!r}, not SolrCloud. "
            f"Solr Orbit only supports SolrCloud mode."
        )
    logger.info("Solr at %s is ready: version=%s commit=%s mode=%s",
                endpoint, info.solr_version or "?", info.commit or "?", info.mode)
    return info


#: Where SolrCloud reports which nodes are currently in the cluster.
CLUSTER_STATUS_PATH = "/solr/admin/collections?action=CLUSTERSTATUS&wt=json"


def live_nodes(endpoint: SolrEndpoint, *, timeout: float = 10.0) -> list[str]:
    """The nodes SolrCloud currently considers live, as ``host:port_solr``."""
    url = f"{endpoint.base_url}{CLUSTER_STATUS_PATH}"
    response = requests.get(url, timeout=timeout, verify=endpoint.verify_certs)
    response.raise_for_status()
    cluster = response.json().get("cluster") or {}
    return [str(n) for n in cluster.get("live_nodes") or []]


def probe_cluster(endpoints: list[SolrEndpoint], *, expected_nodes: int | None = None,
                  timeout: float = 120.0, interval: float = 2.0,
                  require_cloud: bool = True) -> SystemInfo:
    """Wait for every node to answer, and for the cluster to have formed.

    Probing only the first endpoint is not enough once a profile asks for more
    than one node. A second Solr that failed to reach ZooKeeper leaves the
    first one perfectly healthy and alone, and the benchmark would then run
    against a one-node cluster while the report claimed two -- a wrong number
    that looks entirely plausible, which is the worst kind.

    Returns the first node's :class:`SystemInfo`, which is what the report
    records: the nodes are identical by construction, so one answer describes
    the cluster.
    """
    if not endpoints:
        raise DeployError("No Solr endpoints to probe")

    deadline = time.monotonic() + timeout
    info = probe(endpoints[0], timeout=timeout, interval=interval, require_cloud=require_cloud)
    for endpoint in endpoints[1:]:
        remaining = max(10.0, deadline - time.monotonic())
        probe(endpoint, timeout=remaining, interval=interval, require_cloud=require_cloud)

    wanted = expected_nodes if expected_nodes is not None else len(endpoints)
    if wanted < 2:
        return info

    last_seen: list[str] = []
    while True:
        try:
            last_seen = live_nodes(endpoints[0])
            if len(last_seen) >= wanted:
                logger.info("Cluster has formed with %d live node(s): %s",
                            len(last_seen), ", ".join(sorted(last_seen)))
                return info
        except Exception as exc:  # noqa: BLE001 - not formed yet, or an older API
            logger.debug("Could not read live nodes: %s", exc)
        if time.monotonic() >= deadline:
            raise DeployError(
                f"Solr answered on every node, but the cluster reported "
                f"{len(last_seen)} live node(s) rather than {wanted} within {timeout:.0f}s "
                f"(saw: {', '.join(sorted(last_seen)) or 'none'}). A node that cannot reach "
                f"ZooKeeper leaves the others healthy and alone, so benchmarking now would "
                f"measure a smaller cluster than the report claims."
            )
        time.sleep(interval)
