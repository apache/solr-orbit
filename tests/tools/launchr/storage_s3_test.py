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
"""The S3 storage backend.

Two layers, because neither alone is enough:

* **Offline** -- URI parsing and the mapping from S3 error codes to launchr's
  exceptions, driven by a stub client. Runs everywhere, including CI with no
  credentials.
* **Against a real bucket** -- the same shared contract the local backend
  passes, so "identical layout across backends" is verified rather than
  asserted. Opt-in: set ``LAUNCHR_IT_S3_URI`` to a prefix you are happy for a
  test to write to and delete under, e.g.
  ``LAUNCHR_IT_S3_URI=s3://solr-orbit/_it AWS_PROFILE=solr-orbit``.
  A stub cannot stand in for this: conditional writes, prefix semantics and
  pagination are exactly where a fake and the real service diverge.
"""

import os
import uuid

import pytest

from solrorbit.tools.launchr.errors import ConfigError, StorageError
from solrorbit.tools.launchr.storage.s3 import S3StorageBackend, parse_uri
from tests.tools.launchr.storage_contract import StorageContract

IT_URI = os.environ.get("LAUNCHR_IT_S3_URI")


# ---------------------------------------------------------------------------
# Offline
# ---------------------------------------------------------------------------


class TestUriParsing:
    def test_splits_bucket_and_prefix(self):
        assert parse_uri("s3://solr-orbit/v1/runs") == ("solr-orbit", "v1/runs")

    def test_a_bare_bucket_has_an_empty_prefix(self):
        assert parse_uri("s3://solr-orbit") == ("solr-orbit", "")

    def test_surrounding_slashes_are_normalised(self):
        # Otherwise joining produces "prefix//key", which S3 stores happily and
        # nothing can address afterwards.
        assert parse_uri("s3://solr-orbit/v1/") == ("solr-orbit", "v1")

    @pytest.mark.parametrize("uri", [
        "/local/path", "https://solr-orbit.s3.amazonaws.com/x", "s3:/solr-orbit",
    ])
    def test_a_non_s3_uri_is_rejected(self, uri):
        with pytest.raises(ConfigError, match="s3://"):
            parse_uri(uri)

    def test_a_missing_bucket_is_rejected(self):
        with pytest.raises(ConfigError, match="No bucket"):
            parse_uri("s3:///just/a/path")

    @pytest.mark.parametrize("bucket", ["UPPERCASE", "x", "has_underscore", "-leading"])
    def test_an_invalid_bucket_name_is_rejected(self, bucket):
        with pytest.raises(ConfigError, match="not a valid S3 bucket name"):
            parse_uri(f"s3://{bucket}/prefix")

    def test_location_renders_the_uri_back(self):
        assert S3StorageBackend("s3://solr-orbit/v1").location == "s3://solr-orbit/v1"

    def test_unknown_options_are_rejected(self):
        with pytest.raises(ConfigError, match="Unknown storage.options"):
            S3StorageBackend("s3://solr-orbit/v1", regoin="eu-north-1")


class TestKeyMapping:
    @pytest.fixture
    def backend(self):
        return S3StorageBackend("s3://solr-orbit/v1")

    def test_a_relative_path_is_joined_to_the_prefix(self, backend):
        assert backend._key("runs/a/results.json") == "v1/runs/a/results.json"

    def test_an_empty_prefix_leaves_the_path_alone(self):
        assert S3StorageBackend("s3://solr-orbit")._key("a.json") == "a.json"

    @pytest.mark.parametrize("path", ["/etc/passwd", "../outside", "a/../../outside"])
    def test_escapes_are_refused(self, backend, path):
        with pytest.raises(StorageError):
            backend._key(path)

    def test_a_dotdot_inside_a_segment_is_not_an_escape(self, backend):
        # "..log" is a filename, not a traversal; rejecting it would be wrong.
        assert backend._key("logs/..log").endswith("logs/..log")


class _StubClient:
    """Minimal boto3 S3 stand-in that raises whatever a test asks it to."""

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))
        if self.error:
            raise self.error
        return {}

    def head_object(self, **kwargs):
        self.calls.append(("head_object", kwargs))
        if self.error:
            raise self.error
        return {}

    def get_object(self, **kwargs):
        self.calls.append(("get_object", kwargs))
        if self.error:
            raise self.error
        raise AssertionError("unreachable")


def _client_error(code):
    from botocore.exceptions import ClientError
    return ClientError({"Error": {"Code": code, "Message": code}}, "PutObject")


class TestErrorMapping:
    @pytest.fixture
    def backend(self):
        return S3StorageBackend("s3://solr-orbit/v1")

    def test_an_immutable_write_names_the_rule(self, backend):
        backend._client = _StubClient(_client_error("PreconditionFailed"))
        with pytest.raises(StorageError, match="immutable"):
            backend.write("a.json", b"{}")

    def test_a_write_sends_the_conditional_header_by_default(self, backend):
        backend._client = stub = _StubClient()
        backend.write("a.json", b"{}")
        assert stub.calls[0][1]["IfNoneMatch"] == "*"

    def test_an_explicit_overwrite_drops_the_condition(self, backend):
        backend._client = stub = _StubClient()
        backend.write("a.json", b"{}", overwrite=True)
        assert "IfNoneMatch" not in stub.calls[0][1]

    def test_a_transport_failure_is_a_storage_error_not_an_immutability_one(self, backend):
        backend._client = _StubClient(_client_error("InternalError"))
        with pytest.raises(StorageError, match="Could not write"):
            backend.write("a.json", b"{}")

    @pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
    def test_a_missing_object_does_not_exist(self, backend, code):
        backend._client = _StubClient(_client_error(code))
        assert backend.exists("a.json") is False

    def test_access_denied_is_raised_rather_than_read_as_absent(self, backend):
        # Reporting a permissions problem as "not there" would send a reader
        # hunting for a lost report that is sitting right where it should be.
        backend._client = _StubClient(_client_error("AccessDenied"))
        with pytest.raises(StorageError, match="Could not check"):
            backend.exists("a.json")

    def test_a_read_failure_names_the_path_and_location(self, backend):
        backend._client = _StubClient(_client_error("NoSuchKey"))
        with pytest.raises(StorageError, match="a.json.*s3://solr-orbit/v1"):
            backend.read("a.json")


class TestCredentialHandling:
    def test_the_client_is_not_built_until_it_is_used(self):
        # validate-config must work on a machine with no AWS credentials.
        backend = S3StorageBackend("s3://solr-orbit/v1", profile="does-not-exist")
        assert backend._client is None

    def test_an_unknown_profile_fails_as_a_storage_error(self):
        backend = S3StorageBackend("s3://solr-orbit/v1", profile="definitely-not-a-profile")
        with pytest.raises(StorageError, match="Could not create an S3 client"):
            _ = backend.client


# ---------------------------------------------------------------------------
# Against a real bucket
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not IT_URI, reason="set LAUNCHR_IT_S3_URI to run against a real bucket")
class TestS3Contract(StorageContract):
    """The shared suite, against S3 itself."""

    @pytest.fixture
    def storage(self):
        backend = S3StorageBackend(
            f"{IT_URI.rstrip('/')}/{uuid.uuid4().hex[:12]}",
            profile=os.environ.get("LAUNCHR_IT_S3_PROFILE"),
            region=os.environ.get("AWS_DEFAULT_REGION", "eu-north-1"),
        )
        yield backend
        # Leaving test objects in a real bucket costs money and confuses the
        # next reader, so clean up even when the test failed.
        keys = [{"Key": backend._key(p)} for p in backend.list("")]
        if keys:
            backend.client.delete_objects(Bucket=backend.bucket, Delete={"Objects": keys})
