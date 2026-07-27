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
from functools import reduce

from solrorbit.exceptions import SystemSetupError


class RepositoryUrlProvider:
    def __init__(self, template_renderer, artifact_variables_provider):
        self.template_renderer = template_renderer
        self.artifact_variables_provider = artifact_variables_provider

    def render_url_for_key(self, host, config_variables, key, mandatory=True):
        try:
            url_template = self._get_value_from_dot_notation_key(config_variables, key)
        except TypeError:
            if mandatory:
                raise SystemSetupError(f"Config key [{key}] is not defined.")
            else:
                return None

        artifact_version = config_variables["distribution"]["version"]
        artifact_variables = self.artifact_variables_provider.get_artifact_variables(host, artifact_version)
        return self.template_renderer.render_template_string(url_template, artifact_variables)

    def _get_value_from_dot_notation_key(self, dict_object, key):
        return reduce(dict.get, key.split("."), dict_object)
