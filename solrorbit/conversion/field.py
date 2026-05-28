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

"""
OpenSearch to Solr Field Name Normalization

Handles the conversion of OpenSearch multi-field patterns (dot notation)
to Solr field naming conventions (underscore notation).
"""


def normalize_field_name(field: str) -> str:
    """
    Normalize OpenSearch field names to Solr equivalents using underscore convention.

    OpenSearch supports multi-field patterns where a text field can have
    keyword sub-fields like 'country_code.raw' or 'name.keyword'. Solr uses
    a different pattern: separate fields with copyField directives.

    This function translates OpenSearch dot notation to Solr underscore convention:
    - country_code.raw → country_code_raw
    - name.keyword → name_keyword
    - title.sort → title_sort

    The schema generator automatically creates these sub-fields with appropriate
    types and copyField directives from the main field.

    Args:
        field: OpenSearch field name (e.g., "country_code.raw")

    Returns:
        Normalized Solr field name (e.g., "country_code_raw")

    Examples:
        >>> normalize_field_name("country_code.raw")
        'country_code_raw'
        >>> normalize_field_name("name.keyword")
        'name_keyword'
        >>> normalize_field_name("title")
        'title'
    """
    if "." in field:
        # Replace dots with underscores to convert OpenSearch multi-field syntax
        # to Solr field naming convention
        # Example: "country_code.raw" → "country_code_raw"
        return field.replace(".", "_")

    # No sub-field, return as-is
    return field
