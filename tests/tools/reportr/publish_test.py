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
"""Publishing a built site."""

import pytest

from solrorbit.tools.launchr.storage import LocalStorageBackend
from solrorbit.tools.reportr import publish as publish_module


@pytest.fixture
def site(tmp_path):
    """A minimal built site: shell, data, a nested asset."""
    root = tmp_path / "site-output"
    (root / "data").mkdir(parents=True)
    (root / "vendor").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "app.js").write_text("console.log(1)", encoding="utf-8")
    (root / "style.css").write_text("body{}", encoding="utf-8")
    (root / "data" / "index.json").write_text("{}", encoding="utf-8")
    (root / "vendor" / "echarts.min.js").write_text("/*!*/", encoding="utf-8")
    return root


class _RecordingBackend(LocalStorageBackend):
    """Local storage that remembers the content types it was handed."""

    def __init__(self, path):
        super().__init__(path)
        self.content_types: dict[str, str | None] = {}

    def write(self, path, data, *, overwrite=False, content_type=None):
        self.content_types[path] = content_type
        super().write(path, data, overwrite=overwrite, content_type=content_type)


class TestContentTypes:
    """S3 serves binary/octet-stream unless told, and a browser then downloads
    the page instead of rendering it. This table is load-bearing, not cosmetic."""

    @pytest.mark.parametrize("name,expected", [
        ("index.html", "text/html; charset=utf-8"),
        ("app.js", "text/javascript; charset=utf-8"),
        ("style.css", "text/css; charset=utf-8"),
        ("data.json", "application/json; charset=utf-8"),
        ("logo.svg", "image/svg+xml"),
        ("font.woff2", "font/woff2"),
    ])
    def test_known_extensions(self, tmp_path, name, expected):
        assert publish_module.content_type_for(tmp_path / name) == expected

    def test_javascript_is_never_text_plain(self, tmp_path):
        # Some hosts' /etc/mime.types say text/plain for .js, and a browser
        # with nosniff refuses to execute that. Hence the explicit table.
        assert "javascript" in publish_module.content_type_for(tmp_path / "app.js")

    def test_an_unknown_extension_falls_back(self, tmp_path):
        assert publish_module.content_type_for(tmp_path / "x.unknownext") == \
            publish_module.DEFAULT_CONTENT_TYPE


class TestPublish:
    def test_uploads_every_file_with_relative_paths(self, site, tmp_path):
        backend = _RecordingBackend(tmp_path / "dest")
        written = publish_module.publish(site, "unused", backend=backend)
        assert written == [
            "app.js", "data/index.json", "index.html", "style.css", "vendor/echarts.min.js",
        ]

    def test_nested_files_keep_their_structure(self, site, tmp_path):
        backend = _RecordingBackend(tmp_path / "dest")
        publish_module.publish(site, "unused", backend=backend)
        assert (backend.root / "vendor" / "echarts.min.js").exists()

    def test_each_file_carries_its_content_type(self, site, tmp_path):
        backend = _RecordingBackend(tmp_path / "dest")
        publish_module.publish(site, "unused", backend=backend)
        assert backend.content_types["index.html"] == "text/html; charset=utf-8"
        assert backend.content_types["data/index.json"] == "application/json; charset=utf-8"

    def test_republishing_overwrites(self, site, tmp_path):
        # A site is mutable in a way a stored report is not: the whole point of
        # a rebuild is to replace what is live.
        backend = _RecordingBackend(tmp_path / "dest")
        publish_module.publish(site, "unused", backend=backend)
        (site / "index.html").write_text("<!doctype html><title>v2</title>", encoding="utf-8")
        publish_module.publish(site, "unused", backend=backend)
        assert b"v2" in backend.read("index.html")

    def test_dry_run_writes_nothing(self, site, tmp_path):
        backend = _RecordingBackend(tmp_path / "dest")
        written = publish_module.publish(site, "unused", backend=backend, dry_run=True)
        assert written and not backend.content_types
        assert not (backend.root / "index.html").exists()

    def test_a_missing_site_says_to_build_first(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="reportr build"):
            publish_module.publish(tmp_path / "nope", "unused",
                                   backend=LocalStorageBackend(tmp_path / "d"))

    def test_an_empty_site_is_refused(self, tmp_path):
        (tmp_path / "empty").mkdir()
        with pytest.raises(FileNotFoundError, match="no files"):
            publish_module.publish(tmp_path / "empty", "unused",
                                   backend=LocalStorageBackend(tmp_path / "d"))


class TestEntryUrl:
    def test_names_index_html_because_there_is_no_default_document(self):
        # The REST endpoint serves no index document, so a bare prefix URL is
        # a 404 and the link has to be explicit.
        url = publish_module.entry_url("s3://solr-orbit/public", "eu-north-1")
        assert url == "https://solr-orbit.s3.eu-north-1.amazonaws.com/public/index.html"

    def test_a_bucket_root_needs_no_prefix_segment(self):
        url = publish_module.entry_url("s3://solr-orbit", "eu-north-1")
        assert url == "https://solr-orbit.s3.eu-north-1.amazonaws.com/index.html"

    def test_a_filesystem_destination_has_no_url(self):
        assert publish_module.entry_url("/srv/www") is None
