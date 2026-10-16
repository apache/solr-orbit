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
"""Local filesystem storage.

The development backend, and the reference implementation of the layout every
other backend reproduces. Writes are atomic within a directory: a temp file
followed by ``os.replace``, so a crashed run never leaves a half-written report
for reportr to trip over.
"""

import logging
import os
from pathlib import Path
from typing import ClassVar

from solrorbit.tools.launchr.errors import StorageError

logger = logging.getLogger(__name__)


class LocalStorageBackend:
    """Stores reports under a local directory."""

    API_VERSION: ClassVar[int] = 2
    name: ClassVar[str] = "local"

    def __init__(self, path: str | os.PathLike):
        self.root = Path(os.path.expanduser(str(path))).resolve()

    def __repr__(self) -> str:
        return f"LocalStorageBackend({str(self.root)!r})"

    @property
    def location(self) -> str:
        """A human-readable description of where this backend writes."""
        return str(self.root)

    def _resolve(self, path: str) -> Path:
        """Map a relative storage path to a filesystem path, refusing escapes."""
        if not path or path.startswith("/"):
            raise StorageError(f"Storage paths must be relative, got {path!r}")
        target = (self.root / path).resolve()
        if target != self.root and self.root not in target.parents:
            raise StorageError(f"Storage path {path!r} escapes the storage root {self.root}")
        return target

    def write(self, path: str, data: bytes, *, overwrite: bool = False,
              content_type: str | None = None) -> None:
        # content_type is accepted and ignored: a filesystem has no such
        # concept, and whatever serves this directory infers it from the
        # extension anyway.
        target = self._resolve(path)
        if target.exists() and not overwrite:
            raise StorageError(
                f"Refusing to overwrite {path!r}: stored reports are immutable. "
                f"A re-run gets a new run id."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        logger.debug("Wrote %d bytes to %s", len(data), target)

    def read(self, path: str) -> bytes:
        target = self._resolve(path)
        try:
            return target.read_bytes()
        except OSError as exc:
            raise StorageError(f"Could not read {path!r} from {self.root}: {exc}") from exc

    def list(self, prefix: str) -> list[str]:
        # Through _resolve like every other entry point, so an absolute or
        # ".." prefix cannot walk outside the storage root.
        base = self._resolve(prefix) if prefix else self.root
        if not base.exists():
            return []
        found = [p for p in base.rglob("*") if p.is_file() and not p.name.endswith(".tmp")]
        return sorted(str(p.relative_to(self.root)).replace(os.sep, "/") for p in found)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()
