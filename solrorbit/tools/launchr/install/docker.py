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
"""Run Solr in a Docker container on the local machine.

This wraps :class:`solrorbit.builder.solr_provisioner.SolrDockerLauncher`, the
same launcher Solr Orbit's own ``docker`` pipeline uses, rather than growing a
second container-management path. It is single-container with embedded
ZooKeeper in SolrCloud mode, and it already knows that ``-c`` is required below
Solr 10 and rejected from 10 onwards.

The cluster-config is applied as container environment: ``SOLR_HEAP``,
``GC_TUNE`` and ``SOLR_OPTS``.
"""

import logging
import subprocess
from typing import ClassVar

from solrorbit.builder.solr_provisioner import SolrDockerLauncher
from solrorbit.tools.launchr import translate
from solrorbit.tools.launchr.errors import DeployError
from solrorbit.tools.launchr.models import (
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrDeployment,
)

logger = logging.getLogger(__name__)

#: Container name prefix. Distinct from Solr Orbit's own ``solr-orbit``
#: container so a launchr run and a hand-run ``--pipeline=docker`` do not fight
#: over the same name.
CONTAINER_PREFIX = "launchr-solr"


def resolve_image(version: str, *, registry: str, nightly_registry: str) -> str:
    """Return the full image reference for a Solr version.

    Mirrors ``SolrDockerLauncher``'s rule so the image recorded in the report is
    the image that was actually pulled.
    """
    repository = nightly_registry if "SNAPSHOT" in version.upper() else registry
    return f"{repository}:{version}"


class DockerInstall:
    """Starts one Solr container per cell, and removes it afterwards."""

    API_VERSION: ClassVar[int] = 1
    name: ClassVar[str] = "docker"

    def __init__(self, *, registry: str = "solr", nightly_registry: str = "apache/solr-nightly"):
        self.registry = registry
        self.nightly_registry = nightly_registry

    def deploy(self, infra: ProvisionedInfra, version: str, image: str | None,
               cluster_config: ResolvedClusterConfig) -> SolrDeployment:
        endpoints = infra.endpoints
        if len(endpoints) != 1:
            raise DeployError(
                f"The 'docker' install method runs a single container, but the profile "
                f"provisioned {len(endpoints)} Solr endpoints."
            )
        endpoint = endpoints[0]
        resolved_image = image or resolve_image(
            version, registry=self.registry, nightly_registry=self.nightly_registry
        )
        container = f"{CONTAINER_PREFIX}-{endpoint.port}"

        # SolrDockerLauncher reads heap/GC/opts off an object with a `.variables`
        # dict; it needs nothing else from a real ClusterConfigInstance.
        variables = translate.to_orbit_variables(cluster_config.env)
        launcher = SolrDockerLauncher(
            port=endpoint.port,
            startup_timeout=infra.profile.startup_timeout,
            container_name=container,
            cluster_config=_Variables(variables),
            image_repository=self.registry,
            nightly_image_repository=self.nightly_registry,
        )

        logger.info("Starting Solr %s as container %s from %s", version, container, resolved_image)
        try:
            launcher.start(version_tag=version, mode="cloud")
        except Exception as exc:
            # No SolrDeployment exists yet, so the orchestrator can neither
            # collect logs nor undeploy: read the log and remove the container
            # here, and hand the log over on the error.
            logs = self._container_logs(container)
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, text=True)
            raise DeployError(
                f"Could not start Solr {version} in Docker: {exc}", logs=logs
            ) from exc

        return SolrDeployment(
            infra=infra,
            version=version,
            image=resolved_image,
            endpoints=[endpoint],
            cluster_config=cluster_config,
            handles={"launcher": launcher, "container": container},
            metadata={
                "container_pid": launcher.pid,
                # The only x-axis position a nightly has; see
                # solrorbit.tools.launchr.versions.SOURCE_IMAGE.
                "image_created": _image_created(resolved_image),
            },
        )

    def undeploy(self, deployment: SolrDeployment) -> None:
        launcher = deployment.handles.get("launcher")
        container = deployment.handles.get("container")
        if launcher is not None:
            launcher.stop()
        elif container:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, text=True)
        # The container ran without a data volume, so its index died with it and
        # the next cell starts from empty.

    def collect_logs(self, deployment: SolrDeployment) -> dict[str, bytes]:
        container = deployment.handles.get("container")
        return self._container_logs(container) if container else {}

    @staticmethod
    def _container_logs(container: str) -> dict[str, bytes]:
        try:
            result = subprocess.run(
                ["docker", "logs", container], capture_output=True, timeout=60, check=False
            )
        except Exception as exc:  # noqa: BLE001 - log collection must never mask the real failure
            logger.warning("Could not collect Docker logs for %s: %s", container, exc)
            return {}
        output = (result.stdout or b"") + (result.stderr or b"")
        return {f"{container}.log": output} if output else {}


def _image_created(image: str) -> str | None:
    """When the local image was built, as an ISO-8601 string. Best effort."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.Created}}", image],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except Exception as exc:  # noqa: BLE001 - a missing date never fails a deploy
        logger.debug("Could not read the build date of %s: %s", image, exc)
        return None
    created = (result.stdout or "").strip()
    return created or None


class _Variables:
    """Minimal stand-in for a Solr Orbit ``ClusterConfigInstance``."""

    def __init__(self, variables: dict):
        self.variables = variables
