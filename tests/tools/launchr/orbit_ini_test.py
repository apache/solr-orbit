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
"""Rendering Solr Orbit's benchmark.ini for a remote driver."""

import configparser

import pytest

from solrorbit.tools.launchr import orbit_ini
from solrorbit.tools.launchr.errors import ConfigError

HOME = "/home/ec2-user"


def parse(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read_string(text)
    return parser


class TestDefaultsComeFromSolrOrbit:
    """The bundled template is the source of defaults, not this module.

    Re-stating Solr Orbit's defaults here would mean watching them drift; a
    key added upstream should reach the driver without launchr knowing it
    exists.
    """

    def test_the_bundled_template_is_found(self):
        assert orbit_ini.template_path().is_file()

    def test_untouched_sections_survive(self):
        cfg = parse(orbit_ini.render(HOME))
        assert cfg.get("meta", "config.version")
        assert cfg.get("workloads", "default.url").endswith("solr-orbit-workloads")

    def test_paths_point_at_the_remote_home(self):
        # The template carries ${CONFIG_DIR}; a driver's home is not ours.
        cfg = parse(orbit_ini.render(HOME))
        assert cfg.get("node", "root.dir") == f"{HOME}/.solr-orbit/benchmarks"
        assert cfg.get("benchmarks", "local.dataset.cache").startswith(HOME)

    def test_the_report_path_launchr_assumes_is_what_the_ini_says(self):
        # launchr fetches the report from <home>/.solr-orbit/benchmarks/
        # test-runs/<id>/; if the template ever moved root.dir, EC2 runs would
        # silently stop finding their reports.
        from solrorbit.tools.launchr.provisioning.ec2 import REMOTE_REPORT

        root = parse(orbit_ini.render(HOME)).get("node", "root.dir")
        assert REMOTE_REPORT.startswith(".solr-orbit/benchmarks/test-runs/")
        assert root == f"{HOME}/.solr-orbit/benchmarks"


class TestMetricsStore:
    def test_filesystem_is_the_default_launchr_sets(self):
        # In-memory discards every raw sample when the process exits, and on a
        # throwaway driver that means they are gone for good.
        cfg = parse(orbit_ini.render(HOME))
        assert cfg.get("reporting", "datastore.type") == "filesystem"

    def test_it_can_be_overridden_back(self):
        cfg = parse(orbit_ini.render(HOME, {"reporting": {"datastore.type": "in-memory"}}))
        assert cfg.get("reporting", "datastore.type") == "in-memory"

    def test_defaults_can_be_skipped_entirely(self):
        cfg = parse(orbit_ini.render(HOME, apply_defaults=False))
        assert cfg.get("reporting", "datastore.type") == "in-memory"


class TestOverrides:
    def test_an_override_wins(self):
        cfg = parse(orbit_ini.render(HOME, {"workloads": {"default.url": "https://x/y"}}))
        assert cfg.get("workloads", "default.url") == "https://x/y"

    def test_a_new_section_is_created(self):
        cfg = parse(orbit_ini.render(HOME, {"custom": {"a": "b"}}))
        assert cfg.get("custom", "a") == "b"

    def test_key_case_is_preserved(self):
        # Solr Orbit reads `datastore.type`, not `DATASTORE.TYPE`; configparser
        # lowercases by default, which would silently rewrite the file.
        cfg = parse(orbit_ini.render(HOME, {"reporting": {"datastore.Secure": "True"}}))
        assert "datastore.Secure" in dict(cfg.items("reporting"))

    def test_booleans_render_as_ini_booleans(self):
        # YAML gives Python True; getboolean does not accept "True"... it does,
        # but "true" is what the rest of the file uses and what Solr writes.
        cfg = parse(orbit_ini.render(HOME, {"defaults": {"preserve_benchmark_candidate": True}}))
        assert cfg.get("defaults", "preserve_benchmark_candidate") == "true"

    def test_none_renders_as_empty(self):
        cfg = parse(orbit_ini.render(HOME, {"reporting": {"datastore.host": None}}))
        assert cfg.get("reporting", "datastore.host") == ""

    def test_a_non_mapping_section_is_rejected(self):
        with pytest.raises(ConfigError, match="must be a mapping"):
            orbit_ini.render(HOME, {"reporting": "filesystem"})

    def test_the_file_says_it_is_generated(self):
        # Otherwise someone edits it on the box and wonders why it reverts.
        assert "Written by launchr" in orbit_ini.render(HOME)


class TestDescribe:
    """What reached the driver has to reach the report too.

    A result produced against a different workloads repository is not
    comparable with one produced on the defaults, and nothing else in the
    report would say so.
    """

    def test_it_reports_the_defaults(self):
        assert orbit_ini.describe(None)["reporting"]["datastore.type"] == "filesystem"

    def test_it_merges_overrides(self):
        applied = orbit_ini.describe({"workloads": {"default.url": "https://x/y"}})
        assert applied["workloads"]["default.url"] == "https://x/y"
        assert applied["reporting"]["datastore.type"] == "filesystem"

    def test_an_override_of_a_default_is_reported_once(self):
        applied = orbit_ini.describe({"reporting": {"datastore.type": "in-memory"}})
        assert applied["reporting"]["datastore.type"] == "in-memory"
