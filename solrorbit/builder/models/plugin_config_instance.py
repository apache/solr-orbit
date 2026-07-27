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
from dataclasses import dataclass, field
from typing import List


@dataclass
class PluginConfigInstance:
    # name of the initial Python file to load for plugins.
    ENTRY_POINT = "plugin"

    """
    Creates new settings for a plugin attached to a benchmark candidate.

    :param name: Descriptive name for this plugin_config_instance.
    :param format_version: The plugin_config_instance format version
    :param is_core_plugin: A boolean dictating if the plugin is a core plugin.
    :param config_names: A list of config folder names where the raw config can be found. May be ``None``.
    :param root_path: The root path from which bootstrap hooks should be loaded if any. May be ``None``.
    :param config_paths: A non-empty list of paths where the raw config can be found.
    :param variables: A dict containing variable definitions that need to be replaced.
    """
    name: str
    format_version: str
    is_core_plugin: bool = False
    config_names: List[str] = None
    root_path: str = None
    config_paths: List[str] = field(default_factory=list)
    variables: dict = field(default_factory=dict)

    @staticmethod
    def get_entry_point():
        return PluginConfigInstance.ENTRY_POINT

    def __str__(self):
        return "Plugin descriptor for [%s]" % self.name

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)

    def __hash__(self):
        return hash(self.name) ^ hash(self.config_names) ^ hash(self.is_core_plugin)

    def __eq__(self, other):
        return isinstance(other, type(self)) and \
               (self.name, self.config_names, self.is_core_plugin) == (other.name, other.config_names, other.is_core_plugin)
