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
"""
The ClusterBuilder is the interface into the builder system from the Dispatcher. This class orchestrates all of the
builder subcomponents used to create and delete a cluster.
"""
class ClusterBuilder:
    def __init__(self, provisioner, downloader, installer, launcher):
        self.provisioner = provisioner
        self.downloader = downloader
        self.installer = installer
        self.launcher = launcher

    def create_cluster(self):
        """
        Creates a cluster using the builder subcomponents

        ;return cluster: A Cluster object defining the cluster that was created
        """
        raise NotImplementedError

    def delete_cluster(self, cluster):
        """
        Deletes a cluster using the builder subcomponents

        ;param cluster: A Cluster object defining the cluster to be deleted
        ;return None
        """
        raise NotImplementedError
