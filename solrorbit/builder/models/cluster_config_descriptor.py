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
from solrorbit.builder.models.cluster_config_types import ClusterConfigType


@dataclass
class ClusterConfigDescriptor:
    """
    A ClusterConfigInstanceDescriptor represents a single source of provision config definition. These descriptors serve
    as an intermediary store of the cluster to be provisioned. Descriptors are created from each config source and played
    on top of one another to create the final ClusterConfigInstance to be used by the Builder system.

    :param name: Descriptive name for this provision config instance source.
    :param description: A description for this provision config instance source.
    :param type: The type of provision config instance source. Can be a standalone config instance or a mixin
    :param root_paths: A list of root paths from which bootstrap hooks should be loaded if any. May be empty.
    :param provider: The infrastructure provider for the cluster. May be ``None``.
    :param flavor: The flavor of cluster to be provisioned. May be ``None``.
    :param config_paths: A list of paths where the raw config can be found. May be empty.
    :param variables: A dict containing variable definitions that need to be replaced.
    """

    name: str
    description: str = ""
    type: ClusterConfigType = ClusterConfigType.CLUSTER_CONFIG_INSTANCE
    root_paths: List[str] = field(default_factory=list)
    provider: ClusterInfraProvider = None
    flavor: ClusterFlavor = None
    config_paths: List[str] = field(default_factory=list)
    variables: dict = field(default_factory=dict)
