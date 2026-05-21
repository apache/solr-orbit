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
OpenSearch Mappings to Solr Schema Translation

IMPORTANT: This module is ONLY used when converting OpenSearch workloads.
Native Solr workloads should not use this module - they provide their own
schema.xml files in configsets.

This translator handles basic field type mappings and multi-field patterns.
For production benchmarks, always create proper Solr configsets with schema.xml
tailored to your use case.

Translation Limitations:
- Not all OpenSearch types have direct Solr equivalents
- Complex features (nested objects) are not fully supported
- Analyzer configurations are simplified
- Date formats may need manual adjustment

Multi-Field Handling:
OpenSearch workloads often use multi-field patterns where a text field has
keyword sub-fields for exact matching:

  OpenSearch mapping:
    "country_code": {
      "type": "text",
      "fields": {
        "raw": {"type": "keyword"}
      }
    }

  Generated Solr schema:
    <field name="country_code" type="text_general" ... />
    <field name="country_code_raw" type="string" docValues="true" ... />
    <copyField source="country_code" dest="country_code_raw" />

Field names are converted using underscore convention (country_code.raw → country_code_raw).
Query translation automatically handles this mapping so workloads work transparently.

Supported sub-field patterns: .raw, .keyword, .sort (all mapped to underscore equivalents).
"""

import logging
import os
import tempfile
import shutil
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# OpenSearch type → Solr type mapping
# Note: This is a best-effort mapping for common cases
OPENSEARCH_TO_SOLR_TYPES = {
    # Numeric types
    "scaled_float": "pdouble",      # Note: loses scaling_factor precision control
    "half_float": "pfloat",
    "float": "pfloat",
    "double": "pdouble",
    "byte": "pint",
    "short": "pint",
    "integer": "pint",
    "long": "plong",

    # String types
    "keyword": "string",            # Exact match, no analysis
    "text": "text_general",         # Analyzed text

    # Other types
    "boolean": "boolean",
    "date": "pdate",
    "binary": "binary",

    # Spatial
    "geo_point": "string",    # Stored as "lat,lon" string (converted during indexing)
}


def translate_opensearch_mapping(properties: Dict[str, Any]) -> tuple[Dict[str, Dict[str, Any]], list[tuple[str, str]]]:
    """
    Translate OpenSearch field mappings to Solr field definitions.

    Args:
        properties: The "properties" dict from OpenSearch index.json mappings

    Returns:
        Tuple of (field_defs, copy_fields) where:
        - field_defs: Dict of field_name → solr_field_config
        - copy_fields: List of (source, dest) tuples for copyField directives

    Raises:
        ValueError: If a field type cannot be translated
    """
    solr_fields = {}
    copy_fields = []

    for field_name, field_config in properties.items():
        os_type = field_config.get("type")

        if not os_type:
            logger.warning(f"Field '{field_name}' has no type, skipping")
            continue

        # Translate main field
        solr_type = OPENSEARCH_TO_SOLR_TYPES.get(os_type)
        if not solr_type:
            logger.warning(
                f"Field '{field_name}' has unsupported type '{os_type}', "
                f"falling back to 'string'"
            )
            solr_type = "string"

        # Build Solr field config
        solr_field = {
            "type": solr_type,
            "indexed": True,
            "stored": True,
        }

        # Add docValues for keyword fields (efficient for sorting/faceting)
        if os_type == "keyword":
            solr_field["docValues"] = True

        # Handle date format
        if os_type == "date":
            # OpenSearch: "format": "yyyy-MM-dd HH:mm:ss"
            # Solr: Uses ISO8601 by default, custom formats need DatePointField config
            os_format = field_config.get("format")
            if os_format and os_format != "strict_date_optional_time||epoch_millis":
                logger.warning(
                    f"Field '{field_name}' has custom date format '{os_format}'. "
                    f"Solr will use ISO8601 format. Manual schema adjustment may be needed."
                )

        solr_fields[field_name] = solr_field

        # Handle multi-fields (OpenSearch sub-fields like .raw, .keyword, .sort)
        # Example: {"country_code": {"type": "text", "fields": {"raw": {"type": "keyword"}}}}
        multi_fields = field_config.get("fields", {})
        for sub_field_name, sub_field_config in multi_fields.items():
            sub_type = sub_field_config.get("type")
            if not sub_type:
                continue

            # Create Solr field name using underscore convention
            # OpenSearch: country_code.raw → Solr: country_code_raw
            solr_sub_field_name = f"{field_name}_{sub_field_name}"

            # Translate sub-field type
            sub_solr_type = OPENSEARCH_TO_SOLR_TYPES.get(sub_type, "string")

            # Build sub-field config
            sub_field_def = {
                "type": sub_solr_type,
                "indexed": True,
                "stored": True,
            }

            # Keyword sub-fields (for exact matching, sorting) need docValues
            if sub_type == "keyword":
                sub_field_def["docValues"] = True

            solr_fields[solr_sub_field_name] = sub_field_def

            # Add copyField directive from main field to sub-field
            copy_fields.append((field_name, solr_sub_field_name))

            logger.info(
                f"Multi-field detected: {field_name}.{sub_field_name} → "
                f"{solr_sub_field_name} (type: {sub_solr_type})"
            )

    return solr_fields, copy_fields


def generate_schema_xml(field_defs: Dict[str, Dict[str, Any]],
                        copy_fields: Optional[list[tuple[str, str]]] = None,
                        unique_key: str = "id") -> str:
    """
    Generate a Solr schema.xml from field definitions.

    Args:
        field_defs: Field definitions from translate_opensearch_mapping()
        copy_fields: List of (source, dest) tuples for copyField directives
        unique_key: Name of the unique key field (default: "id")

    Returns:
        Complete schema.xml content as string
    """
    if copy_fields is None:
        copy_fields = []

    # Build field definitions XML
    fields_xml = []

    # Add required fields for SolrCloud
    fields_xml.append('  <!-- Required fields for SolrCloud -->')
    fields_xml.append(f'  <field name="{unique_key}" type="string" indexed="true" stored="true" required="true" />')
    fields_xml.append('  <field name="_version_" type="plong" indexed="true" stored="false" docValues="true" />')
    fields_xml.append('  <field name="_root_" type="string" indexed="true" stored="false" docValues="false" />')
    fields_xml.append('  <field name="_text_" type="text_general" indexed="true" stored="false" multiValued="true" />')
    fields_xml.append('')
    fields_xml.append('  <!-- Workload fields (auto-generated from OpenSearch mappings) -->')

    # Add workload fields
    for field_name, field_config in field_defs.items():
        # Skip if it's the unique key (already added)
        if field_name == unique_key:
            continue

        field_type = field_config["type"]
        indexed = str(field_config.get("indexed", True)).lower()
        stored = str(field_config.get("stored", True)).lower()
        doc_values = field_config.get("docValues")

        attrs = [
            f'name="{field_name}"',
            f'type="{field_type}"',
            f'indexed="{indexed}"',
            f'stored="{stored}"',
        ]

        if doc_values is not None:
            attrs.append(f'docValues="{str(doc_values).lower()}"')

        fields_xml.append(f'  <field {" ".join(attrs)} />')

    # Build copyField directives XML
    copy_fields_xml = []
    if copy_fields:
        copy_fields_xml.append('')
        copy_fields_xml.append('  <!-- Multi-field copyField directives (OpenSearch → Solr translation) -->')
        for source, dest in copy_fields:
            copy_fields_xml.append(f'  <copyField source="{source}" dest="{dest}" />')

    # Complete schema XML
    schema_xml = f"""<?xml version="1.0" encoding="UTF-8" ?>
<!--
  AUTO-GENERATED SCHEMA (OpenSearch → Solr translation)

  WARNING: This schema was automatically generated from OpenSearch mappings
  as a convenience fallback. For production use, create a proper Solr schema.xml
  tailored to your specific requirements.

  Generated by: osbenchmark.conversion.schema
-->
<schema name="auto-generated" version="1.6">
  <!-- Field Types -->

  <!-- String: exact match, no tokenization -->
  <fieldType name="string" class="solr.StrField" sortMissingLast="true" docValues="true" />

  <!-- Boolean -->
  <fieldType name="boolean" class="solr.BoolField" sortMissingLast="true" />

  <!-- Binary -->
  <fieldType name="binary" class="solr.BinaryField" />

  <!-- Point-based numeric types (for range queries, sorting) -->
  <fieldType name="pint" class="solr.IntPointField" docValues="true" />
  <fieldType name="plong" class="solr.LongPointField" docValues="true" />
  <fieldType name="pfloat" class="solr.FloatPointField" docValues="true" />
  <fieldType name="pdouble" class="solr.DoublePointField" docValues="true" />
  <fieldType name="pdate" class="solr.DatePointField" docValues="true" />

  <!-- Text: analyzed for full-text search -->
  <fieldType name="text_general" class="solr.TextField" positionIncrementGap="100" multiValued="true">
    <analyzer type="index">
      <tokenizer class="solr.StandardTokenizerFactory" />
      <filter class="solr.StopFilterFactory" words="stopwords.txt" ignoreCase="true" />
      <filter class="solr.LowerCaseFilterFactory" />
    </analyzer>
    <analyzer type="query">
      <tokenizer class="solr.StandardTokenizerFactory" />
      <filter class="solr.StopFilterFactory" words="stopwords.txt" ignoreCase="true" />
      <filter class="solr.SynonymGraphFilterFactory" expand="true" ignoreCase="true" synonyms="synonyms.txt" />
      <filter class="solr.LowerCaseFilterFactory" />
    </analyzer>
  </fieldType>

  <!-- Spatial: lat/lon point -->
  <fieldType name="location_rpt" class="solr.SpatialRecursivePrefixTreeFieldType"
             geo="true" distErrPct="0.025" maxDistErr="0.001" distanceUnits="kilometers" />

  <!-- Fields -->
{chr(10).join(fields_xml)}

  <!-- Unique Key -->
  <uniqueKey>{unique_key}</uniqueKey>

  <!-- Copy Fields for Multi-Field Support -->
{chr(10).join(copy_fields_xml)}

  <!-- Copy field for default search -->
  <copyField source="*" dest="_text_" />
</schema>
"""

    return schema_xml


def create_configset_from_schema(schema_xml: str,
                                 configset_name: Optional[str] = None) -> str:
    """
    Create a temporary Solr configset directory with the generated schema.

    IMPORTANT: Files are created at the root level (not under conf/) because
    when uploaded to ZooKeeper via the configset API, Solr expects files
    directly under /configs/{name}/, not /configs/{name}/conf/.

    Args:
        schema_xml: Complete schema.xml content
        configset_name: Optional name for the configset (used in directory name)

    Returns:
        Path to the configset directory (e.g., /tmp/solr-configset-XXXXX/)

    Note:
        Caller is responsible for cleaning up the temporary directory after use.
    """
    # Create temporary directory
    prefix = f"solr-configset-{configset_name}-" if configset_name else "solr-configset-"
    configset_dir = tempfile.mkdtemp(prefix=prefix)

    # Write schema.xml at root level (NOT under conf/)
    schema_path = os.path.join(configset_dir, "schema.xml")
    with open(schema_path, "w", encoding="utf-8") as f:
        f.write(schema_xml)

    # Create minimal solrconfig.xml
    # This is a bare-bones config that works for basic indexing/searching
    solrconfig_xml = """<?xml version="1.0" encoding="UTF-8" ?>
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
    <filterCache size="512"
                 initialSize="512"
                 autowarmCount="0"/>
    <queryResultCache size="512"
                      initialSize="512"
                      autowarmCount="0"/>
    <documentCache size="512"
                   initialSize="512"
                   autowarmCount="0"/>
    <cache name="perSegFilter"
           class="solr.CaffeineCache"
           size="10"
           initialSize="0"
           autowarmCount="10"
           regenerator="solr.NoOpRegenerator" />
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

    # Write solrconfig.xml at root level
    solrconfig_path = os.path.join(configset_dir, "solrconfig.xml")
    with open(solrconfig_path, "w", encoding="utf-8") as f:
        f.write(solrconfig_xml)

    # Create empty stopwords.txt and synonyms.txt at root level (required by text_general)
    stopwords_path = os.path.join(configset_dir, "stopwords.txt")
    with open(stopwords_path, "w", encoding="utf-8") as f:
        f.write("# Auto-generated empty stopwords file\n")

    synonyms_path = os.path.join(configset_dir, "synonyms.txt")
    with open(synonyms_path, "w", encoding="utf-8") as f:
        f.write("# Auto-generated empty synonyms file\n")

    logger.info(f"Created temporary configset at: {configset_dir}")
    return configset_dir


def cleanup_configset(configset_path: str) -> None:
    """
    Remove a temporary configset directory.

    Args:
        configset_path: Path to the configset directory to remove
    """
    try:
        if os.path.exists(configset_path):
            shutil.rmtree(configset_path)
            logger.info(f"Cleaned up temporary configset: {configset_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up configset at {configset_path}: {e}")
