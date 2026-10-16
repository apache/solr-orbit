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

"""Reading every document of a collection for create-workload."""

import unittest.mock as mock
from unittest import TestCase

from solrorbit.client import SolrClient
from solrorbit.workload_generator import extractors


def _page(docs, next_cursor_mark):
    return mock.Mock(docs=docs, nextCursorMark=next_cursor_mark)


class CursorScanTests(TestCase):
    def test_pages_through_a_collection_with_the_data_client(self):
        client = SolrClient(host="localhost", port=8983)
        pages = [
            _page([{"id": "1", "_version_": 11}, {"id": "2", "_version_": 12}], "AoE2"),
            _page([{"id": "3", "_version_": 13}], "AoE3"),
            _page([], "AoE3"),
        ]
        with mock.patch.object(client, "search", side_effect=pages) as search:
            docs = list(extractors._cursor_scan(client, "geonames", batch_size=2))  # pylint: disable=protected-access

        self.assertEqual([{"id": "1"}, {"id": "2"}, {"id": "3"}], docs)
        self.assertEqual(["*", "AoE2", "AoE3"], [call.kwargs["cursorMark"] for call in search.call_args_list])
        for call in search.call_args_list:
            self.assertEqual(("geonames", "*:*"), call.args)
            self.assertEqual({"rows": 2, "sort": "id asc"}, {k: call.kwargs[k] for k in ("rows", "sort")})

    def test_stops_when_the_cursor_does_not_move(self):
        client = SolrClient(host="localhost", port=8983)
        with mock.patch.object(client, "search", return_value=_page([{"id": "1"}], "*")) as search:
            docs = list(extractors._cursor_scan(client, "geonames"))  # pylint: disable=protected-access

        self.assertEqual([{"id": "1"}], docs)
        search.assert_called_once()
