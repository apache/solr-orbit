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
"""Bounded retry with exponential backoff.

What retries and what does not is a deliberate policy, not a detail:

* ``provision``, ``deploy`` and storage writes retry -- cloud API timeouts,
  image pulls and transient 5xx are routine, and a retry changes nothing about
  what the benchmark measures.
* the **benchmark itself never retries**. A benchmark that failed is a fact
  about that cell. Re-running it silently would change what the data point
  means and would hide a flaky workload. ``launchr run --retry-failed`` is the
  explicit, human-triggered path for that.
"""

import logging
import time
from typing import Callable, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Backoff for infrastructure steps: provisioning and deployment.
INFRA_BACKOFF: tuple[float, ...] = (10.0, 30.0, 90.0)
#: Backoff for storage writes, which fail faster and recover faster.
STORAGE_BACKOFF: tuple[float, ...] = (1.0, 5.0, 15.0)


def with_retries(operation: Callable[[], T], *, what: str,
                 backoff: Sequence[float] = INFRA_BACKOFF,
                 sleep: Callable[[float], None] | None = None) -> T:
    """Call ``operation``, retrying after each delay in ``backoff``.

    ``len(backoff) + 1`` attempts in total. The last exception is re-raised
    unchanged, so the caller sees the real cause rather than a wrapper.

    ``sleep`` is resolved at call time rather than bound as a default, so
    ``time.sleep`` can be stubbed -- a default argument would capture the
    original function at import and silently ignore any patch.
    """
    pause = sleep if sleep is not None else time.sleep
    attempts = len(backoff) + 1
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - the caller decides what is fatal
            if attempt == attempts:
                logger.error("%s failed after %d attempts: %s", what, attempts, exc)
                raise
            delay = backoff[attempt - 1]
            logger.warning("%s failed (attempt %d/%d): %s -- retrying in %.0fs",
                           what, attempt, attempts, exc, delay)
            pause(delay)
    raise AssertionError("unreachable")  # pragma: no cover
