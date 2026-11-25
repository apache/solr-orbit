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
"""Building the Solr Orbit command line, and finding its report."""

from pathlib import Path

import pytest

from solrorbit.tools.launchr import orbit
from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.models import (
    DEFAULT_CLIENT_TIMEOUT,
    MatrixCell,
    NodeHandle,
    ProfileSpec,
    ProvisionedInfra,
    ResolvedClusterConfig,
    SolrDeployment,
    SolrEndpoint,
)


def deployment(endpoints=None, cluster_config=None, client_timeout=None):
    profile = ProfileSpec(name="p", provisioning="local", install_method="docker")
    endpoints = endpoints or [SolrEndpoint()]
    infra = ProvisionedInfra(
        profile=profile, strategy="local", install_method="docker",
        nodes=[NodeHandle(name=f"solr-{i}", endpoint=e) for i, e in enumerate(endpoints)],
    )
    extra = {} if client_timeout is None else {"client_timeout": client_timeout}
    return SolrDeployment(infra=infra, version="9.11.0", image="solr:9.11.0", endpoints=endpoints,
                          cluster_config=cluster_config or ResolvedClusterConfig(name="c"), **extra)


def cell(**kwargs):
    defaults = dict(workload="nyc_taxis", test_procedure=None, solr_version="9.11.0",
                    profile="local-docker", cluster_config="default-1s1r")
    defaults.update(kwargs)
    return MatrixCell(**defaults)


def argv(**kwargs):
    """Build an argv for the default cell, overriding build_argv keywords."""
    defaults = dict(test_run_id="tid", session_id="session-aaa", run_id="run-bbb", workload_params={})
    defaults.update(kwargs)
    return orbit.build_argv(cell(), deployment(), **defaults)


class TestArgv:
    def test_uses_the_benchmark_only_pipeline(self):
        assert "--pipeline=benchmark-only" in argv()

    def test_runs_solr_orbit_as_a_module_not_a_path_binary(self):
        # So launchr always drives the interpreter and Solr Orbit version it was
        # installed with, whatever `solr-orbit` happens to be on PATH.
        built = argv()
        assert built[1:4] == ["-m", "solrorbit.benchmark", "run"]

    def test_passes_the_launchr_generated_run_id(self):
        assert "--test-run-id=tid" in argv(test_run_id="tid")

    def test_never_passes_cluster_config(self):
        # Solr Orbit records it without applying it under benchmark-only, which
        # would put an unhonoured claim in the report.
        assert not any(a.startswith("--cluster-config") for a in argv())

    def test_never_passes_distribution_version(self):
        # Solr Orbit derives it from the live cluster, which is more trustworthy.
        assert not any(a.startswith("--distribution-version") for a in argv())

    def test_single_iteration_without_aggregation(self):
        built = argv()
        assert "--test-iterations=1" in built and "--aggregate=false" in built

    def test_aborts_on_error(self):
        # A cell whose operations error is not producing a usable data point.
        assert "--on-error=abort" in argv()

    def test_test_procedure_only_when_the_cell_names_one(self):
        assert not any(a.startswith("--test-procedure") for a in
                       orbit.build_argv(cell(), deployment(), test_run_id="t", session_id="s",
                                        run_id="r", workload_params={}))
        with_procedure = orbit.build_argv(cell(test_procedure="longevity"), deployment(),
                                          test_run_id="t", session_id="s", run_id="r",
                                          workload_params={})
        assert "--test-procedure=longevity" in with_procedure

    def test_test_mode_is_opt_in(self):
        assert "--test-mode" not in argv()
        assert "--test-mode" in argv(test_mode=True)

    def test_workload_params_are_json(self):
        # JSON sidesteps the comma and colon escaping that k:v pairs require;
        # Solr Orbit's to_dict() accepts an object starting with '{'.
        built = argv(workload_params={"num_shards": 3, "replication_factor": 2})
        param = [a for a in built if a.startswith("--workload-params=")][0]
        assert param == '--workload-params={"num_shards":3,"replication_factor":2}'

    def test_no_workload_params_flag_when_there_are_none(self):
        assert not any(a.startswith("--workload-params") for a in argv())

    def test_target_hosts_omits_the_scheme_for_plain_http(self):
        built = argv()
        assert "--target-hosts=127.0.0.1:8983" in built

    def test_target_hosts_keeps_the_scheme_for_tls(self):
        tls = SolrEndpoint(scheme="https", host="solr.internal", port=8983)
        built = orbit.build_argv(cell(), deployment([tls]), test_run_id="t", session_id="s",
                                 run_id="r", workload_params={})
        assert "--target-hosts=https://solr.internal:8983" in built

    def test_multiple_endpoints_are_comma_joined(self):
        endpoints = [SolrEndpoint(host="a"), SolrEndpoint(host="b")]
        built = orbit.build_argv(cell(), deployment(endpoints), test_run_id="t", session_id="s",
                                 run_id="r", workload_params={})
        assert "--target-hosts=a:8983,b:8983" in built

    def test_client_options_disable_verification_only_when_asked(self):
        assert f"--client-options=timeout:{DEFAULT_CLIENT_TIMEOUT}" in argv()
        lax = SolrEndpoint(scheme="https", verify_certs=False)
        built = orbit.build_argv(cell(), deployment([lax]), test_run_id="t", session_id="s",
                                 run_id="r", workload_params={})
        assert f"--client-options=timeout:{DEFAULT_CLIENT_TIMEOUT},verify_certs:false" in built

    def test_the_client_timeout_is_the_deployment_s(self):
        # It has to outlast the longest single request a benchmark makes, which
        # is optimize: a force-merge of the whole index behind one HTTP call.
        built = orbit.build_argv(cell(), deployment(client_timeout=30), test_run_id="t",
                                 session_id="s", run_id="r", workload_params={})
        assert "--client-options=timeout:30" in built


class TestUserTags:
    def test_carries_launchr_provenance(self):
        tag = [a for a in argv() if a.startswith("--user-tag=")][0]
        assert "launchr-session:session-aaa" in tag
        assert "launchr-run:run-bbb" in tag
        assert "launchr-cluster-config:default-1s1r" in tag
        assert "launchr-profile:local-docker" in tag

    def test_configured_tags_are_appended(self):
        tag = [a for a in argv(user_tags={"intention": "nightly"}) if a.startswith("--user-tag=")][0]
        assert "intention:nightly" in tag

    @pytest.mark.parametrize("bad", [{"a,b": "v"}, {"k": "a,b"}, {"k": "a:b"}, {"a:b": "v"}])
    def test_separators_in_tags_are_rejected_with_a_clear_message(self, bad):
        # Solr Orbit's parser splits on ',' then ':', so these would be silently
        # mangled or blow up deep inside the benchmark.
        with pytest.raises(ConfigError, match="separators"):
            orbit.render_user_tags(bad)

    def test_none_value_renders_as_empty(self):
        assert orbit.render_user_tags({"k": None}) == "k:"


class TestReportPath:
    def test_plain_run(self, tmp_path):
        assert orbit.report_path("abc", root=tmp_path) == tmp_path / "test-runs" / "abc" / "test_run.json"

    def test_aggregated_run(self, tmp_path):
        expected = tmp_path / "aggregated_results" / "abc" / "aggregated_test_run.json"
        assert orbit.report_path("abc", aggregated=True, root=tmp_path) == expected

    def test_orbit_root_is_a_real_directory_path(self):
        # Read from Solr Orbit's own benchmark.ini so launchr follows the same
        # configuration the benchmark does.
        root = orbit.orbit_root()
        assert isinstance(root, Path)
        assert root.is_absolute()


class TestDescribeArgv:
    def test_shortens_the_interpreter(self):
        assert orbit.describe_argv(argv()).startswith("python -m solrorbit.benchmark run")

    def test_quotes_arguments_containing_json(self):
        rendered = orbit.describe_argv(argv(workload_params={"num_shards": 1}))
        assert "'--workload-params={\"num_shards\":1}'" in rendered
