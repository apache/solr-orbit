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
Workload Format Detection

Determines whether a workload is OpenSearch Benchmark format (requiring conversion)
or native Solr Benchmark format (no conversion needed).
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


# OpenSearch-specific operation types
OPENSEARCH_OPERATIONS = {
    "create-index",
    "delete-index",
    "cluster-health",
    "refresh",
    "force-merge",
    "index",  # OpenSearch uses "index", Solr uses "bulk-index"
    "search",  # Could be either, check param-source
}

# Solr-specific operation types
SOLR_OPERATIONS = {
    "create-collection",
    "delete-collection",
    "bulk-index",
    "commit",
    "optimize",
}

# OpenSearch-specific param sources
OPENSEARCH_PARAM_SOURCES = {
    "opensearch-bulk-source",
    "opensearch-search-source",
}

# Solr-specific param sources
SOLR_PARAM_SOURCES = {
    "solr-bulk-source",
    "solr-search-source",
}


def is_opensearch_workload(workload) -> bool:
    """
    Detect if a workload is in OpenSearch Benchmark format.

    Detection strategy (in order of priority):
    1. Check for explicit "collections" key → Solr workload
    2. Check for explicit "indices" key → OpenSearch workload
    3. Check operation types in challenges
    4. Check param-source values
    5. Default to False (treat as Solr if unclear)

    Args:
        workload: Workload object or dict

    Returns:
        True if OpenSearch format (needs conversion), False if Solr format
    """
    # Handle both Workload objects and dicts
    if hasattr(workload, "indices"):
        # Workload object - check for collections attribute
        has_collections = hasattr(workload, "collections") and len(getattr(workload, "collections", [])) > 0
        has_indices = len(workload.indices) > 0

        if has_collections:
            logger.debug("Detected Solr workload (has collections)")
            return False
        if has_indices:
            logger.debug("Detected OpenSearch workload (has indices)")
            return True

    # For dicts, check keys directly
    if isinstance(workload, dict):
        if "collections" in workload:
            logger.debug("Detected Solr workload (collections key)")
            return False
        if "indices" in workload:
            logger.debug("Detected OpenSearch workload (indices key)")
            return True

    # Fallback: Check operation types and param sources
    is_opensearch = _detect_from_operations(workload)

    if is_opensearch:
        logger.info("Detected OpenSearch workload format - conversion will be applied")
    else:
        logger.debug("Detected Solr workload format - no conversion needed")

    return is_opensearch


def _detect_from_operations(workload) -> bool:
    """
    Detect format by examining operations in challenges/test procedures.

    Returns:
        True if OpenSearch format, False if Solr format
    """
    # Get test procedures (challenges)
    test_procedures = []
    if hasattr(workload, "test_procedures"):
        test_procedures = workload.test_procedures
    elif isinstance(workload, dict) and "challenges" in workload:
        # Raw dict format
        test_procedures = workload.get("challenges", [])

    opensearch_score = 0
    solr_score = 0

    for test_proc in test_procedures:
        # Get schedule
        schedule = []
        if hasattr(test_proc, "schedule"):
            schedule = test_proc.schedule
        elif isinstance(test_proc, dict):
            schedule = test_proc.get("schedule", [])

        for task in schedule:
            # Get operation
            operation = None
            if hasattr(task, "operation"):
                operation = task.operation
            elif isinstance(task, dict):
                operation = task.get("operation", {})

            if not operation:
                continue

            # Get operation type
            op_type = None
            if hasattr(operation, "type"):
                op_type = operation.type
            elif isinstance(operation, dict):
                op_type = operation.get("operation-type") or operation.get("type")

            if op_type in OPENSEARCH_OPERATIONS:
                opensearch_score += 2
            if op_type in SOLR_OPERATIONS:
                solr_score += 2

            # Check param-source
            param_source = None
            if hasattr(operation, "param_source"):
                param_source = operation.param_source
            elif isinstance(operation, dict):
                param_source = operation.get("param-source")

            if param_source in OPENSEARCH_PARAM_SOURCES:
                opensearch_score += 3
            if param_source in SOLR_PARAM_SOURCES:
                solr_score += 3

    logger.debug(f"Detection scores - OpenSearch: {opensearch_score}, Solr: {solr_score}")

    # If unclear, default to Solr (no conversion)
    return opensearch_score > solr_score


def should_convert_workload(workload) -> bool:
    """
    Convenience function - alias for is_opensearch_workload.

    Args:
        workload: Workload object or dict

    Returns:
        True if workload needs conversion (is OpenSearch format)
    """
    return is_opensearch_workload(workload)


def is_opensearch_only_query(body) -> bool:
    """
    Return True when the query body contains OpenSearch-only query features that
    cannot be meaningfully translated to Solr — such as Painless/Groovy script
    scoring, percolate, pinned, rank_feature, or intervals queries.

    Queries identified this way should be SKIPPED during a Solr benchmark run
    rather than silently degraded to ``q=*:*``.

    Args:
        body: The query body dict (non-dicts always return False)

    Returns:
        True if the body contains OS-only constructs that Solr cannot execute.
    """
    if not isinstance(body, dict):
        return False
    query = body.get("query")
    if not isinstance(query, dict):
        return False
    return _contains_os_only_node(query)


def _contains_os_only_node(node) -> bool:
    """Recursively check whether a query node contains OpenSearch-only features."""
    if not isinstance(node, dict):
        return False
    # Script-based scoring (Painless, expression, Groovy, etc.)
    if "function_score" in node:
        for fn in node["function_score"].get("functions", []):
            if "script_score" in fn:
                return True
    if "script_score" in node:
        return True
    # Other OpenSearch/Elasticsearch-only query types
    for os_only_type in ("more_like_this", "percolate", "rank_feature", "pinned", "intervals"):
        if os_only_type in node:
            return True
    # Recurse into bool clauses
    if "bool" in node:
        for clause_list in node["bool"].values():
            if isinstance(clause_list, list):
                for clause in clause_list:
                    if _contains_os_only_node(clause):
                        return True
            elif isinstance(clause_list, dict):
                if _contains_os_only_node(clause_list):
                    return True
    return False


def is_opensearch_body(body) -> bool:
    """
    Detect whether a query body dict is in OpenSearch DSL format.

    Returns True when the body looks like an OpenSearch query, i.e. it contains
    a "query" key whose value is a dict (not a plain Solr query string), OR when
    it contains OpenSearch-specific aggregation keys ("aggs" / "aggregations").

    Args:
        body: The query body (any type; non-dicts always return False)

    Returns:
        True if the body is OpenSearch DSL format, False otherwise.
    """
    if not isinstance(body, dict):
        return False
    query_val = body.get("query")
    if isinstance(query_val, dict):
        return True
    if "aggs" in body or "aggregations" in body:
        return True
    return False


def has_opensearch_aggregations(body) -> bool:
    """
    Return True when the body contains OpenSearch-style aggregation keys
    ("aggs" or "aggregations") that are not natively understood by Solr.

    Args:
        body: The query body dict (non-dicts always return False)

    Returns:
        True if the body contains OpenSearch aggregations.
    """
    if not isinstance(body, dict):
        return False
    return "aggs" in body or "aggregations" in body


def is_opensearch_workload_path(workload_path: str) -> bool:
    """
    Detect whether a workload directory contains an OpenSearch Benchmark workload.

    Reads ``workload.json`` (or ``workload.jsonnet``) from the given directory as
    raw JSON and checks for the presence of the ``"indices"`` key, which is the
    definitive marker of an OSB workload. A ``"collections"`` key indicates a
    Solr-native workload.

    This function is the ONLY piece of conversion code that may be imported from
    the benchmark run path (``test_run_orchestrator.py``). It does not import any
    heavy conversion dependencies.

    Args:
        workload_path: Path to the workload directory.

    Returns:
        True if the workload is in OpenSearch Benchmark format (needs conversion).
        False for Solr-native format, missing file, or any parse/IO error.
    """
    for filename in ("workload.json", "workload.jsonnet"):
        candidate = os.path.join(workload_path, filename)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    data = json.load(fh)
                if "indices" in data:
                    logger.debug("Detected OSB workload at '%s' (contains 'indices' key)", workload_path)
                    return True
                if "collections" in data:
                    logger.debug("Detected Solr workload at '%s' (contains 'collections' key)", workload_path)
                return False
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("Could not parse workload file '%s': %s — treating as Solr format", candidate, exc)
                return False
    return False
