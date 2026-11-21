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
"""Exception hierarchy for launchr.

Every failure launchr raises deliberately is a :class:`LaunchrError`. The
orchestrator treats these as expected outcomes worth reporting; anything else
escaping a plugin is a bug and is logged with a traceback.
"""


class LaunchrError(Exception):
    """Base class for every error launchr raises deliberately."""


class ConfigError(LaunchrError):
    """The configuration is invalid, incomplete, or self-contradictory."""


class ProvisioningError(LaunchrError):
    """A provisioning strategy could not create or tear down infrastructure."""


class DeployError(LaunchrError):
    """A Solr install method could not bring Solr up, or Solr came up wrong.

    ``logs`` carries whatever the install method could read before it cleaned
    up, because a failed deploy leaves the orchestrator with no deployment to
    ask -- and that is exactly when a Solr log is wanted.
    """

    def __init__(self, message: str, *, logs: dict[str, bytes] | None = None):
        super().__init__(message)
        self.logs = logs or {}


class BenchmarkError(LaunchrError):
    """Solr Orbit ran but did not produce a usable result."""


class StorageError(LaunchrError):
    """A storage backend could not read or write."""


class VersionResolutionError(LaunchrError):
    """No resolver in the chain could place a version on the timeline."""
