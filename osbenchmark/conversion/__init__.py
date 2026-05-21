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
OpenSearch Benchmark to Solr Benchmark Conversion Package

This package contains all conversion logic for translating OpenSearch Benchmark
workloads to Solr Benchmark format. Native Solr workloads bypass this package
entirely.

Modules:
- detector: Detect if a workload is OpenSearch or Solr format
- workload: Convert OpenSearch workload structure to Solr format
- schema: Translate OpenSearch mappings to Solr schema
- query: Translate OpenSearch query DSL to Solr syntax
- field: Normalize field names (multi-field patterns)
"""

from .detector import (
    is_opensearch_workload,
    is_opensearch_body,
    has_opensearch_aggregations,
    is_opensearch_only_query,
)

__all__ = [
    "is_opensearch_workload",
    "is_opensearch_body",
    "has_opensearch_aggregations",
    "is_opensearch_only_query",
]
