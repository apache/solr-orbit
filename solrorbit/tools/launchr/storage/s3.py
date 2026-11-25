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
"""S3 storage.

Reproduces :class:`~solrorbit.tools.launchr.storage.local.LocalStorageBackend`'s
layout key for key, so the same ``runs/<workload>/<date>/<run-id>/results.json``
path addresses the same report whether it lives on a laptop or in a bucket.
That is what lets reportr build the same site from either.

``boto3`` rather than ``cloudpathlib``: boto3 is already a core dependency of
Solr Orbit, and the one thing this backend needs beyond a ``pathlib`` veneer --
a conditional put, so two concurrent sessions cannot silently overwrite each
other's reports -- is not something the ``pathlib`` API can express.

**Credentials are never read from launchr's configuration.** They come from the
ambient chain: environment, shared credentials file, instance role, or an OIDC
web identity. ``storage.options.profile`` names a *profile*, which is a pointer
to a credential rather than a credential.
"""

import logging
import re
import threading
from typing import Any, ClassVar
from urllib.parse import urlsplit

from solrorbit.tools.launchr.errors import ConfigError, StorageError

logger = logging.getLogger(__name__)

#: Options a caller may set under ``storage.options``. Anything else is a typo
#: worth failing on rather than ignoring.
KNOWN_OPTIONS = frozenset({"region", "profile", "endpoint_url"})

#: Error codes S3 returns when a conditional put loses its race, or when the
#: object simply is not there. Treated as "does not exist" / "already exists"
#: rather than as transport failures.
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})
_EXISTS_CODES = frozenset({"PreconditionFailed", "ConditionalRequestConflict"})


def parse_uri(uri: str) -> tuple[str, str]:
    """Split ``s3://bucket/prefix`` into ``(bucket, prefix)``.

    The prefix is normalised without leading or trailing slashes, so joining it
    to a relative storage path never produces an empty segment -- S3 happily
    stores a key containing ``//`` and then nothing can address it again.
    """
    parsed = urlsplit(uri)
    if parsed.scheme != "s3":
        raise ConfigError(f"An s3 storage path must start with 's3://', got {uri!r}")
    bucket = parsed.netloc
    if not bucket:
        raise ConfigError(f"No bucket in storage path {uri!r}. Expected 's3://bucket/prefix'.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]", bucket):
        raise ConfigError(f"{bucket!r} is not a valid S3 bucket name (in storage path {uri!r})")
    return bucket, parsed.path.strip("/")


class S3StorageBackend:
    """Stores reports under a prefix of an S3 bucket."""

    API_VERSION: ClassVar[int] = 2
    name: ClassVar[str] = "s3"

    def __init__(self, path: str, **options: Any):
        unknown = set(options) - KNOWN_OPTIONS
        if unknown:
            raise ConfigError(
                f"Unknown storage.options for the 's3' backend: {', '.join(sorted(unknown))}. "
                f"Known: {', '.join(sorted(KNOWN_OPTIONS))}."
            )
        self.bucket, self.prefix = parse_uri(path)
        self.region = options.get("region")
        self.profile = options.get("profile")
        self.endpoint_url = options.get("endpoint_url")
        # boto3 clients are not documented as thread-safe to *create*, and the
        # orchestrator runs profile groups concurrently. One lock around lazy
        # creation is cheaper than a client per call.
        self._lock = threading.Lock()
        self._client = None

    def __repr__(self) -> str:
        return f"S3StorageBackend({self.location!r})"

    @property
    def location(self) -> str:
        """A human-readable description of where this backend writes."""
        return f"s3://{self.bucket}/{self.prefix}" if self.prefix else f"s3://{self.bucket}"

    # -- client ------------------------------------------------------------

    @property
    def client(self):
        """The boto3 S3 client, created on first use.

        Lazy because constructing a client resolves credentials, and a
        ``launchr validate-config`` that only wants to print the resolved
        configuration should not fail on a machine with no AWS credentials.
        """
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = self._make_client()
        return self._client

    def _make_client(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - boto3 is a core dependency
            raise StorageError(
                "The 's3' storage backend needs boto3, which should be installed with Solr Orbit."
            ) from exc
        session_args = {}
        if self.profile:
            session_args["profile_name"] = self.profile
        if self.region:
            session_args["region_name"] = self.region
        try:
            session = boto3.session.Session(**session_args)
            return session.client("s3", endpoint_url=self.endpoint_url)
        except Exception as exc:
            raise StorageError(f"Could not create an S3 client for {self.location}: {exc}") from exc

    # -- paths -------------------------------------------------------------

    def _key(self, path: str) -> str:
        """Map a relative storage path to a bucket key, refusing escapes."""
        if not path or path.startswith("/"):
            raise StorageError(f"Storage paths must be relative, got {path!r}")
        if ".." in path.split("/"):
            raise StorageError(f"Storage path {path!r} escapes the storage root {self.location}")
        return f"{self.prefix}/{path}" if self.prefix else path

    def _relative(self, key: str) -> str:
        """Inverse of :meth:`_key`, for rendering listings."""
        if self.prefix and key.startswith(f"{self.prefix}/"):
            return key[len(self.prefix) + 1:]
        return key

    # -- the StorageBackend contract ---------------------------------------

    def write(self, path: str, data: bytes, *, overwrite: bool = False,
              content_type: str | None = None) -> None:
        key = self._key(path)
        extra: dict[str, Any] = {} if overwrite else {"IfNoneMatch": "*"}
        if content_type:
            extra["ContentType"] = content_type
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        except Exception as exc:
            if _code(exc) in _EXISTS_CODES:
                raise StorageError(
                    f"Refusing to overwrite {path!r}: stored reports are immutable. "
                    f"A re-run gets a new run id."
                ) from exc
            if not overwrite and _is_unsupported_conditional(exc):
                # An S3-compatible server that predates conditional writes.
                # Fall back to check-then-put, which is racy in exactly the way
                # the local backend is racy -- acceptable, and worth saying out
                # loud once rather than silently degrading.
                logger.warning(
                    "%s does not support conditional writes; falling back to a non-atomic "
                    "existence check. Concurrent sessions could overwrite each other.",
                    self.location,
                )
                if self.exists(path):
                    raise StorageError(
                        f"Refusing to overwrite {path!r}: stored reports are immutable. "
                        f"A re-run gets a new run id."
                    ) from exc
                extra.pop("IfNoneMatch", None)
                self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
            else:
                raise StorageError(f"Could not write {path!r} to {self.location}: {exc}") from exc
        logger.debug("Wrote %d bytes to s3://%s/%s", len(data), self.bucket, key)

    def read(self, path: str) -> bytes:
        key = self._key(path)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:
            raise StorageError(f"Could not read {path!r} from {self.location}: {exc}") from exc

    def list(self, prefix: str) -> list[str]:
        base = self._key(prefix) if prefix else self.prefix
        # A trailing slash keeps `runs/nyc` from matching `runs/nyc_taxis/...`;
        # an empty base lists the whole bucket, which is the documented meaning.
        if base and not base.endswith("/"):
            base += "/"
        found: list[str] = []
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=base):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    # Directory-marker objects and the local backend's temp
                    # files are not storage content.
                    if key.endswith("/") or key.endswith(".tmp"):
                        continue
                    found.append(self._relative(key))
        except Exception as exc:
            raise StorageError(f"Could not list {prefix!r} in {self.location}: {exc}") from exc
        return sorted(found)

    def exists(self, path: str) -> bool:
        key = self._key(path)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:
            if _code(exc) in _MISSING_CODES:
                return False
            raise StorageError(
                f"Could not check whether {path!r} exists in {self.location}: {exc}"
            ) from exc


def _code(exc: Exception) -> str:
    """Return the S3 error code of a botocore ClientError, or ``''``."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return ""
    return str(response.get("Error", {}).get("Code", ""))


def _is_unsupported_conditional(exc: Exception) -> bool:
    """Whether ``exc`` says this endpoint rejects ``IfNoneMatch`` outright.

    Distinguished from a lost race: ``PreconditionFailed`` means the conditional
    put worked and the object already existed, while these mean the server never
    understood the condition. Only the latter justifies the non-atomic fallback.
    """
    if _code(exc) in {"NotImplemented", "InvalidRequest", "InvalidArgument"}:
        return True
    # botocore rejects unknown parameters client-side, before any request.
    return isinstance(exc, (TypeError, ValueError)) and "IfNoneMatch" in str(exc)
