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
from enum import Enum


class ArchitectureTypes(Enum):
    """
    Represents a machine's architecture type

    :param hardware_name: The value returned by the machine when querying the architecture. Obtained via `uname -m` for unix machines
    :param artifact_name: The value used by artifacts to represent the architecture
    """

    def __init__(self, hardware_name, artifact_name):
        self.hardware_name = hardware_name
        self.artifact_name = artifact_name

    ARM = "aarch64", "arm64"
    x86 = "x86_64", "x64"

    @staticmethod
    def get_from_hardware_name(hardware_name):
        for arch_type in ArchitectureTypes:
            if arch_type.hardware_name == hardware_name:
                return arch_type

        raise ValueError
