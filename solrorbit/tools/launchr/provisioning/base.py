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
"""The provisioning strategy contract.

A provisioning strategy owns three things:

1. creating the machines a profile group's cells run on,
2. **running Solr Orbit on the right one of them** -- the load driver lives
   wherever the strategy says it does: this process for ``local``, an SSH'd
   instance on EC2, a Job in a Kubernetes cluster,
3. destroying whatever it created.

Point 2 is why there is no separate "driver" plugin type: where the benchmark
executes is a property of the infrastructure, and keeping it here leaves the
orchestrator's lifecycle loop free of transport details.
"""

from typing import ClassVar, Protocol, runtime_checkable

from solrorbit.tools.launchr.models import (
    OrbitInvocation,
    OrbitResult,
    ProfileSpec,
    ProvisionedInfra,
)


@runtime_checkable
class ProvisioningStrategy(Protocol):
    """Creates, drives and destroys the infrastructure a benchmark runs on."""

    #: Bumped when this Protocol changes incompatibly.
    API_VERSION: ClassVar[int] = 1

    #: The name this strategy is configured by, e.g. ``local``.
    name: ClassVar[str]

    def provision(self, profile: ProfileSpec, *, nodes: int) -> ProvisionedInfra:
        """Create infrastructure for ``nodes`` Solr nodes.

        ``nodes`` is the maximum any cell in the group needs, which may exceed
        ``profile.nodes``: profiles differing only in node count share a group.
        """
        ...

    def run_on_driver(self, infra: ProvisionedInfra, invocation: OrbitInvocation) -> OrbitResult:
        """Run Solr Orbit wherever this strategy's load driver lives."""
        ...

    def teardown(self, infra: ProvisionedInfra) -> None:
        """Destroy everything :meth:`provision` created.

        Must be safe to call twice, and must not raise on partially-created
        state -- it runs in a ``finally`` and is the last line of defence
        against leaking billable resources.
        """
        ...
