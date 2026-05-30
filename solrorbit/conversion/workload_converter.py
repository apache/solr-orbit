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
OpenSearch Workload to Solr Workload Converter

Converts an OpenSearch Benchmark workload directory to a Solr-native workload.

Usage:
    from solrorbit.conversion.workload_converter import convert_opensearch_workload
    result = convert_opensearch_workload("/path/to/osb_workload", "/path/to/solr_workload")

The converter:
  - Renames ``indices`` → ``collections`` and generates schema.xml files from mappings
  - Renames operation types using the same map as migrate_workload.py
  - Translates OpenSearch search bodies to Solr JSON Query DSL
  - Preserves ``corpora`` as-is (dataset files are compatible with both formats)
  - Writes a ``CONVERTED.md`` marker file to prevent double-conversion
  - Returns a summary dict with output_dir, issues, and skipped operations
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime

from .detector import is_opensearch_workload
from .query import translate_to_solr_json_dsl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Jinja2 template-preserving helpers
# ---------------------------------------------------------------------------

# Matches (in order of priority):
#  1. Already-quoted Jinja2 expression: "{{expr}}"
#  2. Entire if/else/endif conditional block (may span many lines)
#  3. Any remaining Jinja2 block tag or expression
_JINJA_RE = re.compile(
    r'"(\{\{[^}]*?\}\})"'  # group 1: already-quoted {{expr}}
    r"|\{%-?\s*if\b.*?\{%-?\s*endif\s*-?%\}"  # full if/else/endif block
    r"|\{%.*?%\}"  # any other block tag
    r"|\{\{.*?\}\}",  # bare {{expr}}
    re.DOTALL,
)

# Matches benchmark.collect(parts="<path>") — captures prefix, path, suffix as groups
_COLLECT_RE = re.compile(r'(benchmark\.collect\s*\(\s*parts\s*=\s*")([^"]+)(")')


def _jinja_substitute(text: str):
    """
    Replace Jinja2 tokens in *text* with JSON-safe string placeholders.

    Returns ``(modified_text, token_list)`` where each element of
    ``token_list`` is ``(original_source, was_quoted)``:.

    - ``"{{expr}}"`` → ``"__J_i__"``  (store inner expr, ``was_quoted=True``)
    - bare ``{{expr}}`` or ``{%…%}`` → ``"__J_i__"`` (store full match, ``was_quoted=False``)
    - full ``{% if %}…{% endif %}`` block → ``"__J_i__"`` (``was_quoted=False``)
    """
    tokens = []

    def replacer(m):
        idx = len(tokens)
        if m.group(1) is not None:
            # Already-quoted: store inner expression only; restore will re-add quotes
            tokens.append((m.group(1), True))
        else:
            tokens.append((m.group(0), False))
        return f'"__J_{idx}__"'

    return _JINJA_RE.sub(replacer, text), tokens


def _jinja_restore(json_text: str, tokens: list) -> str:
    """
    Restore Jinja2 tokens in serialised JSON text from their placeholders.

    - For ``was_quoted=True`` tokens the placeholder ``"__J_i__"`` is replaced
      with ``"originalExpr"`` (surrounding quotes preserved).
    - For ``was_quoted=False`` tokens the placeholder string (with its
      surrounding quotes) is replaced verbatim with the original Jinja2 source.
    """
    for idx, (original, was_quoted) in enumerate(tokens):
        placeholder_json = f'"__J_{idx}__"'
        if was_quoted:
            # Was "{{expr}}" — restore with surrounding quotes
            json_text = json_text.replace(placeholder_json, f'"{original}"')
        else:
            # Was bare {{expr}} or {%…%} — replace the entire quoted placeholder
            json_text = json_text.replace(placeholder_json, original)
    return json_text


def _parse_jinja_fragment(text: str, wrap_array: bool = False):
    """
    Parse a text that may contain Jinja2 tokens as JSON.

    If *wrap_array* is True, the text is wrapped in ``[…]`` before parsing
    (use for ``benchmark.collect()`` fragment files that are not valid JSON
    by themselves).

    Returns ``(parsed_value, tokens)`` or raises ``ValueError`` if the text
    cannot be parsed even after substitution.
    """
    modified, tokens = _jinja_substitute(text)
    to_parse = f"[{modified}]" if wrap_array else modified
    try:
        parsed = json.loads(to_parse)
        return parsed, tokens
    except json.JSONDecodeError as exc:
        raise ValueError(f"Cannot parse as JSON after Jinja2 substitution: {exc}") from exc


def _serialise_jinja_fragment(data, tokens: list, wrap_array: bool = False) -> str:
    """
    Serialise *data* back to JSON and restore the Jinja2 tokens.

    If *wrap_array* was True, the list wrapper is stripped.
    """
    text = json.dumps(data, indent=2)
    if wrap_array:
        # Strip the surrounding [ … ] added by wrap_array
        text = text.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1].strip()
    return _jinja_restore(text, tokens)


def _load_workload_json(workload_path: str) -> dict:
    """
    Load workload.json, rendering Jinja2 templates if necessary.

    OSB workload files often start with ``{% import "benchmark.helpers" ... %}``
    which is invalid JSON.  We try plain JSON first; if that fails with a
    JSONDecodeError we fall back to rendering the template (with empty vars).
    """
    with open(workload_path, encoding="utf-8") as f:
        raw = f.read()

    # Fast path: pure JSON (no template directives)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Template path: render Jinja2 then parse JSON
    try:
        from solrorbit.workload.loader import render_template_from_file

        rendered = render_template_from_file(workload_path, template_vars={})
        return json.loads(rendered)
    except Exception as exc:
        raise ValueError(f"Cannot parse workload file '{workload_path}' as JSON or Jinja2 template: {exc}") from exc


# Sentinel filename written to the output directory after successful conversion
CONVERTED_MARKER = "CONVERTED.md"

# Operation type mapping (same as migrate_workload.py _OP_MAP)
_OP_MAP = {
    "bulk": "bulk-index",
    "index": "bulk-index",
    "search": "search",
    "force-merge": "optimize",
    "create-index": "create-collection",
    "delete-index": "delete-collection",
    "raw-request": "raw-request",
    "sleep": "sleep",
}

# Operations that have no meaningful Solr equivalent (skipped with a note)
_UNSUPPORTED_OPS = {
    "cluster-health",
    "wait-for-recovery",
    "wait-for-snapshot-create",
    "restore-snapshot",
    "create-snapshot",
    "delete-snapshot-repository",
    "create-snapshot-repository",
    "put-settings",
    "create-transform",
    "start-transform",
    "delete-transform",
    "create-data-stream",
    "delete-data-stream",
    "create-index-template",
    "delete-index-template",
    "shrink-index",
    "put-pipeline",
    "delete-pipeline",
}


def detect_workload_format_from_file(workload_dir: str) -> bool:
    """
    Read ``workload.json`` from ``workload_dir`` and detect if it is OpenSearch format.

    Args:
        workload_dir: Path to the workload directory containing ``workload.json``

    Returns:
        True if the workload is OpenSearch format (needs conversion), False if Solr format.

    Raises:
        FileNotFoundError: If workload.json is not found in workload_dir
        ValueError: If workload.json is not valid JSON
    """
    workload_path = os.path.join(workload_dir, "workload.json")
    if not os.path.isfile(workload_path):
        # Check for .json extension variants
        for name in ("workload.json", "workload.yaml"):
            candidate = os.path.join(workload_dir, name)
            if os.path.isfile(candidate):
                workload_path = candidate
                break
        else:
            raise FileNotFoundError(f"No workload.json found in: {workload_dir}")

    workload_dict = _load_workload_json(workload_path)
    return is_opensearch_workload(workload_dict)


def is_already_converted(output_dir: str) -> bool:
    """
    Check if the output directory already contains a converted workload.

    Args:
        output_dir: Path to the candidate output directory

    Returns:
        True if ``CONVERTED.md`` exists in ``output_dir`` (already converted)
    """
    return os.path.isfile(os.path.join(output_dir, CONVERTED_MARKER))


def convert_opensearch_workload(source_dir: str, output_dir: str) -> dict:
    """
    Convert an OpenSearch Benchmark workload to a Solr-native workload.

    Steps performed:
      1. Read ``workload.json`` from ``source_dir``
      2. Convert ``indices`` → ``collections`` and generate configsets from mappings
      3. Rename operation types, translate search bodies to Solr JSON Query DSL
      4. Preserve ``corpora`` unchanged (dataset files are format-agnostic)
      5. Write converted ``workload.json`` to ``output_dir``
      6. Write ``CONVERTED.md`` marker with conversion summary
      7. Copy any non-JSON workload files (Python param sources, etc.)

    Args:
        source_dir: Path to the source OpenSearch workload directory
        output_dir: Path where the Solr workload will be written (created if absent)

    Returns:
        Dict with:
          - ``output_dir``: absolute path to the converted workload
          - ``issues``: list of warning strings about approximations or limitations
          - ``skipped``: list of operation names that were removed (unsupported ops)
    """
    issues = []
    skipped = []

    workload_path = os.path.join(source_dir, "workload.json")
    if not os.path.isfile(workload_path):
        raise FileNotFoundError(f"workload.json not found in: {source_dir}")

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # --- Analyse the workload (renders Jinja2 to get the full structure) ---
    rendered_workload = _load_workload_json(workload_path)

    # --- Generate configsets from index mappings ---
    _generate_configsets_from_indices(rendered_workload, source_dir, output_dir, issues)

    # --- Write converted workload.json (template-preserving) ---
    _write_converted_workload_json(workload_path, rendered_workload, output_dir, issues, skipped)

    # --- Process operations / test_procedures fragment files referenced via benchmark.collect() ---
    _process_collected_files(source_dir, output_dir, issues, skipped)

    # --- Convert challenges / test procedures (inline, if present) ---
    for challenge in rendered_workload.get("challenges", []):
        for task in challenge.get("schedule", []):
            _convert_task(task, rendered_workload, source_dir, output_dir, issues, skipped)

    # --- Copy auxiliary files (Python param sources, templates, etc.) ---
    # Skip index body files (e.g. index.json) — replaced by generated configsets
    index_body_files = {index.get("body") for index in rendered_workload.get("indices", []) if index.get("body")}
    _copy_auxiliary_files(source_dir, output_dir, skip_files=index_body_files)

    # --- Follow external benchmark.collect() refs and make the workload self-contained ---
    _process_external_collected_files(source_dir, output_dir, issues, skipped)

    # --- Write CONVERTED.md marker ---
    _write_converted_marker(output_dir, source_dir, skipped, issues)

    logger.info(
        "Workload conversion complete: %s → %s (%d ops, %d skipped, %d issues)",
        source_dir,
        output_dir,
        0,
        len(skipped),
        len(issues),
    )

    return {
        "output_dir": os.path.abspath(output_dir),
        "issues": issues,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_configsets_from_indices(rendered_workload: dict, source_dir: str, output_dir: str, issues: list):
    """Generate Solr configsets from the rendered workload's indices section."""
    for index in rendered_workload.get("indices", []):
        collection_name = index.get("name", "unknown")
        index_body_path = index.get("body")
        if not index_body_path:
            continue
        body_abs = os.path.join(source_dir, index_body_path)
        if not os.path.isfile(body_abs):
            continue
        try:
            index_body = _load_workload_json(body_abs)
            mappings = index_body.get("mappings", {})
            properties = mappings.get("properties", {})
            if properties:
                _generate_configset(collection_name, properties, output_dir)
        except Exception as exc:
            issues.append(f"Could not generate schema for collection '{collection_name}': {exc}")


def _write_converted_workload_json(workload_path: str, rendered_workload: dict, output_dir: str, issues: list, skipped: list):
    """
    Write the converted workload.json to *output_dir*, preserving Jinja2 template syntax.

    Strategy: read the raw file text and apply targeted text replacements rather than
    round-tripping through JSON serialisation (which would strip all Jinja2 directives).
    """
    with open(workload_path, encoding="utf-8") as f:
        raw_text = f.read()

    # 1. Rename "indices": → "collections":  (top-level key rename)
    #    Use word-boundary to avoid false matches like "field_indices"
    converted_text = re.sub(r'(?m)^(\s*)"indices"\s*:', r'\1"collections":', raw_text)

    # 2. Replace "body": "<index_file>" → "configset-path": "configsets/<name>" for each index.
    #    Index specs use "body" as a string file path; operation "body" fields are dicts/objects,
    #    so a string-value match is safe here.
    for index in rendered_workload.get("indices", []):
        name = index.get("name")
        body_file = index.get("body")
        if name and body_file:
            configset_path = f"configsets/{name}"
            converted_text = re.sub(
                rf'"body"\s*:\s*"{re.escape(body_file)}"',
                f'"configset-path": "{configset_path}"',
                converted_text,
            )

    # 3. If the workload inlines operations in "challenges" (not via benchmark.collect()),
    #    perform in-text operation-type renames and inline body translations.
    # For workloads using benchmark.collect(), operations are in separate files and
    # will be processed by _process_collected_files().
    uses_collect = "benchmark.collect" in raw_text
    if not uses_collect:
        converted_text = _apply_inline_conversions(converted_text, rendered_workload, issues, skipped)

    out_path = os.path.join(output_dir, "workload.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(converted_text)


def _apply_inline_conversions(text: str, rendered_workload: dict, issues: list, skipped: list) -> str:
    """
    Apply operation-type renames and search body translations to inline workload text.

    Used for workloads that embed operations directly in workload.json (no benchmark.collect()).
    """
    try:
        parsed, tokens = _parse_jinja_fragment(text)
        # parsed is the full workload dict with placeholder values

        # Rename indices → collections
        if "indices" in parsed:
            parsed["collections"] = parsed.pop("indices")

        # Convert operations (filter out those skipped by _convert_operation)
        parsed["operations"] = [op for op in parsed.get("operations", []) if not isinstance(op, dict) or _convert_operation(op, issues, skipped, "", "")]

        # Convert challenge schedules
        for challenge in parsed.get("challenges", []):
            for task in challenge.get("schedule", []):
                _convert_task(task, parsed, "", "", issues, skipped)

        return _serialise_jinja_fragment(parsed, tokens)
    except Exception as exc:
        issues.append(f"Inline conversion failed, falling back to text-only: {exc}")
        return text


def _process_collected_files(source_dir: str, output_dir: str, issues: list, skipped: list):
    """
    Process JSON fragment files referenced via benchmark.collect() in workload.json.

    Scans ``operations/`` and ``test_procedures/`` sub-directories, parses each JSON
    fragment using Jinja2-placeholder substitution, applies operation conversions, and
    writes the result to the corresponding location in *output_dir*.
    """
    for subdir in ("operations", "test_procedures"):
        src_subdir = os.path.join(source_dir, subdir)
        if not os.path.isdir(src_subdir):
            continue
        dst_subdir = os.path.join(output_dir, subdir)
        os.makedirs(dst_subdir, exist_ok=True)

        for filename in os.listdir(src_subdir):
            if not filename.endswith(".json"):
                continue
            src_path = os.path.join(src_subdir, filename)
            dst_path = os.path.join(dst_subdir, filename)

            with open(src_path, encoding="utf-8") as f:
                raw = f.read()

            try:
                ops_list, tokens = _parse_jinja_fragment(raw, wrap_array=True)
            except ValueError as exc:
                issues.append(f"{subdir}/{filename}: cannot parse as JSON fragment ({exc}); copied verbatim")
                shutil.copy2(src_path, dst_path)
                continue

            # Convert each operation in the fragment; filter out skipped ones
            if subdir == "operations":
                ops_list = [op for op in ops_list if not isinstance(op, dict) or _convert_operation(op, issues, skipped, source_dir, output_dir)]

            converted_text = _serialise_jinja_fragment(ops_list, tokens, wrap_array=True)

            with open(dst_path, "w", encoding="utf-8") as f:
                f.write(converted_text)


def _generate_configset(collection_name: str, properties: dict, output_dir: str) -> str:
    """
    Generate a Solr configset directory from OpenSearch field mappings.

    Returns:
        Absolute path to the generated configset directory
        (``<output_dir>/configsets/<collection_name>/``)
    """
    from .schema import translate_opensearch_mapping, generate_schema_xml

    configset_dir = os.path.join(output_dir, "configsets", collection_name)
    os.makedirs(configset_dir, exist_ok=True)

    field_defs, copy_fields = translate_opensearch_mapping(properties)
    schema_xml = generate_schema_xml(field_defs, copy_fields=copy_fields, unique_key="id")

    # Write schema.xml
    with open(os.path.join(configset_dir, "schema.xml"), "w", encoding="utf-8") as f:
        f.write(schema_xml)

    # Write minimal solrconfig.xml
    solrconfig_xml = _minimal_solrconfig()
    with open(os.path.join(configset_dir, "solrconfig.xml"), "w", encoding="utf-8") as f:
        f.write(solrconfig_xml)

    # Write required text analysis resource files
    for aux_file, content in [
        ("stopwords.txt", "# Auto-generated empty stopwords file\n"),
        ("synonyms.txt", "# Auto-generated empty synonyms file\n"),
    ]:
        with open(os.path.join(configset_dir, aux_file), "w", encoding="utf-8") as f:
            f.write(content)

    logger.info("Generated configset for collection '%s' at: %s", collection_name, configset_dir)
    return configset_dir


def _convert_task(task, workload, source_dir, output_dir, issues, skipped):
    """
    Convert a single schedule task in-place.

    Renames operation types, translates search bodies, and removes unsupported ops.
    """
    if not isinstance(task, dict):
        return

    op = task.get("operation")
    if isinstance(op, str):
        # Operation reference by name — look it up in workload["operations"]
        op_name = op
        op_def = _find_operation(workload, op_name)
        if op_def:
            _convert_operation(op_def, issues, skipped, source_dir, output_dir)
        return

    if isinstance(op, dict):
        _convert_operation(op, issues, skipped, source_dir, output_dir)
        return


def _find_operation(workload, op_name):
    """Find an operation definition by name in workload["operations"]."""
    for op in workload.get("operations", []):
        if isinstance(op, dict) and op.get("name") == op_name:
            return op
    return None


def _has_auto_date_histogram(aggs: dict) -> bool:
    """Return True if any aggregation (at any nesting level) uses auto_date_histogram."""
    for agg_def in aggs.values():
        if not isinstance(agg_def, dict):
            continue
        if "auto_date_histogram" in agg_def:
            return True
        nested = agg_def.get("aggs") or agg_def.get("aggregations") or {}
        if _has_auto_date_histogram(nested):
            return True
    return False


def _convert_operation(op, issues, skipped, source_dir, output_dir):
    """Convert an operation definition dict in-place.

    Returns True if the operation should be kept, False if it should be removed.
    """
    op_type = op.get("operation-type") or op.get("type", "")
    op_name = op.get("name", op_type)

    if op_type in _UNSUPPORTED_OPS:
        logger.warning("Skipping unsupported operation '%s' (type: %s)", op_name, op_type)
        skipped.append(op_name)
        return False

    # auto_date_histogram has no Solr equivalent — skip the whole operation.
    if op_type in ("search", "paginated-search", "scroll-search"):
        body = op.get("body")
        if isinstance(body, dict):
            aggs = body.get("aggs") or body.get("aggregations") or {}
            if _has_auto_date_histogram(aggs):
                logger.warning(
                    "Skipping operation '%s': auto_date_histogram is not supported in Solr (Solr requires explicit gap/start/end for range facets).",
                    op_name,
                )
                skipped.append(f"{op_name} (auto_date_histogram not supported in Solr)")
                return False

    new_type = _OP_MAP.get(op_type)
    if new_type and new_type != op_type:
        op["operation-type"] = new_type
        if "type" in op and op.get("type") == op_type:
            op["type"] = new_type

    # Rename index → collection
    if "index" in op:
        op["collection"] = op.pop("index")
    if "indices" in op:
        op["collection"] = op.pop("indices")

    # For create-index → create-collection: inject absolute configset-path when available
    if op_type == "create-index" and output_dir:
        collection = op.get("collection", op.get("name", ""))
        if collection:
            configset_dir = os.path.join(os.path.abspath(output_dir), "configsets", collection)
            if os.path.isdir(configset_dir):
                op.setdefault("configset-path", configset_dir)
                op.setdefault("configset", collection)

    # Translate force-merge params
    if op_type == "force-merge" and "max-num-segments" in op:
        op["max-segments"] = op.pop("max-num-segments")

    # Translate search body from OpenSearch DSL to Solr JSON DSL
    if op_type in ("search", "paginated-search", "scroll-search"):
        body = op.get("body")
        if isinstance(body, dict) and isinstance(body.get("query"), dict):
            try:
                op["body"] = translate_to_solr_json_dsl(body)
            except Exception as exc:
                issues.append(f"Could not translate search body for op '{op.get('name', '?')}': {exc}")

        # Load body from file if referenced
        body_file = op.get("body-params", {}).get("body") if isinstance(op.get("body-params"), dict) else None
        if body_file and isinstance(body_file, str) and not body_file.startswith("{"):
            body_abs = os.path.join(source_dir, body_file)
            if os.path.isfile(body_abs):
                try:
                    with open(body_abs, encoding="utf-8") as f:
                        body_dict = json.load(f)
                    if isinstance(body_dict.get("query"), dict):
                        converted = translate_to_solr_json_dsl(body_dict)
                        out_body_dir = os.path.join(output_dir, os.path.dirname(body_file))
                        os.makedirs(out_body_dir, exist_ok=True)
                        out_body_path = os.path.join(output_dir, body_file)
                        with open(out_body_path, "w", encoding="utf-8") as f:
                            json.dump(converted, f, indent=2)
                except Exception as exc:
                    issues.append(f"Could not translate body file '{body_file}': {exc}")

    return True


def _copy_auxiliary_files(source_dir: str, output_dir: str, skip_files: set = None):
    """
    Copy Python param sources and other non-JSON files from source to output.

    Files already handled elsewhere (workload.json, operations/, test_procedures/,
    configsets/) are skipped; everything else is copied verbatim.

    Args:
        source_dir: Source workload directory.
        output_dir: Destination workload directory.
        skip_files: Additional filenames to skip (e.g. index body files like ``index.json``).
    """
    _skip_files = {"workload.json"} | (skip_files or set())
    # These subdirectories are handled by _process_collected_files and _generate_configsets
    skip_dirs = {"__pycache__", ".git", "configsets", "operations", "test_procedures"}

    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        rel_root = os.path.relpath(root, source_dir)
        out_root = os.path.join(output_dir, rel_root) if rel_root != "." else output_dir

        for filename in files:
            if filename in _skip_files:
                continue
            src_path = os.path.join(root, filename)
            dst_path = os.path.join(out_root, filename)
            if not os.path.exists(dst_path):
                os.makedirs(out_root, exist_ok=True)
                try:
                    shutil.copy2(src_path, dst_path)
                except OSError as exc:
                    logger.warning("Could not copy '%s': %s", src_path, exc)


def _process_external_collected_files(source_dir: str, output_dir: str, issues: list, skipped: list):
    """
    Make the converted workload self-contained by following external benchmark.collect() refs.

    Some workloads (e.g. geonames) reference shared operation fragments outside the workload
    directory via relative paths like ``../../common_operations/workload_setup.json``.
    Those files are not part of ``source_dir`` so they were not converted by
    ``_process_collected_files()``.

    This function:
      1. Scans every JSON file already written to ``output_dir`` for ``benchmark.collect()`` calls.
      2. Resolves each ``parts="..."`` path relative to the corresponding source file.
      3. If the resolved path falls **outside** ``source_dir`` (an "external" ref):
         a. Converts the external file (renames operation types, translates search bodies).
         b. Copies it into ``output_dir``, preserving the sub-directory name relative to
            ``source_dir``'s parent directory (e.g. ``common_operations/``).
         c. Rewrites the ``parts="..."`` value in the output file to the new relative path.
      4. Recurses into each newly created external file to handle nested ``benchmark.collect()``
         calls (e.g. ``workload_setup.json`` itself references ``delete_index.json`` etc.).
    """
    source_abs = os.path.abspath(source_dir)
    output_abs = os.path.abspath(output_dir)
    # Parent of source_dir (e.g. workloads/default/) — used to anchor external file paths
    source_parent = os.path.dirname(source_abs)
    # Guard: don't convert the same external file twice
    converted_dsts: set = set()

    def _ensure_external(ext_abs: str, src_file_abs: str) -> str | None:
        """
        Convert *ext_abs* (an external source file) and write it to the mirrored location
        inside *output_abs*.  Returns the absolute destination path, or None on failure.
        """
        try:
            rel_from_parent = os.path.relpath(ext_abs, source_parent)
        except ValueError:
            return None  # Different drive (Windows) — skip
        if rel_from_parent.startswith(".."):
            return None  # Too far up the tree — can't mirror safely

        dst_abs = os.path.normpath(os.path.join(output_abs, rel_from_parent))

        if dst_abs in converted_dsts:
            return dst_abs  # Already done
        converted_dsts.add(dst_abs)

        if not os.path.isfile(ext_abs):
            issues.append(f"External benchmark.collect reference not found: {ext_abs}")
            return None

        os.makedirs(os.path.dirname(dst_abs), exist_ok=True)

        with open(ext_abs, encoding="utf-8") as f:
            raw = f.read()

        converted = _convert_fragment_text(raw, issues, skipped)
        with open(dst_abs, "w", encoding="utf-8") as f:
            f.write(converted)

        # Recurse: the newly written file may itself have benchmark.collect() calls
        _process_one_file(dst_abs, ext_abs)
        return dst_abs

    def _convert_fragment_text(raw: str, issues: list, skipped: list) -> str:
        """
        Convert operation types in a fragment file (JSON or Jinja2-with-JSON).

        Tries structured parse+convert first; falls back to regex-based text rename.
        """
        try:
            ops_list, tokens = _parse_jinja_fragment(raw, wrap_array=True)
            for item in ops_list:
                if not isinstance(item, dict):
                    continue
                op = item.get("operation")
                if isinstance(op, str):
                    new_op = _OP_MAP.get(op)
                    if new_op and new_op != op:
                        item["operation"] = new_op
                elif isinstance(op, dict):
                    _convert_operation(op, issues, skipped, "", "")
            return _serialise_jinja_fragment(ops_list, tokens, wrap_array=True)
        except ValueError:
            # Complex Jinja2 — fall back to text substitution for known op-type strings
            result = raw
            for old_op, new_op in _OP_MAP.items():
                if old_op != new_op:
                    result = re.sub(
                        rf'(:\s*"){re.escape(old_op)}(")',
                        rf"\1{new_op}\2",
                        result,
                    )
            return result

    def _process_one_file(out_file_abs: str, src_file_abs: str):
        """
        Scan *out_file_abs* for external benchmark.collect() refs, convert+copy the
        referenced files, and rewrite the ``parts="..."`` paths in-place.

        *src_file_abs* is the original source file whose location is used to resolve
        relative ``parts="..."`` paths.
        """
        with open(out_file_abs, encoding="utf-8") as f:
            content = f.read()
        if "benchmark.collect" not in content:
            return

        src_dir_of_file = os.path.dirname(src_file_abs)
        out_dir_of_file = os.path.dirname(out_file_abs)

        def replacer(m):
            prefix, parts_rel, suffix = m.group(1), m.group(2), m.group(3)
            ext_abs = os.path.normpath(os.path.join(src_dir_of_file, parts_rel))

            # If the ref points inside source_dir it was already handled
            if ext_abs.startswith(source_abs + os.sep) or ext_abs == source_abs:
                return m.group(0)

            dst_abs = _ensure_external(ext_abs, src_file_abs)
            if dst_abs is None:
                return m.group(0)

            new_rel = os.path.relpath(dst_abs, out_dir_of_file).replace(os.sep, "/")
            return f"{prefix}{new_rel}{suffix}"

        modified = _COLLECT_RE.sub(replacer, content)
        if modified != content:
            with open(out_file_abs, "w", encoding="utf-8") as f:
                f.write(modified)

    # Walk all JSON files currently in output_dir and process their external collect() refs
    for root, dirs, files in os.walk(output_abs):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", "configsets"}]
        for filename in files:
            if not filename.endswith(".json"):
                continue
            out_file = os.path.join(root, filename)
            rel = os.path.relpath(out_file, output_abs)
            src_file = os.path.join(source_abs, rel)
            _process_one_file(out_file, src_file)


def _write_converted_marker(output_dir: str, source_dir: str, skipped: list, issues: list):
    """Write a CONVERTED.md marker file documenting the conversion."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    skipped_section = ""
    if skipped:
        skipped_section = "\n## Skipped Operations\n\n" + "\n".join(f"- `{op}`" for op in skipped) + "\n"

    issues_section = ""
    if issues:
        issues_section = "\n## Conversion Issues\n\n" + "\n".join(f"- {i}" for i in issues) + "\n"

    content = f"""# Workload Conversion Record

This workload was automatically converted from OpenSearch Benchmark format to
Solr Orbit format by `solrorbit.conversion.workload_converter`.

## Metadata

- **Source workload**: `{os.path.abspath(source_dir)}`
- **Converted at**: `{timestamp}`
- **Converter version**: solr.conversion.workload_converter v1.0
{skipped_section}{issues_section}
## Notes

- Search operation bodies have been translated to Solr JSON Query DSL format.
- Configsets were auto-generated from OpenSearch mappings (review for production use).
- Corpora (dataset files) are unchanged and shared with the source workload.
- Operations with no Solr equivalent were skipped (listed above if any).

Re-running `convert-workload` with `--force` will overwrite this directory.
"""
    marker_path = os.path.join(output_dir, CONVERTED_MARKER)
    with open(marker_path, "w", encoding="utf-8") as f:
        f.write(content)


def _minimal_solrconfig() -> str:
    """Return a minimal solrconfig.xml suitable for benchmark workloads."""
    return """<?xml version="1.0" encoding="UTF-8" ?>
<config>
  <luceneMatchVersion>9.0</luceneMatchVersion>
  <dataDir>${solr.data.dir:}</dataDir>
  <directoryFactory name="DirectoryFactory"
                    class="${solr.directoryFactory:solr.NRTCachingDirectoryFactory}"/>
  <codecFactory class="solr.SchemaCodecFactory"/>
  <schemaFactory class="ClassicIndexSchemaFactory"/>
  <indexConfig>
    <lockType>${solr.lock.type:native}</lockType>
  </indexConfig>
  <updateHandler class="solr.DirectUpdateHandler2">
    <updateLog>
      <str name="dir">${solr.ulog.dir:}</str>
    </updateLog>
    <autoCommit>
      <maxTime>${solr.autoCommit.maxTime:15000}</maxTime>
      <openSearcher>false</openSearcher>
    </autoCommit>
    <autoSoftCommit>
      <maxTime>${solr.autoSoftCommit.maxTime:-1}</maxTime>
    </autoSoftCommit>
  </updateHandler>
  <query>
    <filterCache size="512" initialSize="512" autowarmCount="0"/>
    <queryResultCache size="512" initialSize="512" autowarmCount="0"/>
    <documentCache size="512" initialSize="512" autowarmCount="0"/>
    <enableLazyFieldLoading>true</enableLazyFieldLoading>
    <queryResultWindowSize>20</queryResultWindowSize>
    <queryResultMaxDocsCached>200</queryResultMaxDocsCached>
    <useColdSearcher>false</useColdSearcher>
  </query>
  <requestDispatcher>
    <requestParsers enableRemoteStreaming="true"
                    multipartUploadLimitInKB="-1"
                    formdataUploadLimitInKB="-1"
                    addHttpRequestToContext="false"/>
    <httpCaching never304="true" />
  </requestDispatcher>
  <requestHandler name="/select" class="solr.SearchHandler">
    <lst name="defaults">
      <str name="echoParams">explicit</str>
      <int name="rows">10</int>
    </lst>
  </requestHandler>
  <requestHandler name="/query" class="solr.SearchHandler">
    <lst name="defaults">
      <str name="echoParams">explicit</str>
      <str name="wt">json</str>
      <str name="indent">true</str>
    </lst>
  </requestHandler>
  <requestHandler name="/update" class="solr.UpdateRequestHandler" />
  <requestHandler name="/admin/ping" class="solr.PingRequestHandler">
    <lst name="invariants">
      <str name="q">solrpingquery</str>
    </lst>
    <lst name="defaults">
      <str name="echoParams">all</str>
    </lst>
  </requestHandler>
</config>
"""
