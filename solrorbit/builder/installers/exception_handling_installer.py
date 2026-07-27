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
from solrorbit.builder.installers.installer import Installer
from solrorbit.exceptions import InstallError


class ExceptionHandlingInstaller(Installer):
    def __init__(self, installer, executor=None):
        super().__init__(executor)
        self.installer = installer

    def install(self, host, binaries, all_node_ips):
        try:
            return self.installer.install(host, binaries, all_node_ips)
        except Exception as e:
            raise InstallError(f"Installing node on host \"{host}\" failed", e)

    def cleanup(self, host):
        try:
            return self.installer.cleanup(host)
        except Exception as e:
            raise InstallError(f"Cleaning up install data on host \"{host}\" failed", e)
