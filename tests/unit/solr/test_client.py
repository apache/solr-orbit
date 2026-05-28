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

"""Unit tests for osbenchmark/client.py (SolrAdminClient)"""

import io
import unittest
from unittest.mock import MagicMock

from osbenchmark.client import (
    SolrAdminClient,
    SolrClientError,
    CollectionAlreadyExistsError,
    CollectionNotFoundError,
)


def _make_response(status_code=200, json_data=None, text="", headers=None):
    """Helper to create a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.text = text
    resp.headers = headers or {"Content-Type": "application/json"}
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


class TestSolrAdminClientGetVersion(unittest.TestCase):
    def _make_client_with_mock_session(self):
        client = SolrAdminClient("localhost")
        client._session = MagicMock()
        return client

    def test_get_version_success(self):
        client = self._make_client_with_mock_session()
        resp = _make_response(json_data={"lucene": {"solr-spec-version": "9.7.0"}})
        client._session.get.return_value = resp
        self.assertEqual("9.7.0", client.get_version())

    def test_get_version_missing_key_raises(self):
        client = self._make_client_with_mock_session()
        resp = _make_response(json_data={"lucene": {}})
        client._session.get.return_value = resp
        with self.assertRaises(SolrClientError):
            client.get_version()

    def test_get_major_version(self):
        client = self._make_client_with_mock_session()
        resp = _make_response(json_data={"lucene": {"solr-spec-version": "10.0.1"}})
        client._session.get.return_value = resp
        self.assertEqual(10, client.get_major_version())


class TestSolrAdminClientUploadConfigset(unittest.TestCase):
    def _make_client_with_mock_session(self):
        client = SolrAdminClient("localhost")
        client._session = MagicMock()
        return client

    def test_upload_configset_success(self):
        import tempfile, os
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=200)
        client._session.put.return_value = resp

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal configset directory structure
            conf_dir = os.path.join(tmpdir, "conf")
            os.makedirs(conf_dir)
            with open(os.path.join(conf_dir, "schema.xml"), "w") as f:
                f.write("<schema/>")

            client.upload_configset("test-config", tmpdir)
            client._session.post.assert_called_once()
            args, kwargs = client._session.post.call_args
            self.assertIn("admin/configs", args[0])
            self.assertEqual("test-config", kwargs["params"]["name"])
            self.assertEqual("UPLOAD", kwargs["params"]["action"])
            self.assertEqual("application/zip", kwargs["headers"]["Content-Type"])

    def test_upload_configset_failure_raises(self):
        import tempfile, os
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=500, text="Server Error")
        client._session.post.return_value = resp

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal configset directory structure
            conf_dir = os.path.join(tmpdir, "conf")
            os.makedirs(conf_dir)
            with open(os.path.join(conf_dir, "schema.xml"), "w") as f:
                f.write("<schema/>")

            with self.assertRaises(SolrClientError):
                client.upload_configset("bad-config", tmpdir)


class TestSolrAdminClientCreateCollection(unittest.TestCase):
    def _make_client_with_mock_session(self):
        client = SolrAdminClient("localhost")
        client._session = MagicMock()
        return client

    def test_create_collection_success(self):
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=200, json_data={"responseHeader": {"status": 0}})
        client._session.post.return_value = resp
        client.create_collection("my-coll", "my-config")
        client._session.post.assert_called_once()

    def test_create_collection_already_exists(self):
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=400, json_data={"error": {"msg": "already exists"}})
        client._session.post.return_value = resp
        with self.assertRaises(CollectionAlreadyExistsError):
            client.create_collection("my-coll", "my-config")

    def test_create_collection_sends_nrt_replicas(self):
        """replication_factor should be sent as nrtReplicas, not replicationFactor."""
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=200, json_data={"responseHeader": {"status": 0}})
        client._session.post.return_value = resp
        client.create_collection("my-coll", "my-config", num_shards=2, replication_factor=3)
        _, kwargs = client._session.post.call_args
        payload = kwargs["json"]
        self.assertEqual(2, payload["numShards"])
        self.assertEqual(3, payload["nrtReplicas"])
        self.assertNotIn("replicationFactor", payload)

    def test_create_collection_tlog_and_pull_replicas(self):
        """tlog_replicas and pull_replicas should be sent in the payload."""
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=200, json_data={"responseHeader": {"status": 0}})
        client._session.post.return_value = resp
        client.create_collection("my-coll", "my-config",
                                 tlog_replicas=2, pull_replicas=1)
        _, kwargs = client._session.post.call_args
        payload = kwargs["json"]
        self.assertEqual(2, payload["tlogReplicas"])
        self.assertEqual(1, payload["pullReplicas"])

    def test_create_collection_defaults_zero_tlog_pull(self):
        """tlog_replicas and pull_replicas default to 0."""
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=200, json_data={"responseHeader": {"status": 0}})
        client._session.post.return_value = resp
        client.create_collection("my-coll", "my-config")
        _, kwargs = client._session.post.call_args
        payload = kwargs["json"]
        self.assertEqual(0, payload["tlogReplicas"])
        self.assertEqual(0, payload["pullReplicas"])


class TestSolrAdminClientDeleteCollection(unittest.TestCase):
    def _make_client_with_mock_session(self):
        client = SolrAdminClient("localhost")
        client._session = MagicMock()
        return client

    def test_delete_collection_success(self):
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=200)
        client._session.delete.return_value = resp
        client.delete_collection("my-coll")

    def test_delete_collection_not_found(self):
        client = self._make_client_with_mock_session()
        resp = _make_response(status_code=404)
        client._session.delete.return_value = resp
        with self.assertRaises(CollectionNotFoundError):
            client.delete_collection("my-coll")

    def test_delete_collection_400_could_not_find(self):
        """Solr 9.x returns HTTP 400 with 'Could not find collection' for missing collections."""
        client = self._make_client_with_mock_session()
        body = {"error": {"msg": "Could not find collection: my-coll"}}
        resp = _make_response(status_code=400, json_data=body)
        client._session.delete.return_value = resp
        with self.assertRaises(CollectionNotFoundError):
            client.delete_collection("my-coll")

    def test_delete_collection_standalone_falls_back_to_cores_api(self):
        """HTTP 500 with 'non-cloud context' triggers a Cores API UNLOAD fallback."""
        client = self._make_client_with_mock_session()
        # Simulate the SolrCloud Collections API failing in standalone mode
        body = {"error": {"msg": "Aliases don't exist in a non-cloud context, check isZookeeperAware() before calling this method."}}
        delete_resp = _make_response(status_code=500, json_data=body)
        client._session.delete.return_value = delete_resp
        # Simulate the Cores API UNLOAD call succeeding
        cores_resp = _make_response(status_code=200, json_data={"responseHeader": {"status": 0}})
        client._session.get.return_value = cores_resp

        client.delete_collection("my-coll")

        # Verify the Cores API was called with UNLOAD action
        client._session.get.assert_called_once()
        call_kwargs = client._session.get.call_args
        url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("url", "")
        params = call_kwargs[1].get("params", {}) if call_kwargs[1] else {}
        self.assertIn("/solr/admin/cores", url)
        self.assertEqual("UNLOAD", params.get("action"))
        self.assertEqual("my-coll", params.get("core"))
        self.assertEqual("true", params.get("deleteIndex"))

    def test_delete_collection_standalone_cores_api_not_found(self):
        """Cores API fallback raises CollectionNotFoundError when core is missing."""
        client = self._make_client_with_mock_session()
        body = {"error": {"msg": "Aliases don't exist in a non-cloud context, check isZookeeperAware() before calling this method."}}
        delete_resp = _make_response(status_code=500, json_data=body)
        client._session.delete.return_value = delete_resp
        cores_resp = _make_response(status_code=404)
        client._session.get.return_value = cores_resp

        with self.assertRaises(CollectionNotFoundError):
            client.delete_collection("my-coll")

    def test_delete_collection_other_500_raises(self):
        """HTTP 500 errors unrelated to non-cloud mode are still raised."""
        client = self._make_client_with_mock_session()
        body = {"error": {"msg": "Internal server error"}}
        resp = _make_response(status_code=500, json_data=body)
        client._session.delete.return_value = resp
        with self.assertRaises(Exception):
            client.delete_collection("my-coll")


class TestSolrAdminClientGetNodeMetrics(unittest.TestCase):
    def _make_client_with_mock_session(self):
        client = SolrAdminClient("localhost")
        client._session = MagicMock()
        return client

    def test_json_format(self):
        client = self._make_client_with_mock_session()
        data = {"metrics": {"solr.jvm": {}}}
        resp = _make_response(json_data=data, headers={"Content-Type": "application/json"})
        client._session.get.return_value = resp
        result = client.get_node_metrics()
        self.assertIsInstance(result, dict)
        self.assertIn("metrics", result)

    def test_prometheus_format(self):
        client = self._make_client_with_mock_session()
        prometheus_text = "# HELP jvm_heap\njvm_heap_used 1234\n"
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.headers = {"Content-Type": "text/plain"}
        resp.text = prometheus_text
        client._session.get.return_value = resp
        result = client.get_node_metrics()
        self.assertIsInstance(result, str)
        self.assertIn("jvm_heap_used", result)


class TestBuildConfigsetZip(unittest.TestCase):
    def test_zip_contains_files(self):
        import tempfile, os, zipfile
        with tempfile.TemporaryDirectory() as tmpdir:
            conf = os.path.join(tmpdir, "conf")
            os.makedirs(conf)
            with open(os.path.join(conf, "schema.xml"), "w") as f:
                f.write("<schema/>")
            with open(os.path.join(conf, "solrconfig.xml"), "w") as f:
                f.write("<config/>")

            zip_bytes = SolrAdminClient._build_configset_zip(tmpdir)
            buf = io.BytesIO(zip_bytes)
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
        self.assertTrue(any("schema.xml" in n for n in names))
        self.assertTrue(any("solrconfig.xml" in n for n in names))


if __name__ == "__main__":
    unittest.main()
