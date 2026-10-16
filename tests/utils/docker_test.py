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

"""Finding Docker Compose under either of its two names."""

import subprocess
import types

import pytest

from solrorbit import exceptions
from solrorbit.utils import docker


def _probe(available):
    """A subprocess.run that succeeds only for the named commands.

    A missing binary raises FileNotFoundError rather than returning non-zero,
    which is how Compose v1's absence actually presents.
    """
    def run(command, **kwargs):
        name = " ".join(command[:-1])
        if name not in available:
            raise FileNotFoundError(2, "No such file or directory", command[0])
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    return run


@pytest.fixture(autouse=True)
def _uncached():
    docker.compose_command.cache_clear()
    yield
    docker.compose_command.cache_clear()


class TestWhichComposeIsUsed:
    def test_v2_is_preferred_when_both_are_present(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", _probe({"docker compose", "docker-compose"}))
        assert docker.compose_command() == "docker compose"

    def test_v2_is_used_when_only_v2_is_present(self, monkeypatch):
        # The current CI runners and every recent Docker install.
        monkeypatch.setattr(subprocess, "run", _probe({"docker compose"}))
        assert docker.compose_command() == "docker compose"

    def test_v1_is_used_when_only_v1_is_present(self, monkeypatch):
        # An older Docker Desktop, which is why the fallback stays.
        monkeypatch.setattr(subprocess, "run", _probe({"docker-compose"}))
        assert docker.compose_command() == "docker-compose"

    def test_neither_present_is_an_explanatory_error(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run", _probe(set()))
        with pytest.raises(exceptions.SystemSetupError, match="docker compose"):
            docker.compose_command()

    def test_a_candidate_that_runs_but_fails_is_not_used(self, monkeypatch):
        # Docker present but the compose plugin missing: `docker compose version`
        # exits non-zero rather than raising.
        def run(command, **kwargs):
            if command[0] == "docker-compose":
                return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
            return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"no such command")
        monkeypatch.setattr(subprocess, "run", run)
        assert docker.compose_command() == "docker-compose"

    def test_the_probe_runs_once_however_often_it_is_asked(self, monkeypatch):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        monkeypatch.setattr(subprocess, "run", run)
        assert docker.compose_command() == docker.compose_command() == "docker compose"
        assert len(calls) == 1

    def test_a_probe_that_hangs_is_not_fatal(self, monkeypatch):
        def run(command, **kwargs):
            if command[0] == "docker":
                raise subprocess.TimeoutExpired(cmd=command, timeout=docker.PROBE_TIMEOUT_SECONDS)
            return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        monkeypatch.setattr(subprocess, "run", run)
        assert docker.compose_command() == "docker-compose"


class TestTheCommandsThatGetBuilt:
    def test_the_local_launcher_uses_the_resolved_command(self, monkeypatch):
        from solrorbit.builder import launcher as launcher_module

        monkeypatch.setattr(subprocess, "run", _probe({"docker compose"}))
        built = launcher_module.DockerLauncher._docker_compose(None, "/tmp/cfg", "up -d")
        assert built == "docker compose -f /tmp/cfg/docker-compose.yml up -d"

    def test_the_shell_launcher_uses_the_resolved_command(self, monkeypatch):
        from solrorbit.builder.launchers import docker_launcher as docker_launcher_module

        monkeypatch.setattr(subprocess, "run", _probe({"docker compose"}))
        built = docker_launcher_module.DockerLauncher._docker_compose(
            docker_launcher_module.DockerLauncher.__new__(docker_launcher_module.DockerLauncher),
            "/tmp/cfg", "ps -q")
        assert built == "docker compose -f /tmp/cfg/docker-compose.yml ps -q"
