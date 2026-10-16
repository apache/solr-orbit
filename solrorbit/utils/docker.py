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

"""Locating Docker Compose, which ships under two different names."""

import functools
import logging
import subprocess

from solrorbit import exceptions

#: Compose v2, a subcommand of the Docker CLI. The current product, and on most
#: hosts the only one present.
COMPOSE_V2 = ("docker", "compose")

#: Compose v1, a standalone binary. End of life since June 2023 and absent from
#: current CI images and Linux distributions, but still installed by older
#: Docker Desktop versions, so it remains worth falling back to.
COMPOSE_V1 = ("docker-compose",)

PROBE_TIMEOUT_SECONDS = 30

logger = logging.getLogger(__name__)


def _responds(command):
    """Whether ``command version`` runs and reports success.

    Both v1 and v2 implement ``version``, so one probe serves for either.
    """
    try:
        completed = subprocess.run([*command, "version"], capture_output=True,
                                   check=False, timeout=PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        # A missing binary raises FileNotFoundError rather than returning
        # non-zero, which is the whole reason this lookup exists.
        logger.debug("Docker Compose candidate %s is unavailable: %s", command, exc)
        return False
    return completed.returncode == 0


@functools.lru_cache(maxsize=1)
def compose_command():
    """The Docker Compose invocation available on this host, as a string.

    Prefers v2 and falls back to v1, so a host with either can run a benchmark.
    The result is cached: this shells out, and it is called once per Compose
    command built.

    :raises SystemSetupError: if neither is present.
    """
    for candidate in (COMPOSE_V2, COMPOSE_V1):
        if _responds(candidate):
            resolved = " ".join(candidate)
            logger.info("Using Docker Compose via [%s].", resolved)
            return resolved
    raise exceptions.SystemSetupError(
        "Docker Compose is required but was not found. Install Docker Compose v2, "
        "which ships with current Docker as the \"docker compose\" subcommand "
        "(the standalone \"docker-compose\" binary is v1 and reached end of life "
        "in June 2023)."
    )
