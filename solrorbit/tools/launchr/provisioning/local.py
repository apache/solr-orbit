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
"""Provisioning on the machine launchr is running on.

A no-op: there is nothing to create and nothing to destroy. The load driver is
this process, so :meth:`run_on_driver` is a subprocess.

This co-locates the driver with Solr, which is explicitly *not* how a
publishable benchmark is run -- see the report's ``infra.provider: "local"``,
which exists so reportr can label the data as developer-local.
"""

import logging
import platform
from typing import ClassVar

from solrorbit.tools.launchr import orbit
from solrorbit.tools.launchr.models import (
    NodeHandle,
    OrbitInvocation,
    OrbitResult,
    ProfileSpec,
    ProvisionedInfra,
    SolrEndpoint,
)

logger = logging.getLogger(__name__)


def host_facts() -> dict:
    """Describe this machine, for the report's ``infra.host`` block."""
    facts: dict = {
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
    }
    try:
        import psutil

        facts["cores"] = psutil.cpu_count(logical=True)
        facts["physical_cores"] = psutil.cpu_count(logical=False)
        facts["memory_gb"] = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception as exc:  # noqa: BLE001 - host facts are nice to have, not essential
        logger.debug("Could not read host facts from psutil: %s", exc)
    try:
        import cpuinfo

        facts["cpu"] = cpuinfo.get_cpu_info().get("brand_raw")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read CPU info: %s", exc)
    return {k: v for k, v in facts.items() if v is not None}


class LocalProvisioning:
    """Uses this machine. Creates nothing, destroys nothing."""

    API_VERSION: ClassVar[int] = 1
    name: ClassVar[str] = "local"

    def provision(self, profile: ProfileSpec, *, nodes: int) -> ProvisionedInfra:
        if nodes != 1:
            # Honest failure beats a benchmark that silently ran one node while
            # the report claimed three.
            from solrorbit.tools.launchr.errors import ConfigError

            raise ConfigError(
                f"Provisioning profile {profile.name!r} asks for {nodes} nodes, but the "
                f"'local' strategy supports exactly 1. Multi-node local clusters need a "
                f"compose-based install method, which is not part of this phase."
            )
        endpoint = SolrEndpoint(scheme="http", host="127.0.0.1", port=profile.port)
        return ProvisionedInfra(
            profile=profile,
            strategy=self.name,
            install_method=profile.install_method,
            nodes=[NodeHandle(name="solr-1", endpoint=endpoint)],
            driver=None,  # the driver is this process
            metadata={"provider": "local", "nodes": 1, "host": host_facts()},
        )

    def run_on_driver(self, infra: ProvisionedInfra, invocation: OrbitInvocation) -> OrbitResult:
        return orbit.run_locally(invocation)

    def teardown(self, infra: ProvisionedInfra) -> None:
        logger.debug("Nothing to tear down for the 'local' strategy")
