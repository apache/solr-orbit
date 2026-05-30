# SPDX-License-Identifier: Apache-2.0
#
# Modifications by Apache Solr contributors; see git log for details.
# Licensed under the Apache License, Version 2.0.
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.
# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

from abc import ABC, abstractmethod


class Launcher(ABC):
    """
    Launchers are used to start and stop Solr on the nodes in a self-managed cluster.
    """

    def __init__(self, shell_executor):
        self.shell_executor = shell_executor

    @abstractmethod
    def start(self, host, node_configurations):
        """
        Starts the Solr nodes on a given host

        ;param host: A Host object defining the host on which to start the nodes
        ;param node_configurations: A list of NodeConfiguration objects detailing the installation data of the nodes on the host
        ;return nodes: A list of Node objects defining the nodes running on a host
        """
        raise NotImplementedError

    @abstractmethod
    def stop(self, host, nodes):
        """
        Stops the Solr nodes on a given host

        ;param host: A Host object defining the host on which to stop the nodes
        ;param nodes: A list of Node objects defining the nodes running on a host
        ;return nodes: A list of Node objects representing Solr nodes that were successfully stopped on the host
        """
        raise NotImplementedError
