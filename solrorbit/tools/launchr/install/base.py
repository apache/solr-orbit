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
"""The Solr install method contract.

An install method brings one Solr version up on already-provisioned
infrastructure with a given cluster-config, and takes it back down again
leaving no data behind -- the next cell must start from an empty index.
"""

from typing import ClassVar, Protocol, runtime_checkable

from solrorbit.tools.launchr.models import (
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrDeployment,
)


@runtime_checkable
class SolrInstallMethod(Protocol):
    """Deploys and undeploys Solr on provisioned infrastructure."""

    #: Bumped when this Protocol changes incompatibly.
    API_VERSION: ClassVar[int] = 1

    #: The name this method is configured by, e.g. ``docker``.
    name: ClassVar[str]

    def deploy(self, infra: ProvisionedInfra, version: str, image: str | None,
               cluster_config: ResolvedClusterConfig) -> SolrDeployment:
        """Start Solr and return how to reach it.

        May return before Solr is fully ready; the orchestrator health-checks
        the returned endpoints itself and that is what gates the benchmark.
        """
        ...

    def undeploy(self, deployment: SolrDeployment) -> None:
        """Stop Solr and delete its data. Safe to call on a failed deploy."""
        ...

    def collect_logs(self, deployment: SolrDeployment) -> dict[str, bytes]:
        """Return Solr's own logs, keyed by filename, for a failed cell.

        Called before :meth:`undeploy`, because undeploying usually destroys
        them. Returning ``{}`` is always acceptable.
        """
        ...
