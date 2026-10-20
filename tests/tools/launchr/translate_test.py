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
"""Every row of the cluster-config translation table.

This is the piece most able to fail silently: a wrong translation benchmarks a
different configuration than the report claims, and nothing visibly breaks. So
each mapping gets an assertion.
"""

import pytest

from solrorbit.tools.launchr import translate
from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.models import ClusterConfigSpec, ResolvedClusterConfig


def resolve(**kwargs):
    return translate.resolve(ClusterConfigSpec(name="t", **kwargs))


class TestEnvironment:
    def test_heap_becomes_solr_heap(self):
        assert resolve(heap="4g").env["SOLR_HEAP"] == "4g"

    def test_g1gc_uses_the_same_flags_as_solr_orbits_mixin(self):
        # Matches resources/cluster_configs/main/cluster_configs/v1/g1gc.ini, so a
        # launchr run and an equivalent --pipeline=docker run get the same JVM.
        assert resolve(gc="G1GC").env["GC_TUNE"] == "-XX:+UseG1GC -XX:+UseStringDeduplication"

    def test_parallelgc(self):
        assert resolve(gc="ParallelGC").env["GC_TUNE"] == "-XX:+UseParallelGC"

    def test_zgc(self):
        assert resolve(gc="ZGC").env["GC_TUNE"] == "-XX:+UseZGC"

    @pytest.mark.parametrize("spelling", ["g1gc", "G1GC", "g1-gc", "G1_GC", " g1gc "])
    def test_gc_name_is_forgiving_about_spelling(self, spelling):
        assert "UseG1GC" in resolve(gc=spelling).env["GC_TUNE"]

    def test_omitted_gc_leaves_solrs_own_default(self):
        assert "GC_TUNE" not in resolve(heap="2g").env

    def test_solr_opts_passes_through(self):
        opts = "-Dsolr.autoSoftCommit.maxTime=1000"
        assert resolve(solr_opts=opts).env["SOLR_OPTS"] == opts

    def test_empty_config_applies_nothing(self):
        assert resolve().env == {}

    def test_unknown_gc_fails_loudly(self):
        # Silently applying nothing would mean the report claims a collector
        # that never ran.
        with pytest.raises(ConfigError, match="Unknown gc"):
            resolve(gc="EpsilonGC")

    def test_unknown_gc_names_the_alternatives(self):
        with pytest.raises(ConfigError, match="g1gc"):
            resolve(gc="nonsense")


class TestWorkloadParams:
    def test_shards_uses_the_workloads_repo_parameter_name(self):
        # num_shards with an underscore: the hyphenated form is the *operation*
        # key that common_operations/create_collection.json fills in.
        assert resolve(shards=3).workload_params == {"num_shards": 3}

    def test_replicas(self):
        assert resolve(replicas=2).workload_params == {"replication_factor": 2}

    def test_both(self):
        params = resolve(shards=3, replicas=2).workload_params
        assert params == {"num_shards": 3, "replication_factor": 2}

    def test_strings_are_coerced(self):
        assert resolve(shards="3").workload_params["num_shards"] == 3

    @pytest.mark.parametrize("value", [0, -1])
    def test_non_positive_counts_are_rejected(self, value):
        with pytest.raises(ConfigError, match="at least 1"):
            resolve(shards=value)

    def test_non_numeric_count_is_rejected(self):
        with pytest.raises(ConfigError, match="must be an integer"):
            resolve(replicas="many")


class TestOrbitVariables:
    def test_env_maps_back_to_orbit_cluster_config_variables(self):
        # SolrDockerLauncher wants heap_size/gc_tune/solr_opts and does the
        # env-var mapping itself.
        resolved = resolve(heap="8g", gc="G1GC", solr_opts="-Dfoo=bar")
        assert translate.to_orbit_variables(resolved.env) == {
            "heap_size": "8g",
            "gc_tune": "-XX:+UseG1GC -XX:+UseStringDeduplication",
            "solr_opts": "-Dfoo=bar",
        }

    def test_unknown_env_keys_are_dropped(self):
        assert translate.to_orbit_variables({"SOLR_HEAP": "1g", "UNRELATED": "x"}) == {"heap_size": "1g"}


def test_spec_is_kept_for_the_report():
    # The report records both what was asked for and what was applied.
    resolved = resolve(heap="4g", gc="G1GC", shards=1)
    assert resolved.spec.heap == "4g"
    assert resolved.spec.gc == "G1GC"


class TestWorkloadParameters:
    """What launchr asks of a workload, and how a config overrides it."""

    class _Workload:
        def __init__(self, name, params):
            self.name = name
            self.workload_params = params

    @staticmethod
    def _cc(params=None):
        return ResolvedClusterConfig(name="c", env={}, workload_params=params or {}, spec=None)

    def test_zstd_is_asked_for_by_default(self):
        params = translate.workload_params(self._cc(), [], "nyc_taxis", test_mode=False)
        assert params["use_zstd"] is True

    def test_test_mode_does_not_ask_for_zstd(self):
        # Test mode rewrites the corpus name to its 1000-document variant, and
        # only the full corpus is published as zstd.
        assert translate.workload_params(self._cc(), [], "nyc_taxis", test_mode=True) == {}

    def test_the_workload_entry_wins_over_the_default(self):
        workloads = [self._Workload("nyc_taxis", {"use_zstd": False})]
        params = translate.workload_params(self._cc(), workloads, "nyc_taxis", test_mode=False)
        assert params["use_zstd"] is False

    def test_an_explicit_null_removes_the_parameter(self):
        # Solr Orbit rejects a parameter the workload does not declare, so a
        # workload without use_zstd needs a way to drop it entirely.
        workloads = [self._Workload("custom", {"use_zstd": None})]
        params = translate.workload_params(self._cc(), workloads, "custom", test_mode=False)
        assert "use_zstd" not in params

    def test_cluster_config_params_are_included_and_overridable(self):
        workloads = [self._Workload("w", {"num_shards": 4})]
        params = translate.workload_params(
            self._cc({"num_shards": 1, "replication_factor": 1}), workloads, "w", test_mode=False)
        assert params["num_shards"] == 4 and params["replication_factor"] == 1
