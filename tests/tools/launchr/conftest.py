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
"""Shared fixtures for the launchr tests."""

import json
from pathlib import Path

import pytest

RESOURCES = Path(__file__).parent / "resources"


def load_resource(name: str) -> dict:
    return json.loads((RESOURCES / name).read_text(encoding="utf-8"))


@pytest.fixture
def orbit_report() -> dict:
    """A real Solr Orbit ``test_run.json``, trimmed to two op_metrics entries."""
    return load_resource("test_run.json")


@pytest.fixture
def info_system_release() -> dict:
    """``/solr/admin/info/system`` from a released Solr."""
    return load_resource("info_system_release.json")


@pytest.fixture
def info_system_snapshot() -> dict:
    """``/solr/admin/info/system`` from a nightly SNAPSHOT build."""
    return load_resource("info_system_snapshot.json")


@pytest.fixture
def solr_project() -> dict:
    """The Apache project JSON that carries release dates."""
    return load_resource("solr_project.json")


@pytest.fixture(autouse=True)
def away_from_the_repo_config(tmp_path, monkeypatch):
    """Run every launchr test somewhere without a launchr.yaml.

    ``config.load(None)`` picks up ``./launchr.yaml`` when one is there, so a
    suite run from the repository root silently inherits the repository's own
    settings -- and a test asserting a default starts failing the moment
    someone edits that file. Tests that want it ask for it by path.
    """
    monkeypatch.chdir(tmp_path)
