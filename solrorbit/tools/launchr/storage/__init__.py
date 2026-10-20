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

``local`` and ``s3``. The registry becomes Python entry points in the phase
that adds a third, with no change to this module's interface.
"""

from typing import Any

from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.storage.base import StorageBackend
from solrorbit.tools.launchr.storage.local import LocalStorageBackend
from solrorbit.tools.launchr.storage.s3 import S3StorageBackend

REGISTRY: dict[str, type] = {
    LocalStorageBackend.name: LocalStorageBackend,
    S3StorageBackend.name: S3StorageBackend,
}

__all__ = [
    "StorageBackend", "LocalStorageBackend", "S3StorageBackend",
    "REGISTRY", "get_backend", "available", "backend_for",
]


def available() -> list[str]:
    """Names of every registered storage backend."""
    return sorted(REGISTRY)


def get_backend(name: str, path: str, options: dict[str, Any] | None = None) -> StorageBackend:
    """Instantiate a storage backend by name.

    ``options`` is the backend-specific ``storage.options`` block. The local
    backend takes none, so passing any is a configuration error rather than
    something to drop on the floor.
    """
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ConfigError(f"Unknown storage backend {name!r}. Available: {', '.join(available())}") from None
    if not options:
        return cls(path)
    try:
        return cls(path, **options)
    except TypeError as exc:
        raise ConfigError(
            f"The {name!r} storage backend does not accept storage.options "
            f"({', '.join(sorted(options))}): {exc}"
        ) from exc


def backend_for(path: str, name: str | None = None,
                options: dict[str, Any] | None = None) -> StorageBackend:
    """Instantiate the backend a path implies, or the one named.

    A ``s3://`` path is unambiguous, so ``reportr build --storage s3://bucket``
    needs no second flag saying what everyone can already see.
    """
    if name is None:
        name = "s3" if str(path).startswith("s3://") else "local"
    return get_backend(name, path, options)
