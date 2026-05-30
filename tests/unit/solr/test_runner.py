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

"""Unit tests for Solr runners (solrorbit/worker_coordinator/runner.py)"""

import asyncio
import unittest
from unittest.mock import MagicMock

from solrorbit.worker_coordinator.runner import (
    _translate_ndjson_batch,
    SolrBulkIndex,
    SolrSearch,
    SolrCreateCollection,
    SolrDeleteCollection,
)
from solrorbit.conversion.field import normalize_field_name
from solrorbit.conversion.query import translate_opensearch_query


# Backward compatibility aliases for tests
def _normalize_field_name(field):
    """Test compatibility wrapper."""
    return normalize_field_name(field)


def _translate_query_node(node):
    """Test compatibility wrapper — returns only the q string."""
    return translate_opensearch_query({"query": node})["q"]


def _run(coro):
    """Run an async coroutine synchronously for testing."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestFieldNameNormalization(unittest.TestCase):
    """Test OpenSearch to Solr field name normalization with underscore convention."""

    def test_raw_suffix_to_underscore(self):
        """Test that .raw suffix is converted to underscore."""
        self.assertEqual("country_code_raw", _normalize_field_name("country_code.raw"))
        self.assertEqual("name_raw", _normalize_field_name("name.raw"))
        self.assertEqual("title_raw", _normalize_field_name("title.raw"))

    def test_keyword_suffix_to_underscore(self):
        """Test that .keyword suffix is converted to underscore."""
        self.assertEqual("country_code_keyword", _normalize_field_name("country_code.keyword"))
        self.assertEqual("name_keyword", _normalize_field_name("name.keyword"))

    def test_sort_suffix_to_underscore(self):
        """Test that .sort suffix is converted to underscore."""
        self.assertEqual("title_sort", _normalize_field_name("title.sort"))
        self.assertEqual("name_sort", _normalize_field_name("name.sort"))

    def test_regular_fields_unchanged(self):
        """Test that regular field names are unchanged."""
        self.assertEqual("country_code", _normalize_field_name("country_code"))
        self.assertEqual("title", _normalize_field_name("title"))
        self.assertEqual("_id", _normalize_field_name("_id"))

    def test_term_query_with_raw_field(self):
        """Test that term queries with .raw fields are normalized to _raw."""
        query = {"term": {"country_code.raw": "US"}}
        result = _translate_query_node(query)
        # Should use country_code_raw (underscore convention)
        self.assertEqual("country_code_raw:US", result)

    def test_term_query_with_keyword_field(self):
        """Test that term queries with .keyword fields are normalized to _keyword."""
        query = {"term": {"name.keyword": "John"}}
        result = _translate_query_node(query)
        self.assertEqual("name_keyword:John", result)

    def test_range_query_with_raw_field(self):
        """Test that range queries with .raw fields are normalized to _raw."""
        query = {"range": {"population.raw": {"gte": 1000, "lte": 5000}}}
        result = _translate_query_node(query)
        self.assertEqual("population_raw:[1000 TO 5000]", result)

    def test_exists_query_with_raw_field(self):
        """Test that exists queries with .raw fields are normalized to _raw."""
        query = {"exists": {"field": "country_code.raw"}}
        result = _translate_query_node(query)
        self.assertEqual("country_code_raw:[* TO *]", result)


class TestTranslateNdjsonBatch(unittest.TestCase):
    def test_id_injected_from_action_line(self):
        lines = [
            '{"index": {"_id": "doc-1", "_index": "my-index"}}',
            '{"title": "hello", "body": "world"}',
        ]
        docs = _translate_ndjson_batch(lines)
        self.assertEqual(1, len(docs))
        self.assertEqual("doc-1", docs[0]["id"])
        self.assertEqual("hello", docs[0]["title"])

    def test_id_absent_when_action_has_no_id(self):
        lines = [
            '{"index": {"_index": "my-index"}}',
            '{"title": "no id"}',
        ]
        docs = _translate_ndjson_batch(lines)
        self.assertEqual(1, len(docs))
        self.assertNotIn("id", docs[0])

    def test_type_dropped(self):
        lines = [
            '{"index": {"_id": "1", "_type": "_doc", "_index": "idx"}}',
            '{"field": "value"}',
        ]
        docs = _translate_ndjson_batch(lines)
        self.assertNotIn("_type", docs[0])

    def test_index_not_stored_in_doc(self):
        lines = [
            '{"index": {"_id": "1", "_index": "my-collection"}}',
            '{"x": 1}',
        ]
        docs = _translate_ndjson_batch(lines)
        self.assertNotIn("_index", docs[0])
        self.assertNotIn("my-collection", docs[0].values())

    def test_multiple_pairs(self):
        lines = [
            '{"index": {"_id": "a"}}',
            '{"f": 1}',
            '{"index": {"_id": "b"}}',
            '{"f": 2}',
        ]
        docs = _translate_ndjson_batch(lines)
        self.assertEqual(2, len(docs))
        self.assertEqual("a", docs[0]["id"])
        self.assertEqual("b", docs[1]["id"])

    def test_malformed_json_skipped(self):
        lines = [
            "not json",
            '{"f": 1}',
        ]
        docs = _translate_ndjson_batch(lines)
        self.assertEqual(0, len(docs))

    def test_empty_lines_ignored(self):
        lines = ["", '{"index": {"_id": "1"}}', '{"f": 1}', ""]
        docs = _translate_ndjson_batch(lines)
        self.assertEqual(1, len(docs))


class TestSolrBulkIndex(unittest.TestCase):
    def _params(self, corpus_lines):
        return {
            "host": "localhost",
            "port": 8983,
            "collection": "test",
            "corpus": corpus_lines,
            "bulk-size": 500,
        }

    def test_bulk_index_returns_weight(self):
        mock_sc = MagicMock()
        mock_sc.add.return_value = None

        lines = [
            '{"index": {"_id": "1"}}',
            '{"title": "doc"}',
        ]
        runner = SolrBulkIndex()
        result = _run(runner(mock_sc, self._params(lines)))

        self.assertEqual(1, result["weight"])
        self.assertEqual("docs", result["unit"])
        self.assertTrue(result["success"])

    def test_bulk_index_reports_errors(self):
        import pysolr

        mock_sc = MagicMock()
        mock_sc.add.side_effect = pysolr.SolrError("Indexing error")

        lines = [
            '{"index": {"_id": "1"}}',
            '{"title": "doc"}',
        ]
        runner = SolrBulkIndex()
        result = _run(runner(mock_sc, self._params(lines)))
        self.assertFalse(result["success"])
        self.assertGreater(result["error-count"], 0)

    def test_simple_ndjson_format(self):
        """Test simple NDJSON (one doc per line, no action lines)."""
        mock_sc = MagicMock()
        mock_sc.add.return_value = None

        # Simple NDJSON: just document lines, no action lines
        lines = [
            '{"vendor_id": "1", "trip_distance": 1.2}',
            '{"vendor_id": "2", "trip_distance": 3.5}',
            '{"vendor_id": "1", "trip_distance": 0.8}',
        ]
        runner = SolrBulkIndex()
        result = _run(runner(mock_sc, self._params(lines)))

        self.assertEqual(3, result["weight"])
        self.assertTrue(result["success"])
        # Verify add was called with 3 docs (collection + docs batch as positional args)
        self.assertEqual(1, mock_sc.add.call_count)
        added_docs = mock_sc.add.call_args[0][1]
        self.assertEqual(3, len(added_docs))


class TestSolrSearch(unittest.TestCase):
    def _base_params(self):
        return {
            "host": "localhost",
            "port": 8983,
            "collection": "test",
        }

    def test_classic_mode(self):
        mock_results = MagicMock()
        mock_results.hits = 42
        mock_sc = MagicMock()
        mock_sc.search.return_value = mock_results

        params = {**self._base_params(), "q": "hello world", "rows": 10}
        runner = SolrSearch()
        result = _run(runner(mock_sc, params))

        self.assertEqual(42, result["hits"])
        self.assertEqual(1, result["weight"])

    def test_json_dsl_mode(self):
        """Mode 2: body with a Solr-style string query → POST to /query endpoint via raw_request."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"response": {"numFound": 7}}
        mock_sc = MagicMock()
        mock_sc.raw_request.return_value = mock_resp

        # Solr JSON DSL uses a string for the 'query' key, not a dict
        params = {**self._base_params(), "body": {"query": "*:*", "limit": 5}}
        runner = SolrSearch()
        result = _run(runner(mock_sc, params))

        self.assertEqual(7, result["hits"])
        mock_sc.raw_request.assert_called_once()

    def test_dict_query_body_posted_to_solr(self):
        """Body with dict query (Solr JSON DSL) is POSTed to /query endpoint via raw_request."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"response": {"numFound": 3}}
        mock_sc = MagicMock()
        mock_sc.raw_request.return_value = mock_resp

        params = {**self._base_params(), "body": {"query": {"match_all": {}}, "size": 20}}
        runner = SolrSearch()
        result = _run(runner(mock_sc, params))

        self.assertEqual(3, result["hits"])
        mock_sc.raw_request.assert_called_once()


class TestSolrCreateCollection(unittest.TestCase):
    def test_two_step_sequence(self):
        import tempfile

        mock_sc = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            params = {
                "collection": "my-coll",
                "configset": "my-config",
                "configset-path": tmpdir,
            }
            runner = SolrCreateCollection()
            _run(runner(mock_sc, params))

        # Verify upload_configset called before create_collection
        mock_sc.upload_configset.assert_called_once_with("my-config", tmpdir)
        mock_sc.create_collection.assert_called_once()

    def test_create_collection_passes_tlog_pull_replicas(self):
        """Runner should pass tlog-replicas and pull-replicas to create_collection."""
        mock_sc = MagicMock()

        params = {
            "collection": "my-coll",
            "configset": "my-config",
            "num-shards": 2,
            "replication-factor": 1,
            "tlog-replicas": 2,
            "pull-replicas": 1,
        }
        runner = SolrCreateCollection()
        _run(runner(mock_sc, params))

        mock_sc.create_collection.assert_called_once_with("my-coll", "my-config", 2, 1, 2, 1)

    def test_create_collection_defaults_tlog_pull_to_zero(self):
        """Runner defaults tlog-replicas and pull-replicas to 0 when omitted."""
        mock_sc = MagicMock()

        params = {
            "collection": "my-coll",
            "configset": "my-config",
        }
        runner = SolrCreateCollection()
        _run(runner(mock_sc, params))

        mock_sc.create_collection.assert_called_once_with("my-coll", "my-config", 1, 1, 0, 0)


class TestSolrDeleteCollection(unittest.TestCase):
    def test_delete_ignores_missing_by_default(self):
        from solrorbit.client import CollectionNotFoundError

        mock_sc = MagicMock()
        mock_sc.delete_collection.side_effect = CollectionNotFoundError("not found")

        params = {
            "collection": "missing-coll",
            "ignore-missing": True,
        }
        runner = SolrDeleteCollection()
        # Should not raise
        _run(runner(mock_sc, params))


class TestRunnerRegistrationSmoke(unittest.TestCase):
    """
    Verify that Solr runners work end-to-end through the MultiClientRunner wrapper.

    The wrapper (created by register_runner) does client_extractor=lambda c: c["default"]
    before calling the runner's __call__.  Tests that bypass register_runner and call
    __call__ directly would miss this extraction and test the wrong calling convention.
    These smoke-tests go through runner_for() so the full wrapper stack is exercised.
    """

    def setUp(self):
        from solrorbit.worker_coordinator.runner import register_default_runners

        register_default_runners()

    def _run_via_framework(self, op_type, clients_dict, params):
        """Look up a registered runner and invoke it the same way execute_single does."""
        from solrorbit.worker_coordinator.runner import runner_for

        wrapped = runner_for(op_type)
        return _run(wrapped(clients_dict, params))

    def test_delete_collection_via_framework(self):
        """SolrDeleteCollection receives SolrClient directly after MultiClientRunner extraction."""
        mock_sc = MagicMock()
        params = {"collection": "smoke-coll", "ignore-missing": True}
        # Pass the dict — the wrapper extracts ["default"] before calling __call__
        self._run_via_framework("delete-collection", {"default": mock_sc}, params)
        mock_sc.delete_collection.assert_called_once_with("smoke-coll")

    def test_bulk_index_via_framework(self):
        """SolrBulkIndex receives SolrClient directly after MultiClientRunner extraction."""
        mock_sc = MagicMock()
        mock_sc.add.return_value = None
        lines = ['{"index": {"_id": "1"}}', '{"title": "doc"}']
        params = {"collection": "smoke-coll", "corpus": lines, "bulk-size": 500}
        result = self._run_via_framework("bulk-index", {"default": mock_sc}, params)
        self.assertTrue(result["success"])
        mock_sc.add.assert_called_once()

    def test_search_via_framework(self):
        """SolrSearch receives SolrClient directly after MultiClientRunner extraction."""
        mock_results = MagicMock()
        mock_results.hits = 5
        mock_sc = MagicMock()
        mock_sc.search.return_value = mock_results
        params = {"collection": "smoke-coll", "q": "*:*"}
        result = self._run_via_framework("search", {"default": mock_sc}, params)
        self.assertEqual(5, result["hits"])


if __name__ == "__main__":
    unittest.main()
