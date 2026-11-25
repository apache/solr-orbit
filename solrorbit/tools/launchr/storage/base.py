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
"""The storage backend contract.

One rule shapes the interface: **reports are immutable**. ``write`` refuses to
overwrite unless explicitly told to, because silently replacing a stored report
is both a data-integrity bug and nearly impossible to notice afterwards.
"""

from typing import ClassVar, Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Reads and writes launchr's reports, summaries and indexes.

    Paths are always relative, ``/``-separated, and identical across backends:
    the same layout on a local filesystem as in a cloud bucket.
    """

    #: Bumped when this Protocol changes incompatibly, so a plugin built against
    #: an older contract is rejected with a clear message instead of mis-binding.
    #:
    #: 2: ``write`` gained ``content_type``. Additive for callers, but an
    #: implementation written against version 1 raises on the new keyword, so
    #: this is a breaking change for backends rather than for their users.
    API_VERSION: ClassVar[int] = 2

    #: The name this backend is configured by, e.g. ``local``.
    name: ClassVar[str]

    def write(self, path: str, data: bytes, *, overwrite: bool = False,
              content_type: str | None = None) -> None:
        """Store ``data`` at ``path``. Raises :class:`~solrorbit.tools.launchr.errors.StorageError`
        if ``path`` exists and ``overwrite`` is false.

        ``content_type`` matters only where the store is also a web server: S3
        labels an object ``binary/octet-stream`` unless told otherwise, and a
        browser will download such an object rather than render it. A backend
        serving no HTTP traffic may ignore it.
        """
        ...

    def read(self, path: str) -> bytes:
        """Return the bytes at ``path``."""
        ...

    def list(self, prefix: str) -> list[str]:
        """Return every stored path under ``prefix``, sorted."""
        ...

    def exists(self, path: str) -> bool:
        """Whether anything is stored at ``path``."""
        ...
