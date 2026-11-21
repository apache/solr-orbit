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
"""Do not manage Solr at all.

For a cluster launchr does not own: it is already running, someone else decides
what version it runs, and launchr must not touch its lifecycle. Pair with the
``preconfigured`` provisioning strategy.
"""

import logging
from typing import ClassVar

from solrorbit.tools.launchr.models import (
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrDeployment,
)

logger = logging.getLogger(__name__)


class NoOpInstall:
    """Leaves Solr exactly as found."""

    API_VERSION: ClassVar[int] = 1
    name: ClassVar[str] = "none"

    def deploy(self, infra: ProvisionedInfra, version: str, image: str | None,
               cluster_config: ResolvedClusterConfig) -> SolrDeployment:
        if cluster_config.env:
            # The settings cannot be applied to a cluster we do not manage, and a
            # report claiming them would be false.
            logger.warning(
                "cluster_config %r sets %s, but install_method 'none' cannot apply anything "
                "to an externally managed cluster. The report will record them as requested, "
                "not applied.",
                cluster_config.name, ", ".join(sorted(cluster_config.env)),
            )
        return SolrDeployment(
            infra=infra,
            version=version,
            image=None,
            endpoints=infra.endpoints,
            cluster_config=cluster_config,
            metadata={"externally_managed": True},
        )

    def undeploy(self, deployment: SolrDeployment) -> None:
        logger.debug("install_method 'none': leaving the external cluster running")

    def collect_logs(self, deployment: SolrDeployment) -> dict[str, bytes]:
        return {}
