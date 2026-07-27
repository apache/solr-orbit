# SPDX-License-Identifier: Apache-2.0
#
# Originally developed by OpenSearch Contributors; licensed under the Apache License, Version 2.0.
# License header was absent in the original source; added when adopted into Apache Solr Orbit.
# Modified by Apache Solr contributors; see git log for details.
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
from dataclasses import dataclass, field
from typing import List

from solrorbit.builder.models.cluster_flavors import ClusterFlavor
from solrorbit.builder.models.cluster_infra_providers import ClusterInfraProvider


@dataclass
class ClusterConfigInstance:
    ENTRY_POINT = "config"

    """
    Creates new settings for a benchmark candidate.

    :param names: Descriptive name(s) for this cluster-config.
    :param root_path: The root path from which bootstrap hooks should be loaded if any. May be ``None``.
    :param provider: The infrastructure provider for the cluster
    :param flavor: The flavor of cluster to be provisioned
    :param config_paths: A non-empty list of paths where the raw config can be found.
    :param variables: A dict containing variable definitions that need to be replaced.
    """
    names: List[str]
    root_path: str
    provider: ClusterInfraProvider = ClusterInfraProvider.LOCAL
    flavor: ClusterFlavor = ClusterFlavor.SELF_MANAGED
    config_paths: List[str] = field(default_factory=list)
    variables: dict = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.names, str):
            self.names = [self.names]

    @staticmethod
    def get_entry_point():
        return ClusterConfigInstance.ENTRY_POINT

    @property
    def name(self):
        return "+".join(self.names)

    # Adapter method for BootstrapHookHandler
    @property
    def config(self):
        return self.name

    @property
    def safe_name(self):
        return "_".join(self.names)

    def __str__(self):
        return self.name
