# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Download and verify the Apache RAT JAR.

Usage: python3 scripts/download-rat.py <version> <target_jar_path>

Downloads apache-rat-<version>-bin.tar.gz from the Apache mirror,
verifies its SHA-512 checksum, extracts the JAR, and writes it to
<target_jar_path>.
"""

import hashlib
import io
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

PRIMARY_URL = "https://downloads.apache.org/creadur"
ARCHIVE_URL = "https://archive.apache.org/dist/creadur"


def download(url: str) -> bytes:
    print(f"Downloading {url}", flush=True)
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def download_with_fallback(primary: str, archive: str) -> bytes:
    """Try the primary mirror; fall back to the archive mirror on 404."""
    try:
        return download(primary)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        print(f"Primary URL returned 404; trying archive mirror …", flush=True)
        return download(archive)


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <version> <target_jar_path>", file=sys.stderr)
        sys.exit(1)

    version, target = sys.argv[1], Path(sys.argv[2])
    tarball_name = f"apache-rat-{version}-bin.tar.gz"
    subpath = f"apache-rat-{version}/{tarball_name}"
    tar_url = f"{PRIMARY_URL}/{subpath}"
    sha_url = f"{tar_url}.sha512"
    tar_archive_url = f"{ARCHIVE_URL}/{subpath}"
    sha_archive_url = f"{tar_archive_url}.sha512"

    tarball = download_with_fallback(tar_url, tar_archive_url)
    expected_hex = download_with_fallback(sha_url, sha_archive_url).decode().strip()

    actual_hex = hashlib.sha512(tarball).hexdigest()
    if actual_hex != expected_hex:
        print(f"SHA-512 mismatch for {tarball_name}!", file=sys.stderr)
        print(f"  expected: {expected_hex}", file=sys.stderr)
        print(f"  actual:   {actual_hex}", file=sys.stderr)
        sys.exit(1)
    print(f"SHA-512 verified: {tarball_name}", flush=True)

    jar_member = f"apache-rat-{version}/apache-rat-{version}.jar"
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tf:
        member = tf.getmember(jar_member)
        jar_data = tf.extractfile(member).read()

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(jar_data)
    print(f"JAR written to {target}", flush=True)


if __name__ == "__main__":
    main()
