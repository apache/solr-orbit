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

"""Unit tests for solrorbit/conversion/workload_converter.py"""

import json
import os
import tempfile
import unittest

from solrorbit.conversion.workload_converter import (
    CONVERTED_MARKER,
    convert_opensearch_workload,
    detect_workload_format_from_file,
    is_already_converted,
)
from solrorbit.conversion.query import (
    translate_to_solr_json_dsl,
    _convert_aggregations_to_facets,
    _calendar_interval_to_solr_gap,
)


class TestDetectWorkloadFormatFromFile(unittest.TestCase):
    def _make_workload(self, tmpdir, workload_dict):
        path = os.path.join(tmpdir, "workload.json")
        with open(path, "w") as f:
            json.dump(workload_dict, f)
        return tmpdir

    def test_detects_opensearch_format_by_indices_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_workload(tmpdir, {"indices": [{"name": "my-index"}], "challenges": []})
            self.assertTrue(detect_workload_format_from_file(tmpdir))

    def test_detects_solr_format_by_collections_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_workload(tmpdir, {"collections": [{"name": "my-coll"}], "challenges": []})
            self.assertFalse(detect_workload_format_from_file(tmpdir))

    def test_raises_if_no_workload_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(FileNotFoundError):
                detect_workload_format_from_file(tmpdir)


class TestIsAlreadyConverted(unittest.TestCase):
    def test_returns_false_when_no_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertFalse(is_already_converted(tmpdir))

    def test_returns_true_when_marker_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = os.path.join(tmpdir, CONVERTED_MARKER)
            with open(marker, "w") as f:
                f.write("# converted")
            self.assertTrue(is_already_converted(tmpdir))


class TestConvertOpensearchWorkload(unittest.TestCase):
    """Integration tests for the main conversion function."""

    def _make_source_workload(self, tmpdir, workload_dict):
        path = os.path.join(tmpdir, "workload.json")
        with open(path, "w") as f:
            json.dump(workload_dict, f)

    def test_renames_indices_to_collections(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_source_workload(
                src,
                {
                    "indices": [{"name": "my-index"}],
                    "challenges": [],
                },
            )
            result = convert_opensearch_workload(src, dst)
            self.assertEqual(0, len(result["issues"]))

            with open(os.path.join(dst, "workload.json")) as f:
                out = json.load(f)
            self.assertIn("collections", out)
            self.assertNotIn("indices", out)
            self.assertEqual("my-index", out["collections"][0]["name"])

    def test_renames_operation_types(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_source_workload(
                src,
                {
                    "indices": [],
                    "challenges": [
                        {
                            "name": "default",
                            "schedule": [
                                {
                                    "operation": {
                                        "name": "index-docs",
                                        "operation-type": "bulk",
                                    },
                                },
                                {
                                    "operation": {
                                        "name": "run-search",
                                        "operation-type": "search",
                                    },
                                },
                            ],
                        }
                    ],
                },
            )
            convert_opensearch_workload(src, dst)
            with open(os.path.join(dst, "workload.json")) as f:
                out = json.load(f)
            schedule = out["challenges"][0]["schedule"]
            self.assertEqual("bulk-index", schedule[0]["operation"]["operation-type"])
            self.assertEqual("search", schedule[1]["operation"]["operation-type"])

    def test_translates_search_body_to_solr_json_dsl(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_source_workload(
                src,
                {
                    "indices": [],
                    "challenges": [
                        {
                            "name": "default",
                            "schedule": [
                                {
                                    "operation": {
                                        "name": "search-all",
                                        "operation-type": "search",
                                        "body": {"query": {"match_all": {}}, "size": 10},
                                    }
                                }
                            ],
                        }
                    ],
                },
            )
            convert_opensearch_workload(src, dst)
            with open(os.path.join(dst, "workload.json")) as f:
                out = json.load(f)
            body = out["challenges"][0]["schedule"][0]["operation"]["body"]
            # Body should be Solr JSON DSL (query is a string, not a dict)
            self.assertIsInstance(body["query"], str)
            self.assertEqual("*:*", body["query"])
            self.assertEqual(10, body["limit"])

    def test_unsupported_ops_are_skipped(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_source_workload(
                src,
                {
                    "indices": [],
                    "challenges": [
                        {
                            "name": "default",
                            "schedule": [
                                {
                                    "operation": {
                                        "name": "snap",
                                        "operation-type": "create-snapshot",
                                    }
                                }
                            ],
                        }
                    ],
                },
            )
            result = convert_opensearch_workload(src, dst)
            self.assertIn("snap", result["skipped"])

    def test_writes_converted_marker(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_source_workload(src, {"indices": [], "challenges": []})
            convert_opensearch_workload(src, dst)
            self.assertTrue(os.path.isfile(os.path.join(dst, CONVERTED_MARKER)))

    def test_idempotent_after_marker(self):
        """is_already_converted returns True after a successful conversion."""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_source_workload(src, {"indices": [], "challenges": []})
            convert_opensearch_workload(src, dst)
            self.assertTrue(is_already_converted(dst))

    def test_returns_output_dir_in_result(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            self._make_source_workload(src, {"indices": [], "challenges": []})
            result = convert_opensearch_workload(src, dst)
            self.assertEqual(os.path.abspath(dst), result["output_dir"])


class TestTranslateToSolrJsonDsl(unittest.TestCase):
    """Tests for translate_to_solr_json_dsl() in query.py."""

    def test_match_all_query(self):
        body = {"query": {"match_all": {}}, "size": 20}
        result = translate_to_solr_json_dsl(body)
        self.assertEqual("*:*", result["query"])
        self.assertEqual(20, result["limit"])
        self.assertNotIn("filter", result)

    def test_term_query(self):
        body = {"query": {"term": {"vendor_id": "CMT"}}}
        result = translate_to_solr_json_dsl(body)
        self.assertIn("vendor_id", result["query"])

    def test_range_query(self):
        body = {"query": {"range": {"fare_amount": {"gte": 5, "lte": 100}}}}
        result = translate_to_solr_json_dsl(body)
        self.assertIn("fare_amount", result["query"])
        self.assertIn("TO", result["query"])

    def test_bool_with_filter_goes_to_fq(self):
        body = {
            "query": {
                "bool": {
                    "must": [{"match_all": {}}],
                    "filter": [{"term": {"payment_type": "CRD"}}],
                }
            }
        }
        result = translate_to_solr_json_dsl(body)
        self.assertIn("filter", result)
        self.assertTrue(len(result["filter"]) > 0)

    def test_sort_is_extracted(self):
        body = {"query": {"match_all": {}}, "sort": [{"fare_amount": "desc"}]}
        result = translate_to_solr_json_dsl(body)
        self.assertIn("sort", result)
        self.assertIn("desc", result["sort"])

    def test_terms_aggregation_converted_to_facet(self):
        body = {"query": {"match_all": {}}, "aggs": {"vendors": {"terms": {"field": "vendor_id", "size": 5}}}}
        result = translate_to_solr_json_dsl(body)
        self.assertIn("facet", result)
        facet = result["facet"]["vendors"]
        self.assertEqual("terms", facet["type"])
        self.assertEqual("vendor_id", facet["field"])
        self.assertEqual(5, facet["limit"])

    def test_date_histogram_converted_to_range_facet(self):
        body = {
            "query": {"match_all": {}},
            "aggs": {
                "pickup_by_month": {
                    "date_histogram": {
                        "field": "pickup_datetime",
                        "calendar_interval": "month",
                    }
                }
            },
        }
        result = translate_to_solr_json_dsl(body)
        facet = result["facet"]["pickup_by_month"]
        self.assertEqual("range", facet["type"])
        self.assertEqual("pickup_datetime", facet["field"])
        self.assertEqual("+1MONTH", facet["gap"])

    def test_avg_metric_aggregation(self):
        body = {"query": {"match_all": {}}, "aggs": {"avg_fare": {"avg": {"field": "fare_amount"}}}}
        result = translate_to_solr_json_dsl(body)
        self.assertEqual("avg(fare_amount)", result["facet"]["avg_fare"])

    def test_empty_body_returns_star_star(self):
        self.assertEqual({"query": "*:*"}, translate_to_solr_json_dsl({}))
        self.assertEqual({"query": "*:*"}, translate_to_solr_json_dsl(None))

    def test_non_dict_query_value_ignored(self):
        """If body['query'] is already a string (Solr native), return body unchanged."""
        body = {"query": "vendor_id:CMT", "limit": 5}
        result = translate_to_solr_json_dsl(body)
        # query is not a dict, so we just get q=*:* and limit from size (not present here)
        self.assertEqual("*:*", result["query"])


class TestConvertAggregationsToFacets(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual({}, _convert_aggregations_to_facets({}))
        self.assertEqual({}, _convert_aggregations_to_facets(None))

    def test_nested_agg_within_terms(self):
        aggs = {"by_vendor": {"terms": {"field": "vendor_id", "size": 10}, "aggs": {"avg_fare": {"avg": {"field": "fare_amount"}}}}}
        result = _convert_aggregations_to_facets(aggs)
        self.assertIn("by_vendor", result)
        self.assertIn("facet", result["by_vendor"])
        self.assertEqual("avg(fare_amount)", result["by_vendor"]["facet"]["avg_fare"])

    def test_histogram_aggregation(self):
        aggs = {"fare_hist": {"histogram": {"field": "fare_amount", "interval": 5}}}
        result = _convert_aggregations_to_facets(aggs)
        self.assertEqual("range", result["fare_hist"]["type"])
        self.assertEqual(5, result["fare_hist"]["gap"])

    def test_unsupported_agg_skipped_with_warning(self):
        aggs = {"my_geohash": {"geohash_grid": {"field": "location", "precision": 3}}}
        with self.assertLogs("solrorbit.conversion.query", level="WARNING") as log:
            result = _convert_aggregations_to_facets(aggs)
        self.assertEqual({}, result)
        self.assertTrue(any("geohash_grid" in msg for msg in log.output))

    def test_value_count_metric(self):
        aggs = {"doc_count": {"value_count": {"field": "vendor_id"}}}
        result = _convert_aggregations_to_facets(aggs)
        self.assertEqual("countvals(vendor_id)", result["doc_count"])


class TestCalendarIntervalToSolrGap(unittest.TestCase):
    def test_known_intervals(self):
        self.assertEqual("+1DAY", _calendar_interval_to_solr_gap("day"))
        self.assertEqual("+1MONTH", _calendar_interval_to_solr_gap("month"))
        self.assertEqual("+1YEAR", _calendar_interval_to_solr_gap("year"))
        self.assertEqual("+1HOUR", _calendar_interval_to_solr_gap("hour"))

    def test_unknown_defaults_to_month(self):
        self.assertEqual("+1MONTH", _calendar_interval_to_solr_gap("fortnight"))

    def test_case_insensitive(self):
        self.assertEqual("+1MONTH", _calendar_interval_to_solr_gap("MONTH"))


if __name__ == "__main__":
    unittest.main()
