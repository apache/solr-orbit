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
"""Storage backends.

Phase 1 ships ``local`` only. The registry becomes Python entry points in the
phase that adds the second backend, with no change to this module's interface.
"""

from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.storage.base import StorageBackend
from solrorbit.tools.launchr.storage.local import LocalStorageBackend

REGISTRY: dict[str, type] = {
    LocalStorageBackend.name: LocalStorageBackend,
}

__all__ = ["StorageBackend", "LocalStorageBackend", "REGISTRY", "get_backend", "available"]


def available() -> list[str]:
    """Names of every registered storage backend."""
    return sorted(REGISTRY)


def get_backend(name: str, path: str) -> StorageBackend:
    """Instantiate a storage backend by name."""
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ConfigError(f"Unknown storage backend {name!r}. Available: {', '.join(available())}") from None
    return cls(path)
