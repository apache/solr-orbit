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
"""Deploying Solr across remote nodes, against a stub SSH session.

The assertions here are about the handful of details that decide whether a
two-node cluster forms at all. Each of them is invisible in a single-node
deploy and produces a confusing failure much later when wrong:

* ``SOLR_HOST`` must be the node's own reachable address, or the node
  registers something the other cannot resolve;
* both nodes must point at the *same* ZooKeeper;
* host networking, or a node publishes its container-private address;
* the ZooKeeper container must go away between cells, or the next cell
  inherits the previous one's collections.
"""

import pytest

from solrorbit.tools.launchr.errors import DeployError
from solrorbit.tools.launchr.install import docker_ssh
from solrorbit.tools.launchr.install.docker_ssh import (
    SOLR_CONTAINER,
    ZK_CONTAINER,
    ZK_IMAGE,
    DockerSshInstall,
    resolve_image,
)
from solrorbit.tools.launchr.models import (
    NodeHandle,
    ProfileSpec,
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrEndpoint,
    SshSpec,
)


class StubResult:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode

    @property
    def ok(self):
        return self.returncode == 0


class StubSession:
    """Records every remote command instead of running it."""

    def __init__(self, host, *, running="true", image_created="2026-10-16T02:25:50.1Z"):
        self.spec = SshSpec(host=host, user="ec2-user")
        self.commands: list = []
        self.running = running
        self.image_created = image_created

    def run(self, command, **kwargs):
        self.commands.append(command)
        if isinstance(command, list):
            if command[:2] == ["docker", "inspect"] and "{{.State.Running}}" in command:
                return StubResult(self.running)
            if command[:2] == ["docker", "inspect"] and "{{.Created}}" in command:
                return StubResult(self.image_created)
            if command[:2] == ["docker", "logs"]:
                return StubResult("some log output")
        return StubResult()

    def issued(self, *fragments):
        """Every command containing all of ``fragments``."""
        out = []
        for c in self.commands:
            text = " ".join(c) if isinstance(c, list) else str(c)
            if all(f in text for f in fragments):
                out.append(text)
        return out


@pytest.fixture
def infra():
    profile = ProfileSpec(name="ec2-2node", provisioning="ec2",
                          install_method="docker-ssh", nodes=2)
    nodes = [
        NodeHandle(name="solr-1",
                   endpoint=SolrEndpoint(host="10.0.0.1", port=8983),
                   ssh=SshSpec(host="203.0.113.1", user="ec2-user")),
        NodeHandle(name="solr-2",
                   endpoint=SolrEndpoint(host="10.0.0.2", port=8983),
                   ssh=SshSpec(host="203.0.113.2", user="ec2-user")),
    ]
    return ProvisionedInfra(profile=profile, strategy="ec2", install_method="docker-ssh",
                            nodes=nodes, handles={"known_hosts": "/tmp/kh"})


@pytest.fixture
def sessions():
    return {"solr-1": StubSession("203.0.113.1"), "solr-2": StubSession("203.0.113.2")}


@pytest.fixture
def method(monkeypatch, sessions):
    install = DockerSshInstall()
    monkeypatch.setattr(install, "_session", lambda node, infra: sessions[node.name])
    # The readiness probe polls a real ZooKeeper; the stub answers ok at once.
    monkeypatch.setattr(install, "_wait_for_zookeeper", lambda session, host: None)
    # _start_solr pauses before checking the container is still up, which is
    # right against Docker and pure cost here: two seconds per node on every
    # deploy added a minute to the suite.
    monkeypatch.setattr(docker_ssh.time, "sleep", lambda _: None)
    return install


@pytest.fixture
def cluster_config():
    return ResolvedClusterConfig(
        name="2shard-1replica",
        env={"SOLR_HEAP": "8g", "GC_TUNE": "-XX:+UseG1GC"},
    )


def deploy(method, infra, cluster_config, version="9.11.0"):
    return method.deploy(infra, version, None, cluster_config)


class TestClusterFormation:
    def test_each_node_publishes_its_own_address(self, method, infra, sessions, cluster_config):
        # Without SOLR_HOST a node registers whatever hostname the container
        # sees, which the other node cannot resolve, and the cluster never
        # forms with both members.
        deploy(method, infra, cluster_config)
        assert sessions["solr-1"].issued("SOLR_HOST=10.0.0.1")
        assert sessions["solr-2"].issued("SOLR_HOST=10.0.0.2")

    def test_both_nodes_point_at_the_same_zookeeper(self, method, infra, sessions,
                                                    cluster_config):
        deploy(method, infra, cluster_config)
        for name in ("solr-1", "solr-2"):
            assert sessions[name].issued("ZK_HOST=10.0.0.1:2181"), name

    def test_zookeeper_runs_on_the_first_node_only(self, method, infra, sessions,
                                                   cluster_config):
        deploy(method, infra, cluster_config)
        assert sessions["solr-1"].issued("docker run", ZK_CONTAINER, ZK_IMAGE)
        assert not sessions["solr-2"].issued("docker run", ZK_CONTAINER)

    def test_containers_use_host_networking(self, method, infra, sessions, cluster_config):
        # With bridge networking a node registers its container-private
        # address into ZooKeeper and the cluster half-forms.
        deploy(method, infra, cluster_config)
        for name in ("solr-1", "solr-2"):
            assert sessions[name].issued("docker run", SOLR_CONTAINER, "--network host"), name

    def test_the_zookeeper_placement_is_recorded(self, method, infra, cluster_config):
        # It is an asymmetry between two otherwise identical nodes, and a
        # reader comparing them should not have to read launchr's source.
        deployment = deploy(method, infra, cluster_config)
        assert deployment.metadata["zookeeper"]["colocated_with"] == "solr-1"
        assert deployment.metadata["network"] == "host"


class TestClusterConfig:
    def test_heap_and_gc_reach_the_container(self, method, infra, sessions, cluster_config):
        deploy(method, infra, cluster_config)
        for name in ("solr-1", "solr-2"):
            assert sessions[name].issued("SOLR_HEAP=8g"), name
            assert sessions[name].issued("GC_TUNE=-XX:+UseG1GC"), name

    def test_an_empty_cluster_config_is_fine(self, method, infra, sessions):
        deploy(method, infra, ResolvedClusterConfig(name="bare"))
        assert sessions["solr-1"].issued("docker run", SOLR_CONTAINER)


class TestEndpoints:
    def test_the_driver_is_given_the_private_addresses(self, method, infra, cluster_config):
        # Routing load over the public interface would measure the internet
        # gateway rather than Solr.
        deployment = deploy(method, infra, cluster_config)
        assert deployment.target_hosts == "10.0.0.1:8983,10.0.0.2:8983"

    def test_the_orchestrator_is_given_the_public_ones(self, method, infra, cluster_config):
        # It health-checks from outside the VPC and cannot reach 10.x at all.
        deployment = deploy(method, infra, cluster_config)
        assert [e.host for e in deployment.probe_endpoints] == ["203.0.113.1", "203.0.113.2"]


class TestImages:
    def test_a_release_comes_from_the_release_registry(self):
        assert resolve_image("9.11.0", registry="docker.io/library/solr",
                             nightly_registry="docker.io/apache/solr-nightly") \
            == "docker.io/library/solr:9.11.0"

    def test_a_snapshot_comes_from_the_nightly_registry(self):
        assert resolve_image("11.0.0-SNAPSHOT", registry="docker.io/library/solr",
                             nightly_registry="docker.io/apache/solr-nightly") \
            == "docker.io/apache/solr-nightly:11.0.0-SNAPSHOT"

    def test_the_image_build_date_is_captured(self, method, infra, cluster_config):
        # The only x-axis position a nightly has.
        deployment = deploy(method, infra, cluster_config, version="11.0.0-SNAPSHOT")
        assert deployment.metadata["image_created"] == "2026-10-16T02:25:50.1Z"

    def test_a_missing_build_date_is_not_fatal(self, monkeypatch, method, infra, sessions,
                                               cluster_config):
        for s in sessions.values():
            s.image_created = ""
        deployment = deploy(method, infra, cluster_config)
        assert deployment.metadata["image_created"] is None


class TestFailureHandling:
    def test_a_container_that_exits_immediately_is_caught(self, method, infra, sessions,
                                                          cluster_config):
        # Worth catching here, where the logs are one call away, rather than
        # as a health-check timeout minutes later.
        sessions["solr-2"].running = "false"
        with pytest.raises(DeployError, match="exited immediately"):
            deploy(method, infra, cluster_config)

    def test_nodes_without_ssh_are_refused(self, method, cluster_config):
        profile = ProfileSpec(name="p", provisioning="ec2", install_method="docker-ssh")
        bare = ProvisionedInfra(profile=profile, strategy="ec2", install_method="docker-ssh",
                                nodes=[NodeHandle(name="solr-1")], handles={"known_hosts": "/x"})
        with pytest.raises(DeployError, match="SSH spec"):
            method.deploy(bare, "9.11.0", None, cluster_config)


class TestIndexStorage:
    """The index is bind-mounted to a known path, not left to Docker.

    The Solr image declares VOLUME /var/solr, so a plain `docker run` makes an
    anonymous volume per container that `docker rm` does not remove -- six
    cells would strand six copies of a 40 GB index. A named path is also the
    only way to put the index on a volume other than the root one.
    """

    def test_the_index_is_bind_mounted(self, method, infra, sessions, cluster_config):
        infra.metadata["data_dir"] = "/var/solr-data"
        deploy(method, infra, cluster_config)
        for name in ("solr-1", "solr-2"):
            assert sessions[name].issued("docker run", "-v /var/solr-data:/var/solr"), name

    def test_the_path_comes_from_provisioning(self, method, infra, sessions, cluster_config):
        infra.metadata["data_dir"] = "/mnt/fast"
        deploy(method, infra, cluster_config)
        assert sessions["solr-1"].issued("docker run", "-v /mnt/fast:/var/solr")

    def test_it_is_recorded_in_the_deployment(self, method, infra, cluster_config):
        infra.metadata["data_dir"] = "/var/solr-data"
        assert deploy(method, infra, cluster_config).metadata["data_dir"] == "/var/solr-data"

    def test_the_directory_is_emptied_before_a_cell_starts(self, method, infra, sessions,
                                                           cluster_config):
        # A cell must not inherit the previous version's index: that is worse
        # than wasted disk, because it looks like a result.
        infra.metadata["data_dir"] = "/var/solr-data"
        deploy(method, infra, cluster_config)
        assert sessions["solr-1"].issued("find", "/var/solr-data", "rm -rf")

    def test_the_directory_is_emptied_again_on_undeploy(self, method, infra, sessions,
                                                        cluster_config):
        infra.metadata["data_dir"] = "/var/solr-data"
        deployment = deploy(method, infra, cluster_config)
        before = len(sessions["solr-1"].issued("find", "/var/solr-data"))
        method.undeploy(deployment)
        assert len(sessions["solr-1"].issued("find", "/var/solr-data")) > before

    def test_the_mount_point_itself_is_never_removed(self, method, infra, sessions,
                                                     cluster_config):
        # It is a mount point when a dedicated volume is attached; removing it
        # would detach the index from its disk.
        infra.metadata["data_dir"] = "/var/solr-data"
        deploy(method, infra, cluster_config)
        cleared = sessions["solr-1"].issued("find", "/var/solr-data")
        assert cleared and all("-mindepth 1" in c for c in cleared)

    def test_a_missing_data_dir_falls_back_rather_than_crashing(self, method, infra,
                                                                sessions, cluster_config):
        infra.metadata.pop("data_dir", None)
        deploy(method, infra, cluster_config)
        assert sessions["solr-1"].issued("docker run", "-v /var/solr-data:/var/solr")


class TestCleanup:
    def test_undeploy_removes_both_containers_everywhere(self, method, infra, sessions,
                                                         cluster_config):
        # The ZooKeeper container holds the cluster state; leaving it would
        # give the next cell the previous one's collections.
        deployment = deploy(method, infra, cluster_config)
        method.undeploy(deployment)
        for name in ("solr-1", "solr-2"):
            assert sessions[name].issued("docker rm -f", SOLR_CONTAINER), name
            assert sessions[name].issued("docker rm -f", ZK_CONTAINER), name

    def test_undeploy_without_a_deploy_does_not_raise(self, method, infra, cluster_config):
        from solrorbit.tools.launchr.models import SolrDeployment

        method.undeploy(SolrDeployment(infra=infra, version="9.11.0", image=None,
                                       endpoints=[], cluster_config=cluster_config))

    def test_logs_come_from_every_node(self, method, infra, cluster_config):
        deployment = deploy(method, infra, cluster_config)
        logs = method.collect_logs(deployment)
        assert f"solr-1-{SOLR_CONTAINER}.log" in logs
        assert f"solr-2-{SOLR_CONTAINER}.log" in logs

    def test_zookeeper_logs_come_only_from_its_node(self, method, infra, cluster_config):
        deployment = deploy(method, infra, cluster_config)
        logs = method.collect_logs(deployment)
        assert f"solr-1-{ZK_CONTAINER}.log" in logs
        assert f"solr-2-{ZK_CONTAINER}.log" not in logs
