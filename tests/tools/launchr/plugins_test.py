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
"""The three plugin registries, and the contract every plugin must honour.

The conformance assertions at the bottom are the useful part: they run against
every registered plugin, so a new one cannot quietly break the orchestrator's
assumptions about teardown and undeploy being safe in any state.
"""

import pytest

from solrorbit.tools.launchr import install as install_module
from solrorbit.tools.launchr import provisioning as provisioning_module
from solrorbit.tools.launchr import storage as storage_module
from solrorbit.tools.launchr.errors import ConfigError, DeployError
from solrorbit.tools.launchr.install.base import SolrInstallMethod
from solrorbit.tools.launchr.models import (
    ProfileSpec,
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrDeployment,
    SolrEndpoint,
)
from solrorbit.tools.launchr.provisioning.base import ProvisioningStrategy
from solrorbit.tools.launchr.storage.base import StorageBackend


class TestRegistries:
    def test_phase_one_provisioning_strategies(self):
        assert provisioning_module.available() == ["local", "preconfigured"]

    def test_phase_one_install_methods(self):
        assert install_module.available() == ["docker", "none"]

    def test_phase_one_storage_backends(self):
        assert storage_module.available() == ["local"]

    def test_unknown_names_list_the_alternatives(self):
        with pytest.raises(ConfigError, match="local, preconfigured"):
            provisioning_module.get_strategy("pulumi-ec2")
        with pytest.raises(ConfigError, match="docker, none"):
            install_module.get_install_method("docker-ssh")

    def test_install_methods_ignore_keywords_they_do_not_want(self):
        # NoOpInstall takes no registry; passing one must not be an error.
        assert install_module.get_install_method("none", registry="x", nightly_registry="y")

    def test_docker_install_receives_the_registry(self):
        method = install_module.get_install_method("docker", registry="ghcr.io/apache/solr")
        assert method.registry == "ghcr.io/apache/solr"


class TestProtocolConformance:
    @pytest.mark.parametrize("name", provisioning_module.available())
    def test_provisioning_strategies_satisfy_the_protocol(self, name):
        strategy = provisioning_module.get_strategy(name)
        assert isinstance(strategy, ProvisioningStrategy)
        assert strategy.name == name
        assert strategy.API_VERSION == 1

    @pytest.mark.parametrize("name", install_module.available())
    def test_install_methods_satisfy_the_protocol(self, name):
        method = install_module.get_install_method(name)
        assert isinstance(method, SolrInstallMethod)
        assert method.name == name
        assert method.API_VERSION == 1

    @pytest.mark.parametrize("name", storage_module.available())
    def test_storage_backends_satisfy_the_protocol(self, name, tmp_path):
        backend = storage_module.get_backend(name, str(tmp_path))
        assert isinstance(backend, StorageBackend)
        assert backend.name == name
        assert backend.API_VERSION == 1


class TestTeardownSafety:
    """Teardown runs in a ``finally``; it must never raise, in any state."""

    @pytest.mark.parametrize("name", provisioning_module.available())
    def test_teardown_is_idempotent(self, name):
        strategy = provisioning_module.get_strategy(name)
        profile = ProfileSpec(name="p", provisioning=name, install_method="none",
                              solr_url="http://localhost:8983")
        infra = strategy.provision(profile, nodes=1)
        strategy.teardown(infra)
        strategy.teardown(infra)  # twice is fine

    @pytest.mark.parametrize("name", install_module.available())
    def test_undeploy_without_a_deploy_is_a_no_op(self, name):
        method = install_module.get_install_method(name)
        profile = ProfileSpec(name="p", provisioning="local", install_method=name)
        infra = ProvisionedInfra(profile=profile, strategy="local", install_method=name)
        deployment = SolrDeployment(infra=infra, version="9.11.0", image=None, endpoints=[],
                                    cluster_config=ResolvedClusterConfig(name="c"))
        method.undeploy(deployment)

    @pytest.mark.parametrize("name", install_module.available())
    def test_collect_logs_never_raises(self, name):
        method = install_module.get_install_method(name)
        profile = ProfileSpec(name="p", provisioning="local", install_method=name)
        infra = ProvisionedInfra(profile=profile, strategy="local", install_method=name)
        deployment = SolrDeployment(infra=infra, version="9.11.0", image=None, endpoints=[],
                                    cluster_config=ResolvedClusterConfig(name="c"))
        assert isinstance(method.collect_logs(deployment), dict)


class TestLocalProvisioning:
    def test_returns_localhost_on_the_configured_port(self):
        strategy = provisioning_module.get_strategy("local")
        profile = ProfileSpec(name="p", provisioning="local", install_method="docker", port=9000)
        infra = strategy.provision(profile, nodes=1)
        assert len(infra.nodes) == 1
        assert infra.endpoints[0] == SolrEndpoint(scheme="http", host="127.0.0.1", port=9000)

    def test_labels_itself_as_local_for_reportr(self):
        # The report records this so a local result is never presented as
        # production data.
        strategy = provisioning_module.get_strategy("local")
        profile = ProfileSpec(name="p", provisioning="local", install_method="docker")
        assert strategy.provision(profile, nodes=1).metadata["provider"] == "local"

    def test_describes_the_host(self):
        strategy = provisioning_module.get_strategy("local")
        profile = ProfileSpec(name="p", provisioning="local", install_method="docker")
        host = strategy.provision(profile, nodes=1).metadata["host"]
        assert "os" in host and "arch" in host

    def test_refuses_multi_node_rather_than_quietly_running_one(self):
        strategy = provisioning_module.get_strategy("local")
        profile = ProfileSpec(name="p", provisioning="local", install_method="docker", nodes=3)
        with pytest.raises(ConfigError, match="supports exactly 1"):
            strategy.provision(profile, nodes=3)

    def test_the_driver_is_this_process(self):
        strategy = provisioning_module.get_strategy("local")
        profile = ProfileSpec(name="p", provisioning="local", install_method="docker")
        assert strategy.provision(profile, nodes=1).driver is None


class TestPreconfiguredProvisioning:
    def test_parses_the_configured_url(self):
        strategy = provisioning_module.get_strategy("preconfigured")
        profile = ProfileSpec(name="p", provisioning="preconfigured", install_method="none",
                              solr_url="https://solr.internal:8984")
        endpoint = strategy.provision(profile, nodes=1).endpoints[0]
        assert (endpoint.scheme, endpoint.host, endpoint.port) == ("https", "solr.internal", 8984)

    def test_accepts_several_urls(self):
        strategy = provisioning_module.get_strategy("preconfigured")
        profile = ProfileSpec(name="p", provisioning="preconfigured", install_method="none",
                              solr_url="http://a:8983,http://b:8983")
        assert len(strategy.provision(profile, nodes=2).endpoints) == 2

    def test_a_bare_host_port_defaults_to_http(self):
        strategy = provisioning_module.get_strategy("preconfigured")
        profile = ProfileSpec(name="p", provisioning="preconfigured", install_method="none",
                              solr_url="solr.internal:8983")
        endpoint = strategy.provision(profile, nodes=1).endpoints[0]
        assert (endpoint.scheme, endpoint.port) == ("http", 8983)

    def test_a_missing_url_says_what_to_add(self):
        strategy = provisioning_module.get_strategy("preconfigured")
        profile = ProfileSpec(name="p", provisioning="preconfigured", install_method="none")
        with pytest.raises(ConfigError, match="solr_url"):
            strategy.provision(profile, nodes=1)

    def test_an_unparseable_url_is_rejected(self):
        strategy = provisioning_module.get_strategy("preconfigured")
        profile = ProfileSpec(name="p", provisioning="preconfigured", install_method="none",
                              solr_url="ftp://solr:21")
        with pytest.raises(ConfigError, match="unsupported scheme"):
            strategy.provision(profile, nodes=1)


class TestNoOpInstall:
    def test_passes_the_existing_endpoints_through(self):
        method = install_module.get_install_method("none")
        profile = ProfileSpec(name="p", provisioning="preconfigured", install_method="none",
                              solr_url="http://solr:8983")
        infra = provisioning_module.get_strategy("preconfigured").provision(profile, nodes=1)
        deployment = method.deploy(infra, "9.11.0", None, ResolvedClusterConfig(name="c"))
        assert deployment.endpoints == infra.endpoints
        assert deployment.metadata["externally_managed"] is True

    def test_warns_when_a_cluster_config_cannot_be_applied(self, caplog):
        # It cannot touch a cluster it does not manage, and a report claiming
        # otherwise would be false.
        method = install_module.get_install_method("none")
        profile = ProfileSpec(name="p", provisioning="preconfigured", install_method="none",
                              solr_url="http://solr:8983")
        infra = provisioning_module.get_strategy("preconfigured").provision(profile, nodes=1)
        cluster_config = ResolvedClusterConfig(name="c", env={"SOLR_HEAP": "4g"})
        with caplog.at_level("WARNING"):
            method.deploy(infra, "9.11.0", None, cluster_config)
        assert "cannot apply" in caplog.text


class TestDockerInstallImageResolution:
    def test_release_uses_the_release_repository(self):
        from solrorbit.tools.launchr.install.docker import resolve_image
        assert resolve_image("9.11.0", registry="docker.io/library/solr",
                             nightly_registry="x") == "docker.io/library/solr:9.11.0"

    def test_snapshot_uses_the_nightly_repository(self):
        from solrorbit.tools.launchr.install.docker import resolve_image
        assert resolve_image("10.0.0-SNAPSHOT", registry="solr",
                             nightly_registry="apache/solr-nightly") == \
            "apache/solr-nightly:10.0.0-SNAPSHOT"

    def test_defaults_match_solr_orbits_own_docker_pipeline(self):
        # So launchr and `solr-orbit run --pipeline=docker` pull the same bytes.
        from solrorbit.builder.solr_provisioner import SolrDockerLauncher
        assert SolrDockerLauncher.DEFAULT_IMAGE_REPOSITORY == "solr"
        assert SolrDockerLauncher.DEFAULT_NIGHTLY_IMAGE_REPOSITORY == "apache/solr-nightly"

    def test_refuses_more_than_one_endpoint(self):
        method = install_module.get_install_method("docker")
        profile = ProfileSpec(name="p", provisioning="local", install_method="docker")
        infra = ProvisionedInfra(
            profile=profile, strategy="local", install_method="docker",
            nodes=[], metadata={},
        )
        from solrorbit.tools.launchr.models import NodeHandle
        infra.nodes = [NodeHandle(name="a", endpoint=SolrEndpoint(host="a")),
                       NodeHandle(name="b", endpoint=SolrEndpoint(host="b"))]
        with pytest.raises(DeployError, match="single container"):
            method.deploy(infra, "9.11.0", None, ResolvedClusterConfig(name="c"))
