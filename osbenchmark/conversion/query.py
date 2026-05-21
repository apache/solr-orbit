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
OpenSearch Query DSL to Solr Query Syntax Translation

This module handles translation of OpenSearch Query DSL (JSON-based query language)
to Solr's Lucene query syntax.

IMPORTANT: This module should ONLY be used when converting OpenSearch workloads.
Native Solr workloads should not go through this translation layer.
"""

import logging
from datetime import datetime

from .field import normalize_field_name

logger = logging.getLogger(__name__)


def translate_opensearch_query(body: dict) -> dict:
    """
    Translate an OpenSearch query DSL dict to Solr query parameters.

    Supported patterns:
      - ``match_all``             → ``*:*``
      - ``term``                  → ``field:value``
      - ``terms``                 → ``field:(v1 v2 v3)`` or ``{!terms f=field}v1,v2,...``
      - ``match`` / ``match_phrase`` → ``field:value``
      - ``range``                 → ``field:[lo TO hi]``
      - ``exists``                → ``field:[* TO *]``
      - ``bool`` (must/should/must_not) → recursive translation in ``q``
      - ``bool.filter``           → Solr ``fq`` parameters (supports large term lists)
      - ``ids``                   → ``id:(id1 id2 ...)``

    Falls back to ``*:*`` for unrecognised patterns (logs warning).

    Args:
        body: OpenSearch query body dict with "query" key

    Returns:
        Dict with keys:
          - ``"q"``: Solr query string for the ``q`` parameter
          - ``"fq"``: list of Solr filter query strings for the ``fq`` parameter

    Examples:
        >>> translate_opensearch_query({"query": {"match_all": {}}})
        {'q': '*:*', 'fq': []}
        >>> translate_opensearch_query({"query": {"term": {"country": "US"}}})
        {'q': 'country:US', 'fq': []}
    """
    if not body or not isinstance(body, dict):
        return {"q": "*:*", "fq": []}
    query = body.get("query", {})
    fq_list = []

    # Top-level terms queries can be very large (thousands of values).
    # Route them directly to fq using {!terms f=...} for efficiency.
    if "terms" in query and len(query) == 1:
        fq_str = _translate_node_for_fq(query)
        if fq_str:
            fq_list.append(fq_str)
            return {"q": "*:*", "fq": fq_list}

    q = _translate_query_node(query, fq_list=fq_list)
    return {"q": q, "fq": fq_list}


def extract_sort_parameter(body: dict) -> str:
    """
    Extract a Solr sort string from an OpenSearch sort clause.

    Args:
        body: OpenSearch query body dict with optional "sort" key

    Returns:
        Solr sort parameter string (e.g., "name_raw desc, _score asc")
        or None if no sort clause present

    Examples:
        >>> extract_sort_parameter({"sort": [{"name.raw": "desc"}]})
        'name_raw desc'
    """
    if not isinstance(body, dict) or "sort" not in body:
        return None
    sort_clauses = body["sort"]
    if isinstance(sort_clauses, dict):
        sort_clauses = [sort_clauses]
    solr_sorts = []
    for clause in sort_clauses:
        if isinstance(clause, str):
            # Normalize field name before adding to sort
            field = normalize_field_name(clause.split()[0] if " " in clause else clause)
            suffix = " " + clause.split()[1] if " " in clause else ""
            solr_sorts.append(field + suffix)
        elif isinstance(clause, dict):
            for field, order_info in clause.items():
                if field == "_score":
                    continue
                # Normalize field name
                field = normalize_field_name(field)
                if isinstance(order_info, dict):
                    order = order_info.get("order", "asc")
                elif isinstance(order_info, str):
                    order = order_info
                else:
                    order = "asc"
                solr_sorts.append(f"{field} {order}")
    return ", ".join(solr_sorts) if solr_sorts else None


# ---------------------------------------------------------------------------
# Internal helper functions
# ---------------------------------------------------------------------------

def _translate_query_node(node: dict, fq_list: list = None) -> str:
    """Recursively translate a single OpenSearch query node to Solr syntax.

    Args:
        node: OpenSearch query node dict
        fq_list: Optional list to collect Solr fq filter strings. When provided,
                 bool.filter clauses are appended here instead of inlined in q.
    """
    if not node or not isinstance(node, dict):
        return "*:*"

    if "match_all" in node:
        return "*:*"

    if "match_none" in node:
        return "-*:*"

    if "term" in node:
        for field, value in node["term"].items():
            v = value.get("value", value) if isinstance(value, dict) else value
            field = normalize_field_name(field)
            return f"{field}:{_escape_solr_value(v)}"

    if "terms" in node:
        for field, values in node["terms"].items():
            if field.startswith("_"):
                continue
            field = normalize_field_name(field)
            return _translate_terms_clause(field, values)

    if "match" in node or "match_phrase" in node:
        sub = node.get("match") or node.get("match_phrase")
        if isinstance(sub, dict):
            for field, value in sub.items():
                # Skip empty field names or metadata fields
                if not field or field.startswith("_"):
                    continue
                v = value.get("query", value) if isinstance(value, dict) else value
                field = normalize_field_name(field)
                # For phrase queries, wrap in quotes if not already
                if "match_phrase" in node and not (isinstance(v, str) and v.startswith('"')):
                    return f'{field}:"{_escape_solr_phrase(v)}"'
                return f"{field}:{_escape_solr_value(v)}"
        # If sub is not a dict or has no valid fields, fall back
        logger.warning(
            "match/match_phrase query has invalid structure: %s. Using *:*",
            sub
        )
        return "*:*"

    if "range" in node:
        for field, bounds in node["range"].items():
            field = normalize_field_name(field)
            lo = bounds.get("gte", bounds.get("gt", "*"))
            hi = bounds.get("lte", bounds.get("lt", "*"))
            # Convert dates if format is specified (common for date fields)
            os_format = bounds.get("format")
            lo = _convert_date_to_solr_format(lo, os_format)
            hi = _convert_date_to_solr_format(hi, os_format)
            return f"{field}:[{lo} TO {hi}]"

    if "exists" in node:
        field = node["exists"].get("field", "*")
        field = normalize_field_name(field)
        return f"{field}:[* TO *]"

    if "ids" in node:
        values = node["ids"].get("values", [])
        if values:
            escaped = " ".join(_escape_solr_value(v) for v in values)
            return f"id:({escaped})"
        return "*:*"

    if "bool" in node:
        bool_q = node["bool"]
        parts = []

        def _add_to_q(clauses, prefix):
            if not clauses:
                return
            if isinstance(clauses, dict):
                clauses = [clauses]
            for clause in clauses:
                sub = _translate_query_node(clause, fq_list=fq_list)
                if sub and sub != "*:*":
                    parts.append(f"{prefix}({sub})")

        def _add_to_fq(clauses):
            """Translate bool.filter clauses to Solr fq parameters."""
            if not clauses:
                return
            if isinstance(clauses, dict):
                clauses = [clauses]
            for clause in clauses:
                fq_str = _translate_node_for_fq(clause)
                if fq_str:
                    fq_list.append(fq_str)

        _add_to_q(bool_q.get("must"), "+")
        _add_to_q(bool_q.get("must_not"), "-")

        # bool.filter → Solr fq when fq_list is available; otherwise inline in q
        if fq_list is not None:
            _add_to_fq(bool_q.get("filter"))
        else:
            _add_to_q(bool_q.get("filter"), "+")

        shoulds = bool_q.get("should", [])
        if isinstance(shoulds, dict):
            shoulds = [shoulds]
        should_parts = [_translate_query_node(s, fq_list=fq_list) for s in shoulds]
        should_parts = [s for s in should_parts if s and s != "*:*"]
        if should_parts:
            parts.append("(" + " ".join(should_parts) + ")")

        return " ".join(parts) if parts else "*:*"

    # Unknown / untranslatable query node
    logger.warning(
        "Cannot translate OpenSearch query type '%s' to Solr syntax. "
        "Falling back to q=*:* (results may not match workload intent). "
        "Consider rewriting this operation as a native Solr workload task.",
        list(node.keys()),
    )
    return "*:*"


def _translate_terms_clause(field: str, values: list) -> str:
    """
    Translate a terms list to the most efficient Solr syntax.

    - Small lists (≤100 terms): ``field:(v1 v2 ...)``  — standard Lucene OR clause
    - Large lists (>100 terms): ``field:(v1 v2 ...)``  for q context, still works
      but when used as an fq, callers should prefer ``{!terms f=field}v1,v2,...``
    """
    escaped = " ".join(
        f'"{_escape_solr_phrase(v)}"' if " " in str(v) else _escape_solr_value(v)
        for v in values
    )
    return f"{field}:({escaped})"


def _translate_node_for_fq(node: dict) -> str:
    """
    Translate a single query node to a Solr fq string.

    For terms clauses, uses the efficient ``{!terms f=field}v1,v2,...`` syntax
    which Solr handles as a cached bitset — ideal for large term lists in filters.

    For other clause types, delegates to _translate_query_node() without fq_list
    (filter sub-clauses are flattened into a single fq string).
    """
    if not node or not isinstance(node, dict):
        return None

    # terms → {!terms f=field}v1,v2,...  (Solr's efficient bitset filter)
    if "terms" in node:
        for field, values in node["terms"].items():
            if field.startswith("_"):
                continue
            field = normalize_field_name(field)
            if not values:
                return None
            # Join values as comma-separated (Solr {!terms} syntax)
            joined = ",".join(str(v) for v in values)
            return f"{{!terms f={field}}}{joined}"

    # range, term, exists, match etc. — translate normally
    return _translate_query_node(node, fq_list=None)


def _escape_solr_value(value) -> str:
    """Escape special Lucene/Solr query characters in a field value."""
    special = r'+-&&||!(){}[]^"~*?:\/'
    result = []
    for char in str(value):
        if char in special:
            result.append('\\' + char)
        else:
            result.append(char)
    return ''.join(result)


def _escape_solr_phrase(value) -> str:
    """
    Escape a phrase value for Solr phrase queries.

    For phrases, we only need to escape quotes (and backslashes).
    Other special characters are OK within quotes.
    """
    return str(value).replace('\\', '\\\\').replace('"', '\\"')


def translate_to_solr_json_dsl(body: dict) -> dict:
    """
    Translate an OpenSearch query body to Solr JSON Query DSL format.

    Output is a valid Solr JSON Query DSL body for POSTing to the
    ``/solr/{collection}/query`` endpoint (Mode 2 of SolrSearch runner).
    The ``"query"`` value is always a string, making it Mode 2 compatible.

    Args:
        body: OpenSearch query body dict (may contain "query", "aggs", "size", "sort")

    Returns:
        Solr JSON Query DSL dict with keys:
          - ``query``: Lucene query string
          - ``filter``: list of filter query strings (omitted if empty)
          - ``limit``: number of results (omitted if not specified)
          - ``sort``: sort string (omitted if not specified)
          - ``facet``: Solr JSON Facet API dict (omitted if no aggregations)
    """
    if not body or not isinstance(body, dict):
        return {"query": "*:*"}

    fq_list = []
    query_val = body.get("query")
    if isinstance(query_val, dict):
        translated = translate_opensearch_query(body)
        q = translated["q"]
        fq_list = translated["fq"]
    else:
        q = "*:*"

    result = {"query": q}

    if fq_list:
        result["filter"] = fq_list

    if "size" in body:
        result["limit"] = body["size"]

    sort_str = extract_sort_parameter(body)
    if sort_str:
        result["sort"] = sort_str

    aggs = body.get("aggs") or body.get("aggregations")
    if aggs and isinstance(aggs, dict):
        facets = _convert_aggregations_to_facets(aggs)
        if facets:
            result["facet"] = facets

    return result


def _convert_aggregations_to_facets(aggs: dict) -> dict:
    """
    Convert OpenSearch aggregations to Solr JSON Facet API format.

    Supported aggregation types:
      - ``terms``          → ``{"type":"terms","field":...,"limit":n}``
      - ``date_histogram`` → ``{"type":"range","field":...,"gap":"..."}``
      - ``histogram``      → ``{"type":"range","field":...,"gap":n}``
      - ``avg``            → ``"avg(field)"`` function expression
      - ``sum``            → ``"sum(field)"`` function expression
      - ``min``            → ``"min(field)"`` function expression
      - ``max``            → ``"max(field)"`` function expression
      - ``value_count``    → ``"countvals(field)"`` function expression

    Nested aggregations within bucket aggs are recursively converted.
    Unsupported aggregation types are skipped with a WARN log.

    Args:
        aggs: OpenSearch aggregations dict (the value of "aggs" or "aggregations")

    Returns:
        Solr JSON Facet API dict suitable for the ``"facet"`` key in JSON Query DSL
    """
    if not aggs or not isinstance(aggs, dict):
        return {}

    result = {}
    for agg_name, agg_def in aggs.items():
        if not isinstance(agg_def, dict):
            continue
        entry = _convert_single_agg(agg_name, agg_def)
        if entry is not None:
            result[agg_name] = entry

    return result


def _convert_single_agg(agg_name: str, agg_def: dict):
    """Convert a single named OpenSearch aggregation to a Solr facet entry."""
    # --- bucket aggregations ---
    if "terms" in agg_def:
        terms_conf = agg_def["terms"]
        field = normalize_field_name(terms_conf.get("field", ""))
        if not field:
            logger.warning("terms agg '%s' has no field — skipping", agg_name)
            return None
        facet_def = {
            "type": "terms",
            "field": field,
            "limit": terms_conf.get("size", 10),
        }
        nested = agg_def.get("aggs") or agg_def.get("aggregations")
        if nested:
            sub = _convert_aggregations_to_facets(nested)
            if sub:
                facet_def["facet"] = sub
        return facet_def

    if "date_histogram" in agg_def:
        dh_conf = agg_def["date_histogram"]
        field = normalize_field_name(dh_conf.get("field", ""))
        if not field:
            logger.warning("date_histogram agg '%s' has no field — skipping", agg_name)
            return None
        interval = (
            dh_conf.get("calendar_interval")
            or dh_conf.get("fixed_interval")
            or dh_conf.get("interval", "month")
        )
        gap = _calendar_interval_to_solr_gap(interval)
        facet_def = {
            "type": "range",
            "field": field,
            "gap": gap,
            "mincount": 1,
            "start": "NOW/YEAR-10YEAR",
            "end": "NOW/YEAR+1YEAR",
        }
        nested = agg_def.get("aggs") or agg_def.get("aggregations")
        if nested:
            sub = _convert_aggregations_to_facets(nested)
            if sub:
                facet_def["facet"] = sub
        return facet_def

    if "histogram" in agg_def:
        h_conf = agg_def["histogram"]
        field = normalize_field_name(h_conf.get("field", ""))
        if not field:
            logger.warning("histogram agg '%s' has no field — skipping", agg_name)
            return None
        return {
            "type": "range",
            "field": field,
            "gap": h_conf.get("interval", 1),
            "mincount": 1,
            "start": 0,
            "end": 1000000,
        }

    # --- metric aggregations (function expressions) ---
    for metric_type in ("avg", "sum", "min", "max"):
        if metric_type in agg_def:
            field = normalize_field_name(agg_def[metric_type].get("field", ""))
            if not field:
                logger.warning("%s agg '%s' has no field — skipping", metric_type, agg_name)
                return None
            return f"{metric_type}({field})"

    if "value_count" in agg_def:
        field = normalize_field_name(agg_def["value_count"].get("field", ""))
        if not field:
            logger.warning("value_count agg '%s' has no field — skipping", agg_name)
            return None
        return f"countvals({field})"

    agg_type = next(iter(agg_def), "unknown")
    logger.warning(
        "Unsupported aggregation type '%s' (name='%s') — skipping in Solr conversion.",
        agg_type, agg_name,
    )
    return None


def _calendar_interval_to_solr_gap(interval: str) -> str:
    """Convert an OpenSearch calendar_interval or fixed_interval to a Solr range gap string."""
    mapping = {
        "minute": "+1MINUTE",
        "1m": "+1MINUTE",
        "hour": "+1HOUR",
        "1h": "+1HOUR",
        "day": "+1DAY",
        "1d": "+1DAY",
        "week": "+7DAYS",
        "1w": "+7DAYS",
        "month": "+1MONTH",
        "1m_month": "+1MONTH",  # avoid conflict with 1m (minute)
        "quarter": "+3MONTHS",
        "1q": "+3MONTHS",
        "year": "+1YEAR",
        "1y": "+1YEAR",
    }
    return mapping.get(str(interval).lower(), "+1MONTH")


def _convert_date_to_solr_format(date_str, os_format=None) -> str:
    """
    Convert an OpenSearch date string to Solr ISO 8601 format.

    Args:
        date_str: Date string in various OpenSearch formats
        os_format: Optional OpenSearch date format pattern (e.g., "dd/MM/yyyy")

    Returns:
        ISO 8601 date string for Solr (e.g., "2015-01-01T00:00:00Z")

    If the date is already in ISO format or conversion fails, returns the
    original string unchanged.
    """
    if not isinstance(date_str, str) or date_str in ("*", "now"):
        return date_str

    # Map OpenSearch date format patterns to Python strptime format
    OS_TO_PYTHON_FORMAT = {
        "dd/MM/yyyy": "%d/%m/%Y",
        "MM/dd/yyyy": "%m/%d/%Y",
        "yyyy-MM-dd": "%Y-%m-%d",
        "yyyy/MM/dd": "%Y/%m/%d",
        "dd-MM-yyyy": "%d-%m-%Y",
        "MM-dd-yyyy": "%m-%d-%Y",
        # Add more as needed
    }

    # If format is provided, use it to parse the date
    if os_format:
        python_fmt = OS_TO_PYTHON_FORMAT.get(os_format)
        if python_fmt:
            try:
                dt = datetime.strptime(date_str, python_fmt)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                logger.warning(f"Failed to parse date '{date_str}' with format '{os_format}'")
                return date_str
        else:
            logger.warning(f"Unknown OpenSearch date format: '{os_format}'")

    # Try common patterns if no format specified
    for python_fmt in OS_TO_PYTHON_FORMAT.values():
        try:
            dt = datetime.strptime(date_str, python_fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue

    # If it's already in ISO-like format, return as-is
    # (handles cases like "2015-01-01T00:00:00Z" or partial ISO)
    if "T" in date_str or len(date_str) == 10:  # YYYY-MM-DD
        return date_str

    logger.warning(f"Could not parse date '{date_str}', using as-is")
    return date_str
