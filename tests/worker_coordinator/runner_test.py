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
import io
import unittest.mock as mock
from unittest import TestCase
from unittest.mock import MagicMock

import pytest
from osbenchmark import client, exceptions
from osbenchmark.worker_coordinator import runner
from tests import run_async, as_future


class _FakeOSClient:
    """Sentinel used as mock target in place of opensearchpy.OpenSearch (which was removed from this fork)."""


class BaseUnitTestContextManagerRunner:
    async def __aenter__(self):
        self.fp = io.StringIO("many\nlines\nin\na\nfile")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.fp.close()
        return False


class RegisterRunnerTests(TestCase):
    def tearDown(self):
        runner.remove_runner("unit_test")

    @run_async
    async def test_runner_function_should_be_wrapped(self):
        async def runner_function(*args):
            return args

        runner.register_runner(operation_type="unit_test", runner=runner_function, async_runner=True)
        returned_runner = runner.runner_for("unit_test")
        self.assertIsInstance(returned_runner, runner.NoCompletion)
        self.assertEqual("user-defined runner for [runner_function]", repr(returned_runner))
        self.assertEqual(("default_client", "param"),
                         await returned_runner({"default": "default_client", "other": "other_client"}, "param"))

    @run_async
    async def test_single_cluster_runner_class_with_context_manager_should_be_wrapped_with_context_manager_enabled(self):
        class UnitTestSingleClusterContextManagerRunner(BaseUnitTestContextManagerRunner):
            async def __call__(self, *args):
                return args

            def __str__(self):
                return "UnitTestSingleClusterContextManagerRunner"

        test_runner = UnitTestSingleClusterContextManagerRunner()
        runner.register_runner(operation_type="unit_test", runner=test_runner, async_runner=True)
        returned_runner = runner.runner_for("unit_test")
        self.assertIsInstance(returned_runner, runner.NoCompletion)
        self.assertEqual("user-defined context-manager enabled runner for [UnitTestSingleClusterContextManagerRunner]",
                         repr(returned_runner))
        # test that context_manager functionality gets preserved after wrapping
        async with returned_runner:
            self.assertEqual(("default_client", "param"),
                             await returned_runner({"default": "default_client", "other": "other_client"}, "param"))
        # check that the context manager interface of our inner runner has been respected.
        self.assertTrue(test_runner.fp.closed)

    @run_async
    async def test_multi_cluster_runner_class_with_context_manager_should_be_wrapped_with_context_manager_enabled(self):
        class UnitTestMultiClusterContextManagerRunner(BaseUnitTestContextManagerRunner):
            multi_cluster = True

            async def __call__(self, *args):
                return args

            def __str__(self):
                return "UnitTestMultiClusterContextManagerRunner"

        test_runner = UnitTestMultiClusterContextManagerRunner()
        runner.register_runner(operation_type="unit_test", runner=test_runner, async_runner=True)
        returned_runner = runner.runner_for("unit_test")
        self.assertIsInstance(returned_runner, runner.NoCompletion)
        self.assertEqual("user-defined context-manager enabled runner for [UnitTestMultiClusterContextManagerRunner]",
                         repr(returned_runner))

        # test that context_manager functionality gets preserved after wrapping
        all_clients = {"default": "default_client", "other": "other_client"}
        async with returned_runner:
            self.assertEqual((all_clients, "param1", "param2"), await returned_runner(all_clients, "param1", "param2"))
        # check that the context manager interface of our inner runner has been respected.
        self.assertTrue(test_runner.fp.closed)

    @run_async
    async def test_single_cluster_runner_class_should_be_wrapped(self):
        class UnitTestSingleClusterRunner:
            async def __call__(self, *args):
                return args

            def __str__(self):
                return "UnitTestSingleClusterRunner"

        test_runner = UnitTestSingleClusterRunner()
        runner.register_runner(operation_type="unit_test", runner=test_runner, async_runner=True)
        returned_runner = runner.runner_for("unit_test")
        self.assertIsInstance(returned_runner, runner.NoCompletion)
        self.assertEqual("user-defined runner for [UnitTestSingleClusterRunner]", repr(returned_runner))
        self.assertEqual(("default_client", "param"),
                         await returned_runner({"default": "default_client", "other": "other_client"}, "param"))

    @run_async
    async def test_multi_cluster_runner_class_should_be_wrapped(self):
        class UnitTestMultiClusterRunner:
            multi_cluster = True

            async def __call__(self, *args):
                return args

            def __str__(self):
                return "UnitTestMultiClusterRunner"

        test_runner = UnitTestMultiClusterRunner()
        runner.register_runner(operation_type="unit_test", runner=test_runner, async_runner=True)
        returned_runner = runner.runner_for("unit_test")
        self.assertIsInstance(returned_runner, runner.NoCompletion)
        self.assertEqual("user-defined runner for [UnitTestMultiClusterRunner]", repr(returned_runner))
        all_clients = {"default": "default_client", "other": "other_client"}
        self.assertEqual((all_clients, "some_param"), await returned_runner(all_clients, "some_param"))


class AssertingRunnerTests(TestCase):
    def setUp(self):
        runner.enable_assertions(True)

    def tearDown(self):
        runner.enable_assertions(False)

    @run_async
    async def test_asserts_equal_succeeds(self):
        opensearch = None
        response = {
            "hits": {
                "hits": {
                    "value": 5,
                    "relation": "eq"
                }
            }
        }
        delegate = mock.MagicMock()
        delegate.return_value = as_future(response)
        r = runner.AssertingRunner(delegate)
        async with r:
            final_response = await r(opensearch, {
                "name": "test-task",
                "assertions": [
                    {
                        "property": "hits.hits.value",
                        "condition": "==",
                        "value": 5
                    },
                    {
                        "property": "hits.hits.relation",
                        "condition": "==",
                        "value": "eq"
                    }
                ]
            })

        self.assertEqual(response, final_response)

    @run_async
    async def test_asserts_equal_fails(self):
        opensearch =  None
        response = {
            "hits": {
                "hits": {
                    "value": 10000,
                    "relation": "gte"
                }
            }
        }
        delegate = mock.MagicMock()
        delegate.return_value = as_future(response)
        r = runner.AssertingRunner(delegate)
        with self.assertRaisesRegex(exceptions.BenchmarkTaskAssertionError,
                                    r"Expected \[hits.hits.relation\] in \[test-task\] to be == \[eq\] but was \[gte\]."):
            async with r:
                await r(opensearch, {
                    "name": "test-task",
                    "assertions": [
                        {
                            "property": "hits.hits.value",
                            "condition": "==",
                            "value": 10000
                        },
                        {
                            "property": "hits.hits.relation",
                            "condition": "==",
                            "value": "eq"
                        }
                    ]
                })

    @run_async
    async def test_skips_asserts_for_non_dicts(self):
        opensearch = None
        response = (1, "ops")
        delegate = mock.MagicMock()
        delegate.return_value = as_future(response)
        r = runner.AssertingRunner(delegate)
        async with r:
            final_response = await r(opensearch, {
                "name": "test-task",
                "assertions": [
                    {
                        "property": "hits.hits.value",
                        "condition": "==",
                        "value": 5
                    }
                ]
            })
        # still passes response as is
        self.assertEqual(response, final_response)

    def test_predicates(self):
        r = runner.AssertingRunner(delegate=None)
        self.assertEqual(5, len(r.predicates))

        predicate_success = {
            # predicate: (expected, actual)
            ">": (5, 10),
            ">=": (5, 5),
            "<": (5, 4),
            "<=": (5, 5),
            "==": (5, 5),
        }

        for predicate, vals in predicate_success.items():
            expected, actual = vals
            self.assertTrue(r.predicates[predicate](expected, actual),
                            f"Expected [{expected} {predicate} {actual}] to succeed.")

        predicate_fail = {
            # predicate: (expected, actual)
            ">": (5, 5),
            ">=": (5, 4),
            "<": (5, 5),
            "<=": (5, 6),
            "==": (5, 6),
        }

        for predicate, vals in predicate_fail.items():
            expected, actual = vals
            self.assertFalse(r.predicates[predicate](expected, actual),
                             f"Expected [{expected} {predicate} {actual}] to fail.")


class RawRequestRunnerTests(TestCase):
    @run_async
    async def test_get_request(self):
        mock_sc = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_sc.raw_request.return_value = mock_resp

        r = runner.RawRequest()
        result = await r(mock_sc, {"method": "GET", "path": "/api/node/system"})

        mock_sc.raw_request.assert_called_once_with("GET", "/api/node/system", None, {})
        self.assertEqual(200, result["http-status"])
        self.assertEqual(1, result["weight"])
        self.assertEqual("ops", result["unit"])

    @run_async
    async def test_post_with_body(self):
        mock_sc = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_sc.raw_request.return_value = mock_resp

        body = {"query": "*:*"}
        r = runner.RawRequest()
        result = await r(mock_sc, {"method": "POST", "path": "/solr/test/query", "body": body})

        mock_sc.raw_request.assert_called_once_with("POST", "/solr/test/query", body, {})
        self.assertEqual(200, result["http-status"])

    @run_async
    async def test_default_method_is_get(self):
        mock_sc = MagicMock()
        mock_sc.raw_request.return_value = MagicMock(status_code=200)

        r = runner.RawRequest()
        await r(mock_sc, {"path": "/api/cores"})

        mock_sc.raw_request.assert_called_once_with("GET", "/api/cores", None, {})

    @run_async
    async def test_custom_headers(self):
        mock_sc = MagicMock()
        mock_sc.raw_request.return_value = MagicMock(status_code=200)

        headers = {"Accept": "application/json"}
        r = runner.RawRequest()
        await r(mock_sc, {"path": "/api/node/system", "headers": headers})

        mock_sc.raw_request.assert_called_once_with("GET", "/api/node/system", None, headers)


class SleepTests(TestCase):
    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    # To avoid real sleeps in unit tests
    @mock.patch("asyncio.sleep", return_value=as_future())
    @run_async
    async def test_missing_parameter(self, sleep, on_client_request_start, on_client_request_end, opensearch):
        r = runner.Sleep()
        with self.assertRaisesRegex(exceptions.DataError,
                                    "Parameter source for operation 'sleep' did not provide the mandatory parameter "
                                    "'duration'. Add it to your parameter source and try again."):
            await r(opensearch, params={})

        self.assertEqual(0, opensearch.call_count)
        self.assertEqual(0, opensearch.on_request_start.call_count)
        self.assertEqual(0, opensearch.on_request_end.call_count)
        self.assertEqual(1, on_client_request_start.call_count)
        self.assertEqual(1, on_client_request_end.call_count)
        self.assertEqual(0, sleep.call_count)

    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    # To avoid real sleeps in unit tests
    @mock.patch("asyncio.sleep", return_value=as_future())
    @run_async
    async def test_sleep(self, sleep, on_client_request_start, on_client_request_end, opensearch):
        r = runner.Sleep()
        await r(opensearch, params={"duration": 4.3})

        self.assertEqual(0, opensearch.call_count)
        self.assertEqual(1, opensearch.on_request_start.call_count)
        self.assertEqual(1, opensearch.on_request_end.call_count)
        self.assertEqual(1, on_client_request_start.call_count)
        self.assertEqual(1, on_client_request_end.call_count)
        sleep.assert_called_once_with(4.3)












class CompositeContextTests(TestCase):
    def test_cannot_be_used_outside_of_composite(self):
        with self.assertRaises(exceptions.BenchmarkAssertionError) as ctx:
            runner.CompositeContext.put("test", 1)

        self.assertEqual("This operation is only allowed inside a composite operation.", ctx.exception.args[0])

    @run_async
    async def test_put_get_and_remove(self):
        async with runner.CompositeContext():
            runner.CompositeContext.put("test", 1)
            runner.CompositeContext.put("don't clear this key", 1)
            self.assertEqual(runner.CompositeContext.get("test"), 1)
            runner.CompositeContext.remove("test")

        # context is cleared properly
        async with runner.CompositeContext():
            with self.assertRaises(KeyError) as ctx:
                runner.CompositeContext.get("don't clear this key")
            self.assertEqual("Unknown property [don't clear this key]. Currently recognized properties are [].",
                             ctx.exception.args[0])

    @run_async
    async def test_fails_to_read_unknown_key(self):
        async with runner.CompositeContext():
            with self.assertRaises(KeyError) as ctx:
                runner.CompositeContext.put("test", 1)
                runner.CompositeContext.get("unknown")
            self.assertEqual("Unknown property [unknown]. Currently recognized properties are [test].",
                             ctx.exception.args[0])

    @run_async
    async def test_fails_to_remove_unknown_key(self):
        async with runner.CompositeContext():
            with self.assertRaises(KeyError) as ctx:
                runner.CompositeContext.put("test", 1)
                runner.CompositeContext.remove("unknown")
            self.assertEqual("Unknown property [unknown]. Currently recognized properties are [test].",
                             ctx.exception.args[0])


class CompositeTests(TestCase):
    class CounterRunner:
        def __init__(self):
            self.max_value = 0
            self.current = 0

        async def __aenter__(self):
            self.current += 1
            return self

        async def __call__(self, opensearch, params):
            self.max_value = max(self.max_value, self.current)
            # wait for a short moment to ensure overlap
            await asyncio.sleep(0.1)

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.current -= 1
            return False

    class CallRecorderRunner:
        def __init__(self):
            self.calls = []

        async def __call__(self, opensearch, params):
            self.calls.append(params["name"])
            # wait for a short moment to ensure overlap
            await asyncio.sleep(0.1)

    def setUp(self):
        runner.register_default_runners()
        self.counter_runner = CompositeTests.CounterRunner()
        self.call_recorder_runner = CompositeTests.CallRecorderRunner()
        runner.register_runner("counter", self.counter_runner, async_runner=True)
        runner.register_runner("call-recorder", self.call_recorder_runner, async_runner=True)
        runner.enable_assertions(True)

    def tearDown(self):
        runner.enable_assertions(False)
        runner.remove_runner("counter")
        runner.remove_runner("call-recorder")

    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @mock.patch('osbenchmark.client.RequestContextHolder.new_request_context')
    @run_async
    async def test_runs_tasks_in_specified_order(self, opensearch, on_client_request_start, on_client_request_end, new_request_context):
        opensearch.transport.perform_request.return_value = as_future()

        params = {
            "requests": [
                {
                    "name": "initial-call",
                    "operation-type": "call-recorder",
                },
                {
                    "stream": [
                        {
                            "name": "stream-a",
                            "operation-type": "call-recorder",
                        }
                    ]
                },
                {
                    "stream": [
                        {
                            "name": "stream-b",
                            "operation-type": "call-recorder",
                        }
                    ]
                },
                {
                    "name": "call-after-stream-ab",
                    "operation-type": "call-recorder",
                },
                {
                    "stream": [
                        {
                            "name": "stream-c",
                            "operation-type": "call-recorder",
                        }
                    ]
                },
                {
                    "stream": [
                        {
                            "name": "stream-d",
                            "operation-type": "call-recorder",
                        }
                    ]
                },
                {
                    "name": "call-after-stream-cd",
                    "operation-type": "call-recorder",
                },

            ]
        }

        r = runner.Composite()
        r.supported_op_types = ["call-recorder"]
        await r(opensearch, params)

        self.assertEqual([
            "initial-call",
            # concurrent
            "stream-a", "stream-b",
            "call-after-stream-ab",
            # concurrent
            "stream-c", "stream-d",
            "call-after-stream-cd"
        ], self.call_recorder_runner.calls)

    @pytest.mark.skip(reason="latency is system-dependent")
    @run_async
    async def test_adds_request_timings(self):
        # We only need the request context holder functionality but not any calls to Elasticsearch.
        # Therefore, we can use the request context holder as a substitute and get proper timing info.
        opensearch = client.RequestContextHolder()

        params = {
            "requests": [
                {
                    "name": "initial-call",
                    "operation-type": "sleep",
                    "duration": 0.1
                },
                {
                    "stream": [
                        {
                            "name": "stream-a",
                            "operation-type": "sleep",
                            "duration": 0.2
                        }
                    ]
                },
                {
                    "stream": [
                        {
                            "name": "stream-b",
                            "operation-type": "sleep",
                            "duration": 0.1
                        }
                    ]
                }
            ]
        }

        r = runner.Composite()
        response = await r(opensearch, params)

        self.assertEqual(1, response["weight"])
        self.assertEqual("ops", response["unit"])
        timings = response["dependent_timing"]
        self.assertEqual(3, len(timings))

        self.assertEqual("initial-call", timings[0]["operation"])
        self.assertAlmostEqual(0.1, timings[0]["service_time"], delta=0.05)

        self.assertEqual("stream-a", timings[1]["operation"])
        self.assertAlmostEqual(0.2, timings[1]["service_time"], delta=0.05)

        self.assertEqual("stream-b", timings[2]["operation"])
        self.assertAlmostEqual(0.1, timings[2]["service_time"], delta=0.05)

        # common properties
        for timing in timings:
            self.assertEqual("sleep", timing["operation-type"])
            self.assertIn("absolute_time", timing)
            self.assertIn("request_start", timing)
            self.assertIn("request_end", timing)
            self.assertGreater(timing["request_end"], timing["request_start"])

    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @run_async
    async def test_limits_connections(self, opensearch, on_client_request_start, on_client_request_end):
        params = {
            "max-connections": 2,
            "requests": [
                {
                    "stream": [
                        {
                            "operation-type": "counter"
                        }
                    ]
                },
                {
                    "stream": [
                        {
                            "operation-type": "counter"
                        }

                    ]
                },
                {
                    "stream": [
                        {
                            "operation-type": "counter"
                        }
                    ]
                }
            ]
        }

        r = runner.Composite()
        r.supported_op_types = ["counter"]
        await r(opensearch, params)

        # composite runner should limit to two concurrent connections
        self.assertEqual(2, self.counter_runner.max_value)

    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @run_async
    async def test_rejects_invalid_stream(self, opensearch, on_client_request_start, on_client_request_end):
        # params contains a "streams" property (plural) but it should be "stream" (singular)
        params = {
            "max-connections": 2,
            "requests": [
                {
                    "stream": [
                        {
                            "operation-type": "counter"
                        }
                    ]
                },
                {
                    "streams": [
                        {
                            "operation-type": "counter"
                        }

                    ]
                }
            ]
        }

        r = runner.Composite()
        with self.assertRaises(exceptions.BenchmarkAssertionError) as ctx:
            await r(opensearch, params)

        self.assertEqual("Requests structure must contain [stream] or [operation-type].", ctx.exception.args[0])

    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @run_async
    async def test_rejects_unsupported_operations(self, opensearch, on_client_request_start, on_client_request_end):
        params = {
            "requests": [
                {
                    "stream": [
                        {
                            "operation-type": "bulk"
                        }
                    ]
                }
            ]
        }

        r = runner.Composite()
        with self.assertRaises(exceptions.BenchmarkAssertionError) as ctx:
            await r(opensearch, params)

        self.assertIn("Unsupported operation-type [bulk].", ctx.exception.args[0])


class RequestTimingTests(TestCase):
    class StaticRequestTiming:
        def __init__(self, task_start):
            self.task_start = task_start
            self.current_request_start = self.task_start

        async def __aenter__(self):
            # pretend time advances on each request
            self.current_request_start += 5
            return self

        @property
        def request_start(self):
            return self.current_request_start

        @property
        def request_end(self):
            return self.current_request_start + 0.1

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return False

    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @run_async
    async def test_merges_timing_info(self, opensearch, on_client_request_start, on_client_request_end):
        multi_cluster_client = {"default": opensearch}
        opensearch.new_request_context.return_value = RequestTimingTests.StaticRequestTiming(task_start=2)

        delegate = mock.Mock(return_value=as_future({
            "weight": 5,
            "unit": "ops",
            "success": True
        }))
        params = {
            "name": "unit-test-operation",
            "operation-type": "test-op"
        }
        timer = runner.RequestTiming(delegate)

        response = await timer(multi_cluster_client, params)

        self.assertEqual(5, response["weight"])
        self.assertEqual("ops", response["unit"])
        self.assertTrue(response["success"])
        self.assertIn("dependent_timing", response)
        timing = response["dependent_timing"]
        self.assertEqual("unit-test-operation", timing["operation"])
        self.assertEqual("test-op", timing["operation-type"])
        self.assertIsNotNone(timing["absolute_time"])
        self.assertEqual(7, timing["request_start"])
        self.assertEqual(7.1, timing["request_end"])
        self.assertAlmostEqual(0.1, timing["service_time"])

        delegate.assert_called_once_with(multi_cluster_client, params)

    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_end')
    @mock.patch('osbenchmark.client.RequestContextHolder.on_client_request_start')
    @mock.patch("tests.worker_coordinator.runner_test._FakeOSClient")
    @run_async
    async def test_creates_new_timing_info(self, opensearch, on_client_request_start, on_client_request_end):
        multi_cluster_client = {"default": opensearch}
        opensearch.new_request_context.return_value = RequestTimingTests.StaticRequestTiming(task_start=2)

        # a simple runner without a return value
        delegate = mock.Mock(return_value=as_future())
        params = {
            "name": "unit-test-operation",
            "operation-type": "test-op"
        }
        timer = runner.RequestTiming(delegate)

        response = await timer(multi_cluster_client, params)

        # defaults added by the timing runner
        self.assertEqual(1, response["weight"])
        self.assertEqual("ops", response["unit"])
        self.assertTrue(response["success"])

        self.assertIn("dependent_timing", response)
        timing = response["dependent_timing"]
        self.assertEqual("unit-test-operation", timing["operation"])
        self.assertEqual("test-op", timing["operation-type"])
        self.assertIsNotNone(timing["absolute_time"])
        self.assertEqual(7, timing["request_start"])
        self.assertEqual(7.1, timing["request_end"])
        self.assertAlmostEqual(0.1, timing["service_time"])

        delegate.assert_called_once_with(multi_cluster_client, params)


class RetryTests(TestCase):
    @run_async
    async def test_is_transparent_on_success_when_no_retries(self):
        delegate = mock.Mock(return_value=as_future())
        opensearch = None
        params = {
            # no retries
        }
        retrier = runner.Retry(delegate)

        await retrier(opensearch, params)

        delegate.assert_called_once_with(opensearch, params)

    @run_async
    async def test_is_transparent_on_exception_when_no_retries(self):
        delegate = mock.Mock(side_effect=as_future(exception=exceptions.BenchmarkConnectionError("no route to host")))
        opensearch = None
        params = {
            # no retries
        }
        retrier = runner.Retry(delegate)

        with self.assertRaises(exceptions.BenchmarkConnectionError):
            await retrier(opensearch, params)

        delegate.assert_called_once_with(opensearch, params)

    @run_async
    async def test_is_transparent_on_application_error_when_no_retries(self):
        original_return_value = {"weight": 1, "unit": "ops", "success": False}

        delegate = mock.Mock(return_value=as_future(original_return_value))
        opensearch = None
        params = {
            # no retries
        }
        retrier = runner.Retry(delegate)

        result = await retrier(opensearch, params)

        self.assertEqual(original_return_value, result)
        delegate.assert_called_once_with(opensearch, params)

    @run_async
    async def test_is_does_not_retry_on_success(self):
        delegate = mock.Mock(return_value=as_future())
        opensearch = None
        params = {
            "retries": 3,
            "retry-wait-period": 0.1,
            "retry-on-timeout": True,
            "retry-on-error": True
        }
        retrier = runner.Retry(delegate)

        await retrier(opensearch, params)

        delegate.assert_called_once_with(opensearch, params)

    @run_async
    async def test_retries_on_timeout_if_wanted_and_raises_if_no_recovery(self):
        delegate = mock.Mock(side_effect=[
            as_future(exception=exceptions.BenchmarkConnectionError("no route to host")),
            as_future(exception=exceptions.BenchmarkConnectionError("no route to host")),
            as_future(exception=exceptions.BenchmarkConnectionError("no route to host")),
            as_future(exception=exceptions.BenchmarkConnectionError("no route to host"))
        ])
        opensearch = None
        params = {
            "retries": 3,
            "retry-wait-period": 0.01,
            "retry-on-timeout": True,
            "retry-on-error": True
        }
        retrier = runner.Retry(delegate)

        with self.assertRaises(exceptions.BenchmarkConnectionError):
            await retrier(opensearch, params)

        delegate.assert_has_calls([
            mock.call(opensearch, params),
            mock.call(opensearch, params),
            mock.call(opensearch, params)
        ])

    @run_async
    async def test_retries_on_timeout_if_wanted_and_returns_first_call(self):
        failed_return_value = {"weight": 1, "unit": "ops", "success": False}

        delegate = mock.Mock(side_effect=[
            as_future(exception=exceptions.BenchmarkConnectionError("no route to host")),
            as_future(failed_return_value)
        ])
        opensearch = None
        params = {
            "retries": 3,
            "retry-wait-period": 0.01,
            "retry-on-timeout": True,
            "retry-on-error": False
        }
        retrier = runner.Retry(delegate)

        result = await retrier(opensearch, params)
        self.assertEqual(failed_return_value, result)

        delegate.assert_has_calls([
            # has returned a connection error
            mock.call(opensearch, params),
            # has returned normally
            mock.call(opensearch, params)
        ])

    @run_async
    async def test_retries_mixed_timeout_and_application_errors(self):
        connection_error = exceptions.BenchmarkConnectionError("no route to host")
        failed_return_value = {"weight": 1, "unit": "ops", "success": False}
        success_return_value = {"weight": 1, "unit": "ops", "success": False}

        delegate = mock.Mock(side_effect=[
            as_future(exception=connection_error),
            as_future(failed_return_value),
            as_future(exception=connection_error),
            as_future(exception=connection_error),
            as_future(failed_return_value),
            as_future(success_return_value)
        ])
        opensearch = None
        params = {
            # we try exactly as often as there are errors to also test the semantics of "retry".
            "retries": 5,
            "retry-wait-period": 0.01,
            "retry-on-timeout": True,
            "retry-on-error": True
        }
        retrier = runner.Retry(delegate)

        result = await retrier(opensearch, params)
        self.assertEqual(success_return_value, result)

        delegate.assert_has_calls([
            # connection error
            mock.call(opensearch, params),
            # application error
            mock.call(opensearch, params),
            # connection error
            mock.call(opensearch, params),
            # connection error
            mock.call(opensearch, params),
            # application error
            mock.call(opensearch, params),
            # success
            mock.call(opensearch, params)
        ])

    @run_async
    async def test_does_not_retry_on_timeout_if_not_wanted(self):
        delegate = mock.Mock(side_effect=as_future(exception=exceptions.BenchmarkConnectionTimeout("timed out")))
        opensearch = None
        params = {
            "retries": 3,
            "retry-wait-period": 0.01,
            "retry-on-timeout": False,
            "retry-on-error": True
        }
        retrier = runner.Retry(delegate)

        with self.assertRaises(exceptions.BenchmarkConnectionTimeout):
            await retrier(opensearch, params)

        delegate.assert_called_once_with(opensearch, params)

    @run_async
    async def test_retries_on_application_error_if_wanted(self):
        failed_return_value = {"weight": 1, "unit": "ops", "success": False}
        success_return_value = {"weight": 1, "unit": "ops", "success": True}

        delegate = mock.Mock(side_effect=[
            as_future(failed_return_value),
            as_future(success_return_value)
        ])
        opensearch = None
        params = {
            "retries": 3,
            "retry-wait-period": 0.01,
            "retry-on-timeout": False,
            "retry-on-error": True
        }
        retrier = runner.Retry(delegate)

        result = await retrier(opensearch, params)

        self.assertEqual(success_return_value, result)

        delegate.assert_has_calls([
            mock.call(opensearch, params),
            # one retry
            mock.call(opensearch, params)
        ])

    @run_async
    async def test_does_not_retry_on_application_error_if_not_wanted(self):
        failed_return_value = {"weight": 1, "unit": "ops", "success": False}

        delegate = mock.Mock(return_value=as_future(failed_return_value))
        opensearch = None
        params = {
            "retries": 3,
            "retry-wait-period": 0.01,
            "retry-on-timeout": True,
            "retry-on-error": False
        }
        retrier = runner.Retry(delegate)

        result = await retrier(opensearch, params)

        self.assertEqual(failed_return_value, result)

        delegate.assert_called_once_with(opensearch, params)

    @run_async
    async def test_assumes_success_if_runner_returns_non_dict(self):
        delegate = mock.Mock(return_value=as_future(result=(1, "ops")))
        opensearch = None
        params = {
            "retries": 3,
            "retry-wait-period": 0.01,
            "retry-on-timeout": True,
            "retry-on-error": True
        }
        retrier = runner.Retry(delegate)

        result = await retrier(opensearch, params)

        self.assertEqual((1, "ops"), result)

        delegate.assert_called_once_with(opensearch, params)

    @run_async
    async def test_retries_until_success(self):
        failure_count = 5

        failed_return_value = {"weight": 1, "unit": "ops", "success": False}
        success_return_value = {"weight": 1, "unit": "ops", "success": True}

        responses = []
        responses += failure_count * [as_future(failed_return_value)]
        responses += [as_future(success_return_value)]

        delegate = mock.Mock(side_effect=responses)
        opensearch = None
        params = {
            "retry-until-success": True,
            "retry-wait-period": 0.01
        }
        retrier = runner.Retry(delegate)

        result = await retrier(opensearch, params)

        self.assertEqual(success_return_value, result)

        delegate.assert_has_calls([mock.call(opensearch, params) for _ in range(failure_count + 1)])


class RemovePrefixTests(TestCase):
    def test_remove_matching_prefix(self):
        # remove_prefix was removed (Python 3.8 shim); str.removeprefix is the built-in
        suffix = "index-20201117".removeprefix("index")
        self.assertEqual(suffix, "-20201117")

    def test_prefix_doesnt_exit(self):
        index_name = "index-20201117"
        suffix = index_name.removeprefix("unrelatedprefix")
        self.assertEqual(suffix, index_name)
