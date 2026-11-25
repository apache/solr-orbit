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
"""Solr in Docker on remote hosts, one container per node, over SSH.

The multi-node counterpart to :mod:`~solrorbit.tools.launchr.install.docker`.
Three things make it more than that module with an ``ssh`` prefix:

**ZooKeeper is external.** The single-container launcher uses Solr's embedded
ZooKeeper, which cannot coordinate a second node. This starts a standalone
``zookeeper`` container and points every Solr at it.

**ZooKeeper runs on the first Solr node, not the driver.** Co-locating it with
the driver would keep the Solr nodes byte-for-byte identical, which is the
tidier story for a version comparison -- but the driver is the machine under
sustained load during indexing, and a starved ZooKeeper there means session
timeouts and a lost run. ZooKeeper's cost during a steady-state benchmark is
near zero: SolrCloud clients cache cluster state and do not consult it per
request. The asymmetry is recorded in the deployment metadata so a reader can
see it rather than discover it.

**Host networking.** Each container shares its instance's network namespace,
so Solr binds the instance's own address and the address it publishes into
ZooKeeper is the one other nodes can actually reach. With bridge networking a
node registers its container-private address and the cluster half-forms.

**The index is bind-mounted, not left to Docker.** The Solr image declares
``VOLUME /var/solr``, so a plain ``docker run`` creates an *anonymous* volume
per container; ``docker rm`` does not remove it, and a six-version matrix
strands six copies of a 40 GB index on the disk. A named host path is also
the only way to put the index on a volume other than the root one, which is
what ``data_volume`` in the provisioning profile exists for.

That makes the data outlive the container, so :meth:`undeploy` empties the
directory. Without that the next cell would inherit the previous version's
index -- which is worse than a leak, because it looks like a result.
"""

import logging
import shlex
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar

from solrorbit.tools.launchr.errors import DeployError
from solrorbit.tools.launchr.models import (
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrDeployment,
    SolrEndpoint,
)
from solrorbit.tools.launchr.provisioning.ec2.ssh import SshSession

logger = logging.getLogger(__name__)

SOLR_CONTAINER = "launchr-solr"
ZK_CONTAINER = "launchr-zk"
ZK_PORT = 2181

#: Pinned, because the coordination layer is part of the environment a result
#: was produced in. 3.9 is the line Solr 9 ships against.
ZK_IMAGE = "zookeeper:3.9"

#: Used when the provisioning strategy did not say; keeps the install method
#: usable against infrastructure that predates the data_dir metadata.
DEFAULT_DATA_DIR = "/var/solr-data"

_ZK_READY_TIMEOUT = 120
_ZK_POLL = 3


def resolve_image(version: str, *, registry: str, nightly_registry: str) -> str:
    """Return the full image reference for a Solr version."""
    repository = nightly_registry if "SNAPSHOT" in version.upper() else registry
    return f"{repository}:{version}"


class DockerSshInstall:
    """Starts a ZooKeeper and one Solr container per node, over SSH."""

    API_VERSION: ClassVar[int] = 1
    name: ClassVar[str] = "docker-ssh"

    def __init__(self, *, registry: str = "docker.io/library/solr",
                 nightly_registry: str = "docker.io/apache/solr-nightly"):
        self.registry = registry
        self.nightly_registry = nightly_registry

    # -- lifecycle ---------------------------------------------------------

    def deploy(self, infra: ProvisionedInfra, version: str, image: str | None,
               cluster_config: ResolvedClusterConfig) -> SolrDeployment:
        nodes = [n for n in infra.nodes if n.ssh and n.endpoint]
        if not nodes:
            raise DeployError(
                "The 'docker-ssh' install method needs nodes with both an SSH spec and a "
                "Solr endpoint; this infrastructure provided none."
            )
        resolved_image = image or resolve_image(
            version, registry=self.registry, nightly_registry=self.nightly_registry,
        )
        sessions = {n.name: self._session(n, infra) for n in nodes}
        zk_node = nodes[0]
        zk_host = f"{zk_node.endpoint.host}:{ZK_PORT}"

        try:
            self._start_zookeeper(sessions[zk_node.name], zk_node.endpoint.host)
            self._pull(sessions, resolved_image)
            image_created = self._image_created(sessions[zk_node.name], resolved_image)
            data_dir = infra.metadata.get("data_dir") or DEFAULT_DATA_DIR
            self._clear_data(sessions, data_dir)
            self._start_solr(sessions, nodes, resolved_image, zk_host, cluster_config,
                             version, data_dir)
        except Exception as exc:
            raise DeployError(f"Could not deploy Solr {version}: {exc}") from exc

        return SolrDeployment(
            infra=infra,
            version=version,
            image=resolved_image,
            endpoints=[n.endpoint for n in nodes],
            # The orchestrator is outside the VPC, so it cannot health-check
            # the private addresses the driver will benchmark against.
            admin_endpoints=[
                SolrEndpoint(scheme=n.endpoint.scheme, host=n.ssh.host, port=n.endpoint.port)
                for n in nodes
            ],
            cluster_config=cluster_config,
            handles={"sessions": sessions, "nodes": nodes, "zk_node": zk_node.name},
            metadata={
                "install_method": self.name,
                "image_created": image_created,
                "zookeeper": {
                    "image": ZK_IMAGE,
                    "mode": "standalone",
                    # Written down because it is an asymmetry between the two
                    # Solr nodes, and a reader comparing them deserves to know.
                    "colocated_with": zk_node.name,
                    "host": zk_host,
                },
                "network": "host",
                "data_dir": data_dir,
                "nodes": [
                    {"name": n.name, "solr_url": n.endpoint.base_url} for n in nodes
                ],
            },
        )

    def undeploy(self, deployment: SolrDeployment) -> None:
        """Remove every container and empty the data directory.

        The index is bind-mounted, so it survives the container. Leaving it
        would hand the next cell the previous Solr version's index, which is
        worse than wasted disk because it looks like a result.
        """
        sessions = deployment.handles.get("sessions") or {}
        for name, session in sessions.items():
            for container in (SOLR_CONTAINER, ZK_CONTAINER):
                try:
                    session.run(["docker", "rm", "-f", container], check=False, timeout=120)
                except Exception as exc:  # noqa: BLE001 - undeploy must not raise
                    logger.warning("Could not remove %s on %s: %s", container, name, exc)
        self._clear_data(sessions, (deployment.metadata or {}).get("data_dir"))

    def _clear_data(self, sessions: dict, data_dir: str | None) -> None:
        """Empty the bind-mounted index directory on every node."""
        if not data_dir or data_dir in ("/", ""):
            return
        for name, session in sessions.items():
            try:
                # The contents, never the directory: it is a mount point when
                # a dedicated volume is attached, and removing it would
                # detach the index from its disk.
                session.run(
                    f"sudo find {shlex.quote(data_dir)} -mindepth 1 -maxdepth 1 "
                    f"-exec rm -rf {{}} + 2>/dev/null || true",
                    check=False, timeout=300)
            except Exception as exc:  # noqa: BLE001 - never block a teardown
                logger.warning("Could not clear %s on %s: %s", data_dir, name, exc)

    def collect_logs(self, deployment: SolrDeployment) -> dict[str, bytes]:
        """Container logs from every node, for a failed cell."""
        logs: dict[str, bytes] = {}
        sessions = deployment.handles.get("sessions") or {}
        zk_node = deployment.handles.get("zk_node")
        for name, session in sessions.items():
            wanted = [SOLR_CONTAINER] + ([ZK_CONTAINER] if name == zk_node else [])
            for container in wanted:
                try:
                    result = session.run(
                        ["docker", "logs", "--tail", "2000", container],
                        check=False, timeout=120,
                    )
                except Exception as exc:  # noqa: BLE001 - never mask the real failure
                    logger.debug("Could not collect %s logs from %s: %s", container, name, exc)
                    continue
                body = (result.stdout or "") + (result.stderr or "")
                if body.strip():
                    logs[f"{name}-{container}.log"] = body.encode("utf-8", "replace")
        return logs

    # -- internals ---------------------------------------------------------

    def _session(self, node, infra: ProvisionedInfra) -> SshSession:
        return SshSession(node.ssh, known_hosts=Path(infra.handles["known_hosts"]))

    def _start_zookeeper(self, session: SshSession, host: str) -> None:
        logger.info("Starting ZooKeeper on %s", host)
        session.run(["docker", "rm", "-f", ZK_CONTAINER], check=False)
        session.run([
            "docker", "run", "-d", "--name", ZK_CONTAINER,
            "--network", "host", "--restart", "no",
            "-e", "ZOO_STANDALONE_ENABLED=true",
            "-e", "ZOO_ADMINSERVER_ENABLED=false",
            ZK_IMAGE,
        ], timeout=600)
        self._wait_for_zookeeper(session, host)

    def _wait_for_zookeeper(self, session: SshSession, host: str) -> None:
        """Block until ZooKeeper answers, so Solr does not race it.

        A Solr that starts before ZooKeeper is listening fails its first
        connection and the container exits, which surfaces much later as an
        unhelpful "cluster never became ready".
        """
        deadline = time.monotonic() + _ZK_READY_TIMEOUT
        probe = (
            f"docker exec {ZK_CONTAINER} "
            f"bash -c 'echo ruok | timeout 5 bash -c \"cat > /dev/tcp/127.0.0.1/{ZK_PORT}; "
            f"cat < /dev/tcp/127.0.0.1/{ZK_PORT}\"' 2>/dev/null || "
            f"docker exec {ZK_CONTAINER} zkServer.sh status"
        )
        while time.monotonic() < deadline:
            if session.run(probe, check=False, timeout=30).ok:
                logger.info("ZooKeeper is accepting connections on %s:%d", host, ZK_PORT)
                return
            time.sleep(_ZK_POLL)
        raise DeployError(
            f"ZooKeeper on {host} was not ready within {_ZK_READY_TIMEOUT}s. "
            f"Check `docker logs {ZK_CONTAINER}` on that instance."
        )

    def _image_created(self, session: SshSession, image: str) -> str | None:
        """When the pulled image was built, as an ISO-8601 string.

        This is the only timestamp a nightly has. Solr's own
        ``solr-impl-version`` on a snapshot build reads "[snapshot build,
        details omitted]" and carries no date, so without this the version
        cannot be placed on the chart's x-axis at all. For a nightly the
        image build date is not an approximation of the answer -- it *is* the
        answer.

        Best-effort: a missing date is not a reason to fail a deploy, because
        a release gets its date from the Apache release list anyway.
        """
        result = session.run(
            ["docker", "inspect", "-f", "{{.Created}}", image], check=False, timeout=60)
        created = (result.stdout or "").strip()
        if not result.ok or not created:
            logger.debug("Could not read the build date of %s", image)
            return None
        logger.info("%s was built %s", image, created)
        return created

    def _pull(self, sessions: dict, image: str) -> None:
        """Pull the Solr image on every node at once.

        In parallel because a cold pull is a minute or two and the nodes are
        independent; serially this would be the slowest part of a short cell.
        """
        logger.info("Pulling %s on %d node(s)", image, len(sessions))
        errors: dict[str, Exception] = {}

        def pull(item):
            name, session = item
            try:
                session.run(["docker", "pull", image], timeout=1800)
            except Exception as exc:  # noqa: BLE001 - collected and reported together
                errors[name] = exc

        with ThreadPoolExecutor(max_workers=max(1, len(sessions))) as pool:
            list(pool.map(pull, sessions.items()))
        if errors:
            detail = "; ".join(f"{name}: {exc}" for name, exc in errors.items())
            raise DeployError(f"Could not pull {image}: {detail}")

    def _start_solr(self, sessions: dict, nodes: list, image: str, zk_host: str,
                    cluster_config: ResolvedClusterConfig, version: str,
                    data_dir: str) -> None:
        for node in nodes:
            session = sessions[node.name]
            host = node.endpoint.host
            port = node.endpoint.port
            logger.info("Starting Solr %s on %s (%s:%d)", version, node.name, host, port)
            session.run(["docker", "rm", "-f", SOLR_CONTAINER], check=False)

            argv = [
                "docker", "run", "-d", "--name", SOLR_CONTAINER,
                "--network", "host", "--restart", "no",
                # Bind the index to a known host path; see the module
                # docstring for why this is not left to Docker.
                "-v", f"{data_dir}:/var/solr",
                "-e", f"ZK_HOST={zk_host}",
                # Without SOLR_HOST a node registers whatever hostname the
                # container sees, which the other node cannot resolve.
                "-e", f"SOLR_HOST={host}",
                "-e", f"SOLR_PORT={port}",
            ]
            for key, value in (cluster_config.env or {}).items():
                argv += ["-e", f"{key}={value}"]
            argv.append(image)
            session.run(argv, timeout=300)

            # A container that exits immediately -- a bad flag, an OOM heap
            # setting -- is worth catching here, where its logs are one call
            # away, rather than as a health-check timeout minutes later.
            time.sleep(2)
            running = session.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", SOLR_CONTAINER],
                check=False,
            )
            if "true" not in (running.stdout or ""):
                logs = session.run(["docker", "logs", "--tail", "50", SOLR_CONTAINER], check=False)
                raise DeployError(
                    f"The Solr container exited immediately on {node.name}. Last output:\n"
                    f"{((logs.stdout or '') + (logs.stderr or '')).strip()[:2000]}"
                )

