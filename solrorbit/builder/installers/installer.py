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


class Installer(ABC):
    """
    Installers are invoked to prepare Solr data that exists on a host so that a Solr cluster can be started.
    """

    def __init__(self, executor):
        self.executor = executor

    @abstractmethod
    def install(self, host, binaries, all_node_ips):
        """
        Executes the necessary logic to prepare and install Solr on a cluster host

        ;param host: A Host object defining the host on which to install the data
        ;param binaries: A map of components to install to their paths on the host
        ;param all_node_ips: A list of the ips for each node in the cluster. Used for cluster formation
        ;return node: A Node object detailing the installation data of the node on the host
        """
        raise NotImplementedError

    @abstractmethod
    def cleanup(self, host):
        """
        Removes the data that was downloaded, installed, and created on a given host during the test run

        ;param host: A Host object defining the host on which to remove the data
        ;return None
        """
        raise NotImplementedError
