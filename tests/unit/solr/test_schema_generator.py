# SPDX-License-Identifier: Apache-2.0
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for osbenchmark/conversion/schema.py"""

import unittest

from osbenchmark.conversion.schema import (
    translate_opensearch_mapping,
    generate_schema_xml,
)


class TestTranslateOpenSearchMapping(unittest.TestCase):
    """Test OpenSearch to Solr mapping translation."""

    def test_simple_field_translation(self):
        """Test basic field type translation without multi-fields."""
        properties = {
            "title": {"type": "text"},
            "count": {"type": "integer"},
            "price": {"type": "double"},
        }

        field_defs, copy_fields = translate_opensearch_mapping(properties)

        # Check field definitions
        self.assertEqual("text_general", field_defs["title"]["type"])
        self.assertEqual("pint", field_defs["count"]["type"])
        self.assertEqual("pdouble", field_defs["price"]["type"])

        # No copy fields for simple fields
        self.assertEqual(0, len(copy_fields))

    def test_keyword_field_has_docvalues(self):
        """Test that keyword fields get docValues=True."""
        properties = {
            "country_code": {"type": "keyword"},
        }

        field_defs, _copy_fields = translate_opensearch_mapping(properties)

        self.assertEqual("string", field_defs["country_code"]["type"])
        self.assertTrue(field_defs["country_code"]["docValues"])

    def test_multi_field_with_raw_suffix(self):
        """Test multi-field with .raw sub-field creates separate field and copyField."""
        properties = {
            "country_code": {
                "type": "text",
                "fields": {
                    "raw": {"type": "keyword"}
                }
            }
        }

        field_defs, copy_fields = translate_opensearch_mapping(properties)

        # Main field should be text_general
        self.assertEqual("text_general", field_defs["country_code"]["type"])

        # Sub-field should be created with underscore naming
        self.assertIn("country_code_raw", field_defs)
        self.assertEqual("string", field_defs["country_code_raw"]["type"])
        self.assertTrue(field_defs["country_code_raw"]["docValues"])

        # Should have one copyField directive
        self.assertEqual(1, len(copy_fields))
        self.assertEqual(("country_code", "country_code_raw"), copy_fields[0])

    def test_multi_field_with_keyword_suffix(self):
        """Test multi-field with .keyword sub-field."""
        properties = {
            "name": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword"}
                }
            }
        }

        field_defs, copy_fields = translate_opensearch_mapping(properties)

        # Sub-field should be created
        self.assertIn("name_keyword", field_defs)
        self.assertEqual("string", field_defs["name_keyword"]["type"])
        self.assertTrue(field_defs["name_keyword"]["docValues"])

        # Should have copyField directive
        self.assertEqual(1, len(copy_fields))
        self.assertEqual(("name", "name_keyword"), copy_fields[0])

    def test_multi_field_with_multiple_subfields(self):
        """Test field with multiple sub-fields."""
        properties = {
            "title": {
                "type": "text",
                "fields": {
                    "raw": {"type": "keyword"},
                    "sort": {"type": "keyword"}
                }
            }
        }

        field_defs, copy_fields = translate_opensearch_mapping(properties)

        # Main field
        self.assertEqual("text_general", field_defs["title"]["type"])

        # Both sub-fields should be created
        self.assertIn("title_raw", field_defs)
        self.assertIn("title_sort", field_defs)

        # Should have two copyField directives
        self.assertEqual(2, len(copy_fields))
        self.assertIn(("title", "title_raw"), copy_fields)
        self.assertIn(("title", "title_sort"), copy_fields)


class TestGenerateSchemaXML(unittest.TestCase):
    """Test schema.xml generation."""

    def test_simple_schema_generation(self):
        """Test basic schema generation without multi-fields."""
        field_defs = {
            "title": {"type": "text_general", "indexed": True, "stored": True},
            "count": {"type": "pint", "indexed": True, "stored": True},
        }

        schema_xml = generate_schema_xml(field_defs)

        # Check that fields are present
        self.assertIn('<field name="title" type="text_general"', schema_xml)
        self.assertIn('<field name="count" type="pint"', schema_xml)

        # Check required SolrCloud fields
        self.assertIn('<field name="id"', schema_xml)
        self.assertIn('<field name="_version_"', schema_xml)

    def test_schema_with_copyfields(self):
        """Test schema generation with copyField directives."""
        field_defs = {
            "country_code": {"type": "text_general", "indexed": True, "stored": True},
            "country_code_raw": {"type": "string", "indexed": True, "stored": True, "docValues": True},
        }
        copy_fields = [("country_code", "country_code_raw")]

        schema_xml = generate_schema_xml(field_defs, copy_fields=copy_fields)

        # Check that both fields are present
        self.assertIn('<field name="country_code" type="text_general"', schema_xml)
        self.assertIn('<field name="country_code_raw" type="string"', schema_xml)

        # Check that copyField directive is present
        self.assertIn('<copyField source="country_code" dest="country_code_raw"', schema_xml)

    def test_schema_with_multiple_copyfields(self):
        """Test schema generation with multiple copyField directives."""
        field_defs = {
            "title": {"type": "text_general", "indexed": True, "stored": True},
            "title_raw": {"type": "string", "indexed": True, "stored": True, "docValues": True},
            "title_sort": {"type": "string", "indexed": True, "stored": True, "docValues": True},
        }
        copy_fields = [
            ("title", "title_raw"),
            ("title", "title_sort"),
        ]

        schema_xml = generate_schema_xml(field_defs, copy_fields=copy_fields)

        # Check that all copyField directives are present
        self.assertIn('<copyField source="title" dest="title_raw"', schema_xml)
        self.assertIn('<copyField source="title" dest="title_sort"', schema_xml)

    def test_docvalues_attribute_in_schema(self):
        """Test that docValues attribute is properly rendered."""
        field_defs = {
            "name_keyword": {"type": "string", "indexed": True, "stored": True, "docValues": True},
        }

        schema_xml = generate_schema_xml(field_defs)

        self.assertIn('docValues="true"', schema_xml)


if __name__ == "__main__":
    unittest.main()
