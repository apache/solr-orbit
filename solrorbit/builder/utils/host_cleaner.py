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
import logging

from solrorbit.utils import console


class HostCleaner:
    def __init__(self, path_manager):
        self.logger = logging.getLogger(__name__)
        self.path_manager = path_manager

    def cleanup(self, host, preserve_install):
        if preserve_install:
            console.info("Preserving benchmark candidate installation.", logger=self.logger)
            return

        self.logger.info("Wiping benchmark candidate installation at [%s].", host.node.binary_path)

        for data_path in host.node.data_paths:
            self.path_manager.delete_path(host, data_path)

        self.path_manager.delete_path(host, host.node.binary_path)
