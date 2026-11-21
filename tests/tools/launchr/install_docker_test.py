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

"""``DockerInstall`` when Solr does not come up."""

import types

import pytest

from solrorbit.tools.launchr.errors import DeployError
from solrorbit.tools.launchr.install import docker as docker_module
from solrorbit.tools.launchr.models import (
    NodeHandle,
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrEndpoint,
)


@pytest.fixture
def infra():
    return ProvisionedInfra(
        profile=types.SimpleNamespace(startup_timeout=1, name="p"),
        strategy="s",
        install_method="docker",
        nodes=[NodeHandle(name="n", endpoint=SolrEndpoint(port=18983))],
    )


@pytest.fixture
def cluster_config():
    return ResolvedClusterConfig(name="c", env={}, workload_params={}, spec=None)


def test_a_failed_start_removes_the_container_and_keeps_its_log(monkeypatch, infra, cluster_config):
    # Without this the orchestrator has no deployment, so it can neither collect
    # the log nor undeploy: the cell loses the one thing worth having, and
    # launchr-solr-18983 keeps running after the session ends.
    commands: list[str] = []

    class Launcher:
        pid = None

        def __init__(self, **kwargs):
            pass

        def start(self, **kwargs):
            raise RuntimeError("startup timeout")

    def run(command, **kwargs):
        commands.append(" ".join(command))
        return types.SimpleNamespace(stdout=b"log line\n", stderr=b"")

    monkeypatch.setattr(docker_module, "SolrDockerLauncher", Launcher)
    monkeypatch.setattr(docker_module.subprocess, "run", run)

    with pytest.raises(DeployError) as raised:
        docker_module.DockerInstall().deploy(infra, "9.11.0", None, cluster_config)

    assert "docker rm -f launchr-solr-18983" in commands
    assert raised.value.logs == {"launchr-solr-18983.log": b"log line\n"}


def test_the_original_startup_error_is_not_lost(monkeypatch, infra, cluster_config):
    class Launcher:
        pid = None

        def __init__(self, **kwargs):
            pass

        def start(self, **kwargs):
            raise RuntimeError("startup timeout")

    monkeypatch.setattr(docker_module, "SolrDockerLauncher", Launcher)
    monkeypatch.setattr(docker_module.subprocess, "run",
                        lambda command, **kw: types.SimpleNamespace(stdout=b"", stderr=b""))

    with pytest.raises(DeployError) as raised:
        docker_module.DockerInstall().deploy(infra, "9.11.0", None, cluster_config)

    assert "startup timeout" in str(raised.value)
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_a_log_that_cannot_be_read_does_not_mask_the_startup_failure(monkeypatch, infra,
                                                                    cluster_config):
    class Launcher:
        pid = None

        def __init__(self, **kwargs):
            pass

        def start(self, **kwargs):
            raise RuntimeError("startup timeout")

    def run(command, **kwargs):
        if command[:2] == ["docker", "logs"]:
            raise OSError("docker went away")
        return types.SimpleNamespace(stdout=b"", stderr=b"")

    monkeypatch.setattr(docker_module, "SolrDockerLauncher", Launcher)
    monkeypatch.setattr(docker_module.subprocess, "run", run)

    with pytest.raises(DeployError) as raised:
        docker_module.DockerInstall().deploy(infra, "9.11.0", None, cluster_config)

    assert "startup timeout" in str(raised.value)
    assert raised.value.logs == {}
