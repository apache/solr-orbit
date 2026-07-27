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


class BinaryBuilder(ABC):
    """
    A BinaryBuilder is used to wrap the executor calls necessary for constructing binaries from code
    """

    @abstractmethod
    def build(self, host, build_commands, override_source_directory):
        """
        Runs the provided commands on the given host to build binaries

        :param host: A host object representing the machine on which to run the commands
        :param build_commands: A list of strings representing sequential bash commands used to build the binaries
        :param override_source_directory: A string representing the source directory where the pre-binary code is located
        :return None
        """
        raise NotImplementedError
