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
import os
from unittest import TestCase
from unittest.mock import Mock

from solrorbit.builder.configs.listers.plugin_config_instance_lister import PluginConfigInstanceLister
from solrorbit.builder.models.plugin_config_instance import PluginConfigInstance


class PluginConfigInstanceListerTest(TestCase):
    def setUp(self):
        self.config_path_resolver = Mock()
        self.plugin_config_instance_lister = PluginConfigInstanceLister(self.config_path_resolver)

        builder_tests_root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.config_path_resolver.resolve_config_path.return_value = os.path.join(builder_tests_root_dir, "data", "plugins", "v1")

    def test_list_plugin_config_instances(self):
        plugin_config_instances = self.plugin_config_instance_lister.list_plugin_config_instances()
        print(plugin_config_instances)

        self.assertEqual(plugin_config_instances, [
            PluginConfigInstance(name="complex-plugin", format_version="v1", config_names=["config-a"]),
            PluginConfigInstance(name="complex-plugin", format_version="v1", config_names=["config-b"]),
            PluginConfigInstance(name="my-analysis-plugin", format_version="v1", is_core_plugin=True),
            PluginConfigInstance(name="my-core-plugin-with-config", format_version="v1", is_core_plugin=True),
            PluginConfigInstance(name="my-ingest-plugin", format_version="v1", is_core_plugin=True)
        ])
