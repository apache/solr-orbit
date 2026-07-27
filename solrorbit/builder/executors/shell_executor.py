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


class ShellExecutor(ABC):
    """
    Executors are used to run shell commands on the cluster hosts. Implementations of this class will use various
    technologies to interface with the hosts of a cluster.
    """

    @abstractmethod
    def execute(self, host, command, **kwargs):
        """
        Executes a list of commands against the provided host

        ;param host: A Host object defining the host on which to execute the commands
        ;param command: A shell command as a string
        ;return output: The output of the command
        """
        raise NotImplementedError
