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


class ConfigInstanceTypes(Enum):
    """
    A ConfigInstanceType is a representation of a configuration category.

    :param config_type: The type of configuration. This corresponds to the subdirectory name where the configurations are stored
    :param supported_config_format_versions: Multiple formats can be defined for the same configuration type. These non-equal
                                             formats are correlated with a version number. ``supported_config_format_versions``
                                             defines the supported version numbers, which is used for listing available configs
    :param default_config_format_version: The default config format version to use when parsing a configuration. This version
                                          will be used if no corresponding CLI format version is specified by the user
    """

    def __init__(self, config_type, supported_config_format_versions, default_config_format_version):
        self.config_type = config_type
        self.supported_config_format_versions = supported_config_format_versions
        self.default_config_format_version = default_config_format_version

    PLUGIN = "plugins", [1], 1
