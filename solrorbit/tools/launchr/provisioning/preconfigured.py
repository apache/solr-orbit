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
"""Benchmark a Solr cluster someone else is running.

Creates nothing and destroys nothing: the profile names a URL, launchr
health-checks it, benchmarks it, and leaves it alone. For an existing benchmark
lab, or for pointing launchr at a cluster you started by hand.

Pair it with the ``none`` install method -- launchr must not try to swap the
Solr version on a cluster it does not own. Because the version under test is
whatever is already running, a profile like this makes sense for exactly one
version per run; the orchestrator checks that what answered matches what was
asked for.
"""

import logging
from typing import ClassVar

from solrorbit.tools.launchr import orbit
from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.models import (
    NodeHandle,
    OrbitInvocation,
    OrbitResult,
    ProfileSpec,
    ProvisionedInfra,
    SolrEndpoint,
)
from solrorbit.tools.launchr.provisioning.local import host_facts

logger = logging.getLogger(__name__)


class PreconfiguredProvisioning:
    """Uses a Solr cluster that already exists, named by ``solr_url``."""

    API_VERSION: ClassVar[int] = 1
    name: ClassVar[str] = "preconfigured"

    def provision(self, profile: ProfileSpec, *, nodes: int) -> ProvisionedInfra:
        if not profile.solr_url:
            raise ConfigError(
                f"Provisioning profile {profile.name!r} uses the 'preconfigured' strategy "
                f"but sets no solr_url. Add e.g. solr_url: \"http://solr-lab.internal:8983\"."
            )
        urls = [u.strip() for u in str(profile.solr_url).split(",") if u.strip()]
        try:
            endpoints = [SolrEndpoint.from_url(u) for u in urls]
        except ValueError as exc:
            raise ConfigError(f"Provisioning profile {profile.name!r}: {exc}") from exc

        return ProvisionedInfra(
            profile=profile,
            strategy=self.name,
            install_method=profile.install_method,
            nodes=[NodeHandle(name=f"solr-{i + 1}", endpoint=e) for i, e in enumerate(endpoints)],
            driver=None,
            metadata={
                "provider": "preconfigured",
                "nodes": len(endpoints),
                "solr_url": profile.solr_url,
                "host": host_facts(),
            },
        )

    def run_on_driver(self, infra: ProvisionedInfra, invocation: OrbitInvocation) -> OrbitResult:
        return orbit.run_locally(invocation)

    def teardown(self, infra: ProvisionedInfra) -> None:
        logger.debug("Nothing to tear down for the 'preconfigured' strategy")
