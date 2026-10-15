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

import asyncio
from unittest import TestCase

import pytest

from solrorbit import client
from tests import run_async


class RequestContextManagerTests(TestCase):
    @pytest.mark.skip(reason="latency is system-dependent")
    @run_async
    async def test_propagates_nested_context(self):
        test_client = client.RequestContextHolder()
        async with test_client.new_request_context() as top_level_ctx:
            test_client.on_request_start()
            await asyncio.sleep(0.1)
            async with test_client.new_request_context() as nested_ctx:
                test_client.on_request_start()
                await asyncio.sleep(0.1)
                test_client.on_request_end()
                nested_duration = nested_ctx.request_end - nested_ctx.request_start
            test_client.on_request_end()
            top_level_duration = top_level_ctx.request_end - top_level_ctx.request_start

        # top level request should cover total duration
        self.assertAlmostEqual(top_level_duration, 0.2, delta=0.05)
        # nested request should only cover nested duration
        self.assertAlmostEqual(nested_duration, 0.1, delta=0.05)


class CreateCollectionApiShapeTests(TestCase):
    """Solr reworked its V2 API: newer releases take the collection's
    properties as the request body, older ones take a ``{"create": {...}}``
    envelope. Benchmarking a release line means talking to both."""

    class FakeResponse:
        def __init__(self, status_code, body=None):
            self.status_code = status_code
            self._body = body if body is not None else {}
            self.text = str(self._body)
            self.ok = status_code < 400

        def json(self):
            return self._body

    class FakeSession:
        def __init__(self, reject_first):
            self.reject_first = reject_first
            self.posts = []

        def post(self, url, json=None, timeout=None):
            self.posts.append(json)
            if self.reject_first and len(self.posts) == 1:
                return CreateCollectionApiShapeTests.FakeResponse(400, {
                    "error": {"details": [{"errorMessages": [
                        "Unknown operation 'name' available ops are "
                        "'[set-alias-property, delete-alias, create, create-alias]'"]}]}})
            return CreateCollectionApiShapeTests.FakeResponse(200, {"responseHeader": {"status": 0}})

    def client_with(self, session):
        admin = client.SolrAdminClient("localhost")
        admin._session = session
        return admin

    def test_a_modern_solr_is_asked_once(self):
        session = self.FakeSession(reject_first=False)
        self.client_with(session).create_collection("c", configset="c")
        self.assertEqual(1, len(session.posts))
        self.assertEqual("c", session.posts[0]["name"])

    def test_an_older_solr_is_retried_with_the_command_envelope(self):
        session = self.FakeSession(reject_first=True)
        self.client_with(session).create_collection("c", configset="c", num_shards=2)
        self.assertEqual(2, len(session.posts))
        self.assertNotIn("create", session.posts[0])
        self.assertEqual(2, session.posts[1]["create"]["numShards"])

    def test_an_unrelated_400_is_not_retried(self):
        # Only "unknown operation" means Solr wanted a different shape; every
        # other 400 is a real failure and must surface as one.
        session = self.FakeSession(reject_first=False)

        def post(url, json=None, timeout=None):
            session.posts.append(json)
            return self.FakeResponse(400, {"error": {"msg": "Collection 'c' already exists"}})

        session.post = post
        with self.assertRaises(client.CollectionAlreadyExistsError):
            self.client_with(session).create_collection("c", configset="c")
        self.assertEqual(1, len(session.posts))
