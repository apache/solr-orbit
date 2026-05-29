# SPDX-License-Identifier: Apache-2.0
#
# Modifications by Apache Solr contributors; see git log for details.
# Licensed under the Apache License, Version 2.0.
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.
# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import io
import logging
import time
import zipfile
from pathlib import Path

import requests

from solrorbit.context import RequestContextHolder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SolrClientError(Exception):
    """Base exception for all SolrAdminClient errors."""


class CollectionAlreadyExistsError(SolrClientError):
    """Raised when create_collection() targets an existing collection."""


class CollectionNotFoundError(SolrClientError):
    """Raised when delete_collection() targets a non-existent collection."""


# ---------------------------------------------------------------------------
# SolrAdminClient
# ---------------------------------------------------------------------------

class SolrAdminClient:
    """
    Thin wrapper around requests.Session for Solr V2 API admin operations.

    Handles collection management, configset upload, version detection,
    cluster status, and metrics retrieval. High-frequency data operations
    (indexing, search, commit, optimize) use pysolr directly in runner.py.

    Not thread-safe — each worker process creates its own instance.
    """

    def __init__(self, host: str, port: int = 8983,
                 username: str = None, password: str = None,
                 tls: bool = False, timeout: int = 30):
        scheme = "https" if tls else "http"
        self.base_url = f"{scheme}://{host}:{port}"
        self.api_url = f"{self.base_url}/api"
        self.timeout = timeout
        self._username = username
        self._password = password
        self._session = None  # created lazily on first use

    def _get_session(self) -> requests.Session:
        """Return the shared session, creating it on first call (lazy init)."""
        if self._session is None:
            self._session = requests.Session()
            # Disable automatic proxy detection (trust_env=False) to avoid hanging
            # on macOS after fork() — CFNetwork proxy detection is not fork-safe.
            self._session.trust_env = False
            if self._username and self._password:
                self._session.auth = (self._username, self._password)
            self._session.headers.update({"Accept": "application/json"})
        return self._session

    # ------------------------------------------------------------------
    # Version detection
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Return parsed JSON from GET /api/node/system."""
        resp = self._get("/api/node/system")
        return resp.json()

    def get_version(self) -> str:
        """
        Detect Solr version via GET /api/node/system.

        Returns the version string, e.g. "9.7.0".
        """
        data = self.info()
        try:
            return data["lucene"]["solr-spec-version"]
        except KeyError as exc:
            raise SolrClientError(
                f"Could not parse Solr version from /api/node/system response: {data}"
            ) from exc

    def get_major_version(self) -> int:
        """Return the major version integer (9 or 10)."""
        version = self.get_version()
        return int(version.split(".")[0])

    def wait_for_cluster_ready(self, timeout: int = 60, **kwargs) -> None:
        """
        Poll GET /api/node/system until Solr responds or timeout is exceeded.

        Args:
            timeout: Maximum seconds to wait (default 60).
        """
        deadline = time.monotonic() + timeout
        last_exc = None
        while time.monotonic() < deadline:
            try:
                self.info()
                return
            except Exception as exc:
                last_exc = exc
            time.sleep(2)
        raise SolrClientError(
            f"Solr cluster did not become ready within {timeout}s. Last error: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Configset management
    # ------------------------------------------------------------------

    def upload_configset(self, name: str, configset_dir: str) -> None:
        """
        Zip the configset directory and upload it via the Solr V1 API.

        Uses: POST /solr/admin/configs?action=UPLOAD&name={name}

        The directory must contain a conf/ sub-directory with at minimum
        schema.xml (or managed-schema) and solrconfig.xml.

        Args:
            name:           Configset name to register on the cluster.
            configset_dir:  Local path to the directory containing conf/.
        """
        zip_bytes = self._build_configset_zip(configset_dir)
        # Use V1 API for configsets (V2 API not available in Solr 9.x)
        url = f"{self.base_url}/solr/admin/configs"
        params = {"action": "UPLOAD", "name": name}
        resp = self._get_session().post(
            url,
            params=params,
            data=zip_bytes,
            headers={"Content-Type": "application/zip"},
            timeout=self.timeout,
        )
        self._raise_for_solr_error(resp, f"upload configset '{name}'")
        logger.info("Uploaded configset '%s' from '%s'", name, configset_dir)

    def delete_configset(self, name: str) -> None:
        """
        Delete a configset via the Solr V1 API.

        Uses: POST /solr/admin/configs?action=DELETE&name={name}
        """
        # Use V1 API for configsets (V2 API not available in Solr 9.x)
        url = f"{self.base_url}/solr/admin/configs"
        params = {"action": "DELETE", "name": name}
        resp = self._get_session().post(
            url,
            params=params,
            timeout=self.timeout,
        )
        self._raise_for_solr_error(resp, f"delete configset '{name}'")
        logger.info("Deleted configset '%s'", name)

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def create_collection(self, name: str, configset: str,
                          num_shards: int = 1, replication_factor: int = 1,
                          tlog_replicas: int = 0, pull_replicas: int = 0,
                          wait_for_active_shards: int = 1) -> None:
        """
        Create a Solr collection via POST /api/collections.

        The configset must already exist on the cluster (call upload_configset first).
        ``replication_factor`` maps to ``nrtReplicas`` in the Solr V2 API (they are semantically
        identical: NRT replicas that participate in indexing and serving queries in real time).
        """
        payload = {
            "name": name,
            "config": configset,
            "numShards": num_shards,
            "nrtReplicas": replication_factor,
            "tlogReplicas": tlog_replicas,
            "pullReplicas": pull_replicas,
            "waitForFinalState": True,
        }
        resp = self._get_session().post(
            f"{self.api_url}/collections",
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code == 400:
            body = self._try_parse_json(resp)
            if "already exists" in str(body).lower():
                raise CollectionAlreadyExistsError(
                    f"Collection '{name}' already exists"
                )
        self._raise_for_solr_error(resp, f"create collection '{name}'")
        logger.info("Created collection '%s' (shards=%d, nrt=%d, tlog=%d, pull=%d)",
                    name, num_shards, replication_factor, tlog_replicas, pull_replicas)

    def delete_collection(self, name: str) -> None:
        """Delete a Solr collection via DELETE /api/collections/{name}."""
        resp = self._get_session().delete(
            f"{self.api_url}/collections/{name}",
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            raise CollectionNotFoundError(f"Collection '{name}' not found")
        # Solr 9.x may return 400 with "Could not find collection" instead of 404
        if resp.status_code == 400:
            body = self._try_parse_json(resp)
            msg = body.get("error", {}).get("msg", "") if isinstance(body, dict) else ""
            if "could not find collection" in msg.lower():
                raise CollectionNotFoundError(f"Collection '{name}' not found")
        self._raise_for_solr_error(resp, f"delete collection '{name}'")
        logger.info("Deleted collection '%s'", name)

    # ------------------------------------------------------------------
    # Cluster status
    # ------------------------------------------------------------------

    def get_cluster_status(self) -> dict:
        """Return cluster state via GET /api/cluster."""
        resp = self._get("/api/cluster")
        return resp.json().get("cluster", resp.json())

    def get_clusterstatus(self) -> dict:
        """Return full CLUSTERSTATUS response dict via V1 Collections API."""
        resp = self._get_session().get(
            f"{self.base_url}/solr/admin/collections",
            params={"action": "CLUSTERSTATUS", "wt": "json"},
            timeout=self.timeout,
        )
        self._raise_for_solr_error(resp, "CLUSTERSTATUS")
        return resp.json()

    def get_core_status(self, core_name: str) -> dict:
        """Return Core STATUS for a specific core (leader replica) via V1 Cores API."""
        resp = self._get_session().get(
            f"{self.base_url}/solr/admin/cores",
            params={"action": "STATUS", "core": core_name, "wt": "json"},
            timeout=self.timeout,
        )
        self._raise_for_solr_error(resp, f"Core STATUS for '{core_name}'")
        return resp.json().get("status", {}).get(core_name, {})

    def list_collections(self) -> list:
        """Return list of collection names via Collections API LIST action."""
        resp = self._get_session().get(
            f"{self.base_url}/solr/admin/collections",
            params={"action": "LIST", "wt": "json"},
            timeout=self.timeout,
        )
        self._raise_for_solr_error(resp, "LIST collections")
        return resp.json().get("collections", [])

    def get_luke_stats(self, collection: str) -> dict:
        """Return Luke index stats for a collection (numDocs, segmentCount, etc.)."""
        resp = self._get_session().get(
            f"{self.base_url}/solr/{collection}/admin/luke",
            params={"numTerms": "0", "wt": "json"},
            timeout=self.timeout,
        )
        self._raise_for_solr_error(resp, f"Luke stats for '{collection}'")
        return resp.json().get("index", {})

    def count_documents(self, collection: str) -> int:
        """Return the number of documents in a collection via rows=0 select query."""
        resp = self._get_session().get(
            f"{self.base_url}/solr/{collection}/select",
            params={"q": "*:*", "rows": 0, "wt": "json"},
            timeout=self.timeout,
        )
        self._raise_for_solr_error(resp, f"count documents in '{collection}'")
        return resp.json()["response"]["numFound"]

    def get_schema(self, collection: str) -> dict:
        """Return the schema of a collection via GET /solr/{collection}/schema."""
        resp = self._get(f"/solr/{collection}/schema")
        return resp.json().get("schema", resp.json())

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def get_node_metrics(self):
        """
        Retrieve node metrics via GET /solr/admin/metrics.

        Both Solr 9.x and Solr 10.x use the same endpoint. The response format
        differs by version and is detected via the Content-Type header:
          - application/json  → Solr 9.x custom JSON → returns parsed dict
          - text/plain        → Solr 10.x Prometheus text → returns raw str

        The telemetry device is responsible for parsing the format-specific response.
        """
        resp = self._get_session().get(f"{self.base_url}/solr/admin/metrics", timeout=self.timeout)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/plain" in content_type:
            return resp.text
        return resp.json()

    # ------------------------------------------------------------------
    # Raw request (for the raw-request workload operation)
    # ------------------------------------------------------------------

    def raw_request(self, method: str, path: str,
                    body=None, headers: dict = None) -> requests.Response:
        """
        Send an arbitrary HTTP request to a Solr endpoint.

        Args:
            method:  HTTP method ("GET", "POST", "DELETE", etc.)
            path:    URL path relative to http://{host}:{port}/ (e.g. "/api/cluster")
            body:    Request body (dict → serialized as JSON, str → sent as-is)
            headers: Additional request headers
        """
        url = f"{self.base_url}{path}"
        req_headers = dict(headers or {})
        kwargs = {"timeout": self.timeout, "headers": req_headers}
        if isinstance(body, dict):
            kwargs["json"] = body
        elif isinstance(body, str):
            kwargs["data"] = body
        resp = self._get_session().request(method.upper(), url, **kwargs)
        return resp

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> requests.Response:
        resp = self._get_session().get(f"{self.base_url}{path}", timeout=self.timeout)
        self._raise_for_solr_error(resp, f"GET {path}")
        return resp

    def _raise_for_solr_error(self, resp: requests.Response, operation: str) -> None:
        if resp.ok:
            return
        body = self._try_parse_json(resp)
        msg = body.get("error", {}).get("msg", resp.text) if isinstance(body, dict) else resp.text
        raise SolrClientError(
            f"Solr {operation} failed (HTTP {resp.status_code}): {msg}"
        )

    @staticmethod
    def _try_parse_json(resp: requests.Response) -> dict:
        try:
            return resp.json()
        except Exception:
            return {}

    @staticmethod
    def _build_configset_zip(configset_dir: str) -> bytes:
        """
        Walk configset_dir and produce an in-memory ZIP suitable for
        PUT /api/cluster/configs/{name}.
        """
        buf = io.BytesIO()
        root = Path(configset_dir)
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(root.rglob("*")):
                if file_path.is_file():
                    arcname = file_path.relative_to(root)
                    zf.write(file_path, arcname)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# SolrClient — unified client used by runners and telemetry devices
# ---------------------------------------------------------------------------

class SolrClient(RequestContextHolder):  # pylint: disable=too-many-public-methods
    """
    Single unified Solr client. Wraps SolrAdminClient (admin/HTTP) and pysolr.Solr
    (indexing/search) as private implementation details.

    All runners and telemetry devices receive a SolrClient and call methods
    on it directly — SolrAdminClient and pysolr.Solr are never referenced
    externally.
    """

    class _NoOpTransport:
        async def close(self):
            pass

    def __init__(self, host="localhost", port=8983, username=None, password=None,
                 tls=False, timeout=30):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._tls = tls
        self._timeout = timeout
        self._admin = SolrAdminClient(host=host, port=port, username=username,
                                      password=password, tls=tls, timeout=timeout)
        self._pysolr_clients = {}  # collection → pysolr.Solr (created lazily)
        self.transport = SolrClient._NoOpTransport()

    # ------------------------------------------------------------------
    # Admin / cluster operations  (delegated to _admin)
    # ------------------------------------------------------------------

    def info(self) -> dict:
        """Return cluster info in an Solr Orbit-compatible shape: {name, version.number}."""
        data = self._admin.info()
        return {
            "name": "Apache Solr",
            "version": {"number": data["lucene"]["solr-spec-version"]},
        }

    def get_version(self):
        return self._admin.get_version()

    def get_major_version(self):
        return self._admin.get_major_version()

    def get_cluster_status(self):
        return self._admin.get_cluster_status()

    def get_node_metrics(self):
        return self._admin.get_node_metrics()

    def get_clusterstatus(self):
        return self._admin.get_clusterstatus()

    def get_core_status(self, core_name):
        return self._admin.get_core_status(core_name)

    def list_collections(self):
        return self._admin.list_collections()

    def get_luke_stats(self, collection):
        return self._admin.get_luke_stats(collection)

    def upload_configset(self, name, path):
        return self._admin.upload_configset(name, path)

    def delete_configset(self, name):
        return self._admin.delete_configset(name)

    def create_collection(self, name, *args, **kwargs):
        return self._admin.create_collection(name, *args, **kwargs)

    def delete_collection(self, name, **kwargs):
        return self._admin.delete_collection(name, **kwargs)

    def wait_for_cluster_ready(self, **kwargs):
        return self._admin.wait_for_cluster_ready(**kwargs)

    def raw_request(self, method, path, body=None, headers=None):
        return self._admin.raw_request(method, path, body=body, headers=headers)

    def count_documents(self, collection):
        return self._admin.count_documents(collection)

    def get_schema(self, collection):
        return self._admin.get_schema(collection)

    # Expose the admin client's internal _get for telemetry devices that
    # need direct access to /api/node/system and similar endpoints.
    def _get(self, path: str):
        return self._admin._get(path)

    # ------------------------------------------------------------------
    # Data operations  (delegated to pysolr.Solr, per collection)
    # ------------------------------------------------------------------

    def _get_pysolr(self, collection: str):
        """Return (lazily-created, cached) pysolr.Solr for the given collection."""
        import pysolr  # pylint: disable=import-outside-toplevel
        if collection not in self._pysolr_clients:
            scheme = "https" if self._tls else "http"
            url = f"{scheme}://{self._host}:{self._port}/solr/{collection}"
            session = requests.Session()
            session.trust_env = False  # fork-safe on macOS (no CFNetwork proxy detection)
            if self._username and self._password:
                session.auth = (self._username, self._password)
            self._pysolr_clients[collection] = pysolr.Solr(
                url, timeout=self._timeout, always_commit=False, session=session)
        return self._pysolr_clients[collection]

    def add(self, collection, docs, **kwargs):
        return self._get_pysolr(collection).add(docs, **kwargs)

    def search(self, collection, q, **kwargs):
        return self._get_pysolr(collection).search(q, **kwargs)

    def commit(self, collection, **kwargs):
        return self._get_pysolr(collection).commit(**kwargs)

    def optimize(self, collection, **kwargs):
        return self._get_pysolr(collection).optimize(**kwargs)


class ClientFactory:
    """
    Factory that creates SolrClient instances from cluster host configuration.
    """

    def __init__(self, hosts, client_options):
        self._hosts = hosts
        self._client_options = dict(client_options)
        self.logger = logging.getLogger(__name__)

    def _parse_host(self):
        entry = self._hosts[0] if self._hosts else {}
        if isinstance(entry, dict):
            return entry.get("host", "localhost"), int(entry.get("port", 8983))
        parts = str(entry).rsplit(":", 1)
        host = parts[0] if parts else "localhost"
        port = int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 8983
        return host, port

    def create(self):
        host, port = self._parse_host()
        return SolrClient(
            host=host,
            port=port,
            username=self._client_options.get("basic_auth_user"),
            password=self._client_options.get("basic_auth_password"),
            tls=self._client_options.get("use_ssl", False),
        )

    def create_async(self):
        return self.create()
