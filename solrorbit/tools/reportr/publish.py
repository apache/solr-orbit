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
"""Upload a built site to wherever it is served from.

Separate from :mod:`~solrorbit.tools.reportr.builder` on purpose. A build is
pure -- reports in, a directory out -- and publishing is the one step that
changes something people can see. Keeping them apart means ``--serve`` shows
exactly what would be published, and a failed upload never leaves a
half-rendered site live.

**Publishing never deletes.** The obvious tidy-up -- remove what is in the
bucket but not in the build -- is wrong here, because launchr's own results
live under the same public prefix as the site. A prune that understood only
the site would delete the benchmark history on its first run. Stale
``reports/<run-id>.json`` files from a narrower rebuild are unreferenced by
``data/*.json`` and cost a few kilobytes, which is the cheaper mistake.
"""

import logging
import mimetypes
from pathlib import Path

from solrorbit.tools.launchr import retry
from solrorbit.tools.launchr.storage import StorageBackend, backend_for

logger = logging.getLogger(__name__)

#: Extension -> Content-Type. S3 labels an object ``binary/octet-stream``
#: unless told otherwise, and a browser handed that for ``index.html``
#: downloads it instead of rendering it -- so this table is what makes the
#: difference between a published site and a pile of files.
#:
#: Spelled out rather than left to :mod:`mimetypes`, whose answers depend on
#: the host's ``/etc/mime.types``: on some machines ``.js`` comes back as
#: ``text/plain``, which browsers refuse to execute under
#: ``X-Content-Type-Options: nosniff``.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/vnd.microsoft.icon",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
}

DEFAULT_CONTENT_TYPE = "application/octet-stream"


def content_type_for(path: Path) -> str:
    """The Content-Type to publish ``path`` under."""
    suffix = path.suffix.lower()
    if suffix in CONTENT_TYPES:
        return CONTENT_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or DEFAULT_CONTENT_TYPE


def publish(site_dir: Path, destination: str, *,
            backend: StorageBackend | None = None,
            options: dict | None = None,
            dry_run: bool = False) -> list[str]:
    """Upload every file under ``site_dir`` to ``destination``.

    Returns the storage paths written, relative to the destination root.
    ``destination`` is an ``s3://bucket/prefix`` URI or a filesystem path.
    """
    site_dir = Path(site_dir)
    if not site_dir.is_dir():
        raise FileNotFoundError(
            f"No site at {site_dir}. Run `reportr build` before publishing."
        )

    store = backend if backend is not None else backend_for(destination, options=options)
    files = sorted(p for p in site_dir.rglob("*") if p.is_file())
    if not files:
        raise FileNotFoundError(f"{site_dir} contains no files to publish")

    written: list[str] = []
    for path in files:
        # POSIX separators: a storage path is always "/"-separated, including
        # when this runs on Windows.
        relative = path.relative_to(site_dir).as_posix()
        if dry_run:
            written.append(relative)
            continue
        data = path.read_bytes()
        retry.with_retries(
            lambda relative=relative, data=data, path=path: store.write(
                relative, data, overwrite=True, content_type=content_type_for(path),
            ),
            what=f"publishing {relative}",
            backoff=retry.STORAGE_BACKOFF,
        )
        written.append(relative)

    verb = "Would publish" if dry_run else "Published"
    logger.info("%s %d file(s) to %s", verb, len(written), store.location)
    return written


def entry_url(destination: str, region: str | None = None) -> str | None:
    """A URL that opens the published site, when one can be derived.

    Only meaningful for ``s3://``. The REST endpoint is used rather than the
    S3 *website* endpoint because the website endpoint is HTTP-only, and a
    bucket policy requiring ``aws:SecureTransport`` -- the sane default --
    rejects it. The REST endpoint has no default-document behaviour, which is
    why ``index.html`` is named explicitly.
    """
    if not destination.startswith("s3://"):
        return None
    from solrorbit.tools.launchr.storage.s3 import parse_uri

    bucket, prefix = parse_uri(destination)
    host = f"{bucket}.s3.{region}.amazonaws.com" if region else f"{bucket}.s3.amazonaws.com"
    path = f"{prefix}/index.html" if prefix else "index.html"
    return f"https://{host}/{path}"
