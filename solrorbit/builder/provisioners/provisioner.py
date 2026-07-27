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
from abc import ABC, abstractmethod


class Provisioner(ABC):
    """
    Provisioners are used to create and destroy any infrastructure required to construct a cluster.
    """
    def __init__(self):
        pass

    @abstractmethod
    def provision_infrastructure(self):
        """
        Provisions the necessary infrastructure for creating a cluster

        ;return hosts: A list of Host objects defining the hosts in a cluster
        """
        raise NotImplementedError

    @abstractmethod
    def tear_down_infrastructure(self, cluster):
        """
        Destroys the infrastructure created for a given cluster

        ;param cluster: A Cluster object representing the cluster to be torn down
        ;return None
        """
        raise NotImplementedError
