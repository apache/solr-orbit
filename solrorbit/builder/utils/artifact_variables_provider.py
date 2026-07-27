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
from solrorbit.builder.models.architecture_types import ArchitectureTypes


class ArtifactVariablesProvider:
    def __init__(self, executor):
        self.executor = executor

    def get_artifact_variables(self, host, version=None):
        return {
            "VERSION": version,
            "OSNAME": self._get_os_name(host),
            "ARCH": self._get_arch(host)
        }

    def _get_os_name(self, host):
        os_name = self.executor.execute(host, "uname", output=True)[0]
        return os_name.lower()

    def _get_arch(self, host):
        arch = self.executor.execute(host, "uname -m", output=True)[0]
        return ArchitectureTypes.get_from_hardware_name(arch.lower()).artifact_name
