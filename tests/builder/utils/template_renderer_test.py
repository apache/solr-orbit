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
from unittest import TestCase, mock
from unittest.mock import Mock

from jinja2 import TemplateSyntaxError

from solrorbit.builder.utils.template_renderer import TemplateRenderer
from solrorbit.exceptions import InvalidSyntax, SystemSetupError


class TemplateRendererTest(TestCase):
    def setUp(self):
        self.root_path = "fake"
        self.variables = {}
        self.file_name = "non-existent.txt"
        self.template_renderer = TemplateRenderer()

    @mock.patch('jinja2.Environment.get_template')
    def test_successful_render(self, get_template):
        template = Mock()
        get_template.return_value = template
        template.render.return_value = "template as string"

        self.template_renderer.render_template_file(self.root_path, self.variables, self.file_name)

    def test_version_between_filter(self):
        self.assertEqual(self.template_renderer.render_template_string('{{ "2.0.0" | version_between("2.0.0", "3.0.0")}}',
                                                                       self.variables), "True")
        self.assertEqual(self.template_renderer.render_template_string('{{ "2.2.3" | version_between("2.0.0", "3.0.0")}}',
                                                                       self.variables), "True")
        self.assertEqual(self.template_renderer.render_template_string('{{ "3.0.0" | version_between("2.0.0", "3.0.0")}}',
                                                                       self.variables), "True")
        self.assertEqual(self.template_renderer.render_template_string('{{ "1.9.0" | version_between("2.0.0", "3.0.0")}}',
                                                                       self.variables), "False")
        self.assertEqual(self.template_renderer.render_template_string('{{ "3.0.1" | version_between("2.0.0", "3.0.0")}}',
                                                                       self.variables), "False")

    @mock.patch('jinja2.Environment.get_template')
    def test_template_syntax_error(self, get_template):
        get_template.side_effect = TemplateSyntaxError("fake", 12)

        with self.assertRaises(InvalidSyntax):
            self.template_renderer.render_template_file(self.root_path, self.variables, self.file_name)

    @mock.patch('jinja2.Environment.get_template')
    def test_unknown_error(self, get_template):
        template = Mock()
        get_template.return_value = template
        template.render.side_effect = RuntimeError()

        with self.assertRaises(SystemSetupError):
            self.template_renderer.render_template_file(self.root_path, self.variables, self.file_name)
