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
"""Place a Solr version on the chart's x-axis.

launchr must not assume a clone of ``apache/solr`` is available -- it usually is
not, on a CI runner or a driver instance or most laptops. So git is one possible
source here, and not the default one.

Two sources ship today, tried in order:

``apache-releases``
    ``https://projects.apache.org/json/projects/solr.json`` lists every release
    with its announcement date. One unauthenticated GET answers a whole backfill
    matrix. Day precision.

``info-system``
    The build timestamp inside ``solr-impl-version``, which launchr already
    fetched to health-check the cluster. Needs no network beyond the cluster
    under test. Second precision. Primary for nightlies and SNAPSHOTs, and the
    universal fallback.

The chosen source and its precision travel into the report, because a release
plotted from an announcement date and a nightly plotted from a build timestamp
are not measuring the same clock.
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from solrorbit.tools.launchr.errors import VersionResolutionError
from solrorbit.tools.launchr.models import SystemInfo, VersionInfo

logger = logging.getLogger(__name__)

SOLR_PROJECT_JSON = "https://projects.apache.org/json/projects/solr.json"

DEFAULT_CACHE_PATH = "~/.launchr/version-cache.json"

#: A release version: exactly three dot-separated numbers and nothing else.
_RELEASE = re.compile(r"^\d+\.\d+\.\d+$")
#: A pre-release build: three numbers plus a qualifier, e.g. ``10.0.0-SNAPSHOT``.
_SNAPSHOT = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)[-.](?P<qualifier>.+)$")

KIND_RELEASE = "release"
KIND_SNAPSHOT = "snapshot"
KIND_UNKNOWN = "unknown"

SOURCE_APACHE_RELEASES = "apache-releases"
SOURCE_INFO_SYSTEM = "info-system"
SOURCE_EXPLICIT = "explicit"
#: When the container image was built. The last resort before giving up, and
#: in practice the only source a nightly has: Solr's own solr-impl-version on
#: a snapshot build reads "[snapshot build, details omitted]" and carries no
#: timestamp at all, so without this a nightly cannot be placed on the x-axis.
#: It is the build date of that image, which for a nightly is exactly the
#: question the chart is asking.
SOURCE_IMAGE = "container-image"

PRECISION_DAY = "day"
PRECISION_SECOND = "second"


def classify(version: str) -> str:
    """Return ``release``, ``snapshot``, or ``unknown`` for a version string."""
    value = version.strip()
    if _RELEASE.match(value):
        return KIND_RELEASE
    if _SNAPSHOT.match(value):
        return KIND_SNAPSHOT
    return KIND_UNKNOWN


def infer_branch(version: str, released_majors: set[int]) -> str | None:
    """Infer the Solr git branch a SNAPSHOT build came from.

    Releases have no branch -- they are points, not lines. For a SNAPSHOT the
    rule follows Solr's branching convention:

    ========================  ==========================================  =============
    Version                   Rule                                        Branch
    ========================  ==========================================  =============
    ``10.0.0-SNAPSHOT``       ``X.0.0`` and no ``X.*`` released yet       ``main``
    ``9.12.0-SNAPSHOT``       ``X.Y.0`` and some ``X.*`` was released     ``branch_9x``
    ``9.11.1-SNAPSHOT``       ``X.Y.Z`` with ``Z > 0``                    ``branch_9_11``
    ========================  ==========================================  =============

    It will be wrong exactly when the convention is broken -- a feature branch
    built as a SNAPSHOT, say -- which is what ``--branch`` is for.
    """
    match = _SNAPSHOT.match(version.strip())
    if not match:
        return None
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    if patch > 0:
        return f"branch_{major}_{minor}"
    if minor == 0 and major not in released_majors:
        return "main"
    return f"branch_{major}x"


# ---------------------------------------------------------------------------
# The Apache release list
# ---------------------------------------------------------------------------


@dataclass
class ReleaseIndex:
    """Release version -> announcement date, from ``solr.json``."""

    dates: dict[str, str]

    @property
    def majors(self) -> set[int]:
        majors = set()
        for version in self.dates:
            head = version.split(".", 1)[0]
            if head.isdigit():
                majors.add(int(head))
        return majors

    def date(self, version: str) -> datetime | None:
        raw = self.dates.get(version.strip())
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("Release list has an unparseable date %r for %s", raw, version)
            return None

    @classmethod
    def from_payload(cls, payload: dict) -> "ReleaseIndex":
        dates: dict[str, str] = {}
        for entry in payload.get("release") or []:
            revision = entry.get("revision")
            created = entry.get("created")
            if revision and created:
                dates[str(revision)] = str(created)
        return cls(dates=dates)

    def as_payload(self) -> dict:
        return {"release": [{"revision": v, "created": d} for v, d in sorted(self.dates.items())]}


class VersionCache:
    """A tiny JSON file caching the release list.

    Release dates never change once published, so there is no expiry. A cache
    that cannot be read or written is a warning, never an error: the whole point
    of the fallback chain is that launchr keeps working.
    """

    def __init__(self, path: str | os.PathLike | None = DEFAULT_CACHE_PATH):
        self.path = Path(os.path.expanduser(str(path))) if path else None

    def load(self) -> dict:
        if not self.path or not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ignoring unreadable version cache %s: %s", self.path, exc)
            return {}

    def store(self, data: dict) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write version cache %s: %s", self.path, exc)


def fetch_release_index(*, timeout: float = 15.0) -> ReleaseIndex:
    """Fetch the Apache release list. Raises on any network or parse failure."""
    response = requests.get(SOLR_PROJECT_JSON, timeout=timeout)
    response.raise_for_status()
    return ReleaseIndex.from_payload(response.json())


# ---------------------------------------------------------------------------
# The resolver chain
# ---------------------------------------------------------------------------


class VersionTimeline:
    """Resolves versions to x-axis positions, caching the release list.

    One instance per ``launchr run``: the release list is fetched at most once
    and reused for every cell, and a fetch failure degrades to the
    ``info-system`` fallback for the rest of the run rather than being retried
    per cell.
    """

    def __init__(self, cache: VersionCache | None = None, *, offline: bool = False):
        self._cache = cache if cache is not None else VersionCache()
        self._offline = offline
        self._index: ReleaseIndex | None = None
        self._index_attempted = False

    @property
    def release_index(self) -> ReleaseIndex:
        """The release list: from the network if possible, else from cache, else empty."""
        if self._index is not None:
            return self._index
        if self._index_attempted:
            return ReleaseIndex(dates={})
        self._index_attempted = True

        cached = self._cache.load()
        if not self._offline:
            try:
                index = fetch_release_index()
                if index.dates:
                    cached["releases"] = index.as_payload()
                    self._cache.store(cached)
                    self._index = index
                    logger.info("Fetched %d Solr release dates from projects.apache.org", len(index.dates))
                    return index
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not fetch the Solr release list (%s); "
                               "falling back to the cache and to build timestamps", exc)

        payload = cached.get("releases")
        if payload:
            self._index = ReleaseIndex.from_payload(payload)
            logger.info("Using %d cached Solr release dates", len(self._index.dates))
        else:
            self._index = ReleaseIndex(dates={})
        return self._index

    def resolve(self, version: str, system_info: SystemInfo | None = None, *,
                override_timestamp: datetime | None = None,
                override_branch: str | None = None,
                image_timestamp: datetime | None = None) -> VersionInfo:
        """Place ``version`` on the timeline, trying each source in turn."""
        kind = classify(version)
        commit = system_info.commit if system_info else None

        if override_branch:
            branch, branch_source = override_branch, SOURCE_EXPLICIT
        elif kind == KIND_RELEASE:
            branch, branch_source = None, None
        else:
            branch = infer_branch(version, self.release_index.majors)
            branch_source = "inferred" if branch else None

        if override_timestamp is not None:
            return VersionInfo(version=version, timestamp=_utc(override_timestamp), source=SOURCE_EXPLICIT,
                               precision=PRECISION_SECOND, kind=kind, commit=commit,
                               branch=branch, branch_source=branch_source)

        if kind == KIND_RELEASE:
            released = self.release_index.date(version)
            if released is not None:
                return VersionInfo(version=version, timestamp=released, source=SOURCE_APACHE_RELEASES,
                                   precision=PRECISION_DAY, kind=kind, commit=commit,
                                   branch=branch, branch_source=branch_source)
            logger.info("Release %s is not in the Apache release list; using the build timestamp", version)

        if system_info and system_info.build_timestamp:
            return VersionInfo(version=version, timestamp=system_info.build_timestamp, source=SOURCE_INFO_SYSTEM,
                               precision=PRECISION_SECOND, kind=kind, commit=commit,
                               branch=branch, branch_source=branch_source)

        if image_timestamp is not None:
            logger.info("Placing %s at the build date of its container image", version)
            return VersionInfo(version=version, timestamp=_utc(image_timestamp),
                               source=SOURCE_IMAGE, precision=PRECISION_SECOND, kind=kind, commit=commit,
                               branch=branch, branch_source=branch_source)

        detail = (
            f"the cluster's solr-impl-version carried no build timestamp "
            f"({system_info.solr_impl_version!r})"
            if system_info
            else "there was no live cluster to read a build timestamp from"
        )
        raise VersionResolutionError(
            f"Could not place Solr {version!r} on the timeline: it is not in the Apache release "
            f"list and {detail}, and no container image build date was available. "
            f"Pass --version-timestamp to set it explicitly."
        )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
