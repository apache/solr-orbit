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
import jinja2
from jinja2 import select_autoescape

from solrorbit.exceptions import InvalidSyntax, SystemSetupError
from solrorbit.utils import io
from solrorbit.workload import loader


class TemplateRenderer:
    def render_template_file(self, root_path, variables, file_name):
        return self._handle_template_rendering_exceptions(self._render_template_file, root_path, variables, file_name)

    def _render_template_file(self, root_path, variables, file_name):
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(root_path), autoescape=select_autoescape(['html', 'xml']))
        env.filters["version_between"] = loader.version_between
        template = env.get_template(io.basename(file_name))
        # force a new line at the end. Jinja seems to remove it.
        return template.render(variables) + "\n"

    def render_template_string(self, template_string, variables):
        return self._handle_template_rendering_exceptions(self._render_template_string, template_string, variables)

    def _render_template_string(self, template_string, variables):
        env = jinja2.Environment(loader=jinja2.BaseLoader, autoescape=select_autoescape(['html', 'xml']))
        env.filters["version_between"] = loader.version_between
        template = env.from_string(template_string)

        return template.render(variables)

    def _handle_template_rendering_exceptions(self, render_func, *args):
        try:
            return render_func(*args)
        except jinja2.exceptions.TemplateSyntaxError as e:
            raise InvalidSyntax("%s" % str(e))
        except BaseException as e:
            raise SystemSetupError("%s" % str(e))
