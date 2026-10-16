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
"""Retry policy.

The policy itself is the thing under test: infrastructure steps retry, the
benchmark never does. The second half of that is asserted in
``orchestrator_test.py``; this file covers the mechanism.
"""

import pytest

from solrorbit.tools.launchr import retry


def test_a_successful_call_is_not_retried():
    calls = []
    result = retry.with_retries(lambda: calls.append(1) or "ok", what="x", sleep=lambda _: None)
    assert result == "ok" and len(calls) == 1


def test_retries_until_it_succeeds():
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("transient")
        return "ok"

    assert retry.with_retries(flaky, what="x", sleep=lambda _: None) == "ok"
    assert attempts["n"] == 3


def test_gives_up_after_the_backoff_is_exhausted():
    attempts = {"n": 0}

    def always_fails():
        attempts["n"] += 1
        raise ConnectionError("permanent")

    with pytest.raises(ConnectionError):
        retry.with_retries(always_fails, what="x", backoff=(1, 2), sleep=lambda _: None)
    # len(backoff) + 1 attempts.
    assert attempts["n"] == 3


def test_reraises_the_original_exception_unwrapped():
    # The caller should see the real cause, not a retry wrapper.
    class Specific(RuntimeError):
        pass

    with pytest.raises(Specific, match="the real problem"):
        retry.with_retries(lambda: (_ for _ in ()).throw(Specific("the real problem")),
                           what="x", backoff=(), sleep=lambda _: None)


def test_waits_for_each_backoff_delay_in_order():
    waited = []

    def always_fails():
        raise ValueError("no")

    with pytest.raises(ValueError):
        retry.with_retries(always_fails, what="x", backoff=(1, 5, 15), sleep=waited.append)
    assert waited == [1, 5, 15]


def test_sleep_is_resolved_at_call_time(monkeypatch):
    # A default argument would capture time.sleep at import and silently ignore
    # a patch, which once made the whole suite hang on real backoff.
    slept = []
    monkeypatch.setattr(retry.time, "sleep", slept.append)

    def fail_once(state={"n": 0}):
        state["n"] += 1
        if state["n"] == 1:
            raise ValueError("once")
        return "ok"

    assert retry.with_retries(fail_once, what="x", backoff=(7,)) == "ok"
    assert slept == [7]


def test_empty_backoff_means_a_single_attempt():
    attempts = {"n": 0}

    def always_fails():
        attempts["n"] += 1
        raise ValueError("no")

    with pytest.raises(ValueError):
        retry.with_retries(always_fails, what="x", backoff=())
    assert attempts["n"] == 1


def test_the_documented_backoff_profiles():
    assert retry.INFRA_BACKOFF == (10.0, 30.0, 90.0)
    assert retry.STORAGE_BACKOFF == (1.0, 5.0, 15.0)
