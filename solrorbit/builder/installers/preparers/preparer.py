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


class Preparer(ABC):
    """
    A preparer is used for preparing the installation of a node by setting up the filesystem, binaries, and install hooks
    """

    def __init__(self, executor):
        self.executor = executor

    @abstractmethod
    def prepare(self, host, binaries):
        """
        Prepares the filesystem and binaries on a node

        ;param host: A Host object defining the host on which to prepare the data
        ;param binaries: A map of components to download paths on the host
        ;return node: A Node object detailing the installation data of the node on the host. May be None if no Node was generated
        """
        raise NotImplementedError

    @abstractmethod
    def get_config_vars(self, host, node, all_node_ips):
        """
        Gets the config file(s) variables associated with the given preparer

        ;param host: A Host object defining a machine within a cluster
        ;param node: A Node object defining the node on a host
        ;param all_node_ips: A list of the ips for each node in the cluster. Used for cluster formation
        ;return dict: A key value pair of the config variables
        """
        raise NotImplementedError

    @abstractmethod
    def get_config_paths(self):
        """
        Returns the config paths list
        """
        raise NotImplementedError

    @abstractmethod
    def invoke_install_hook(self, host, phase, variables, env):
        """
        Invokes the associated install hook

        ;param host: A Host object defining the host on which to invoke the install hook
        ;param phase: The BoostrapPhase of install hook
        ;param variables: Key value pairs to be passed to the install hook
        ;param env: Key value pairs of environment variables to be passed ot the install hook
        ;return None
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
