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
