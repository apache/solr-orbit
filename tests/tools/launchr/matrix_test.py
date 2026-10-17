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
"""Matrix expansion, grouping and ordering."""

import pytest
import yaml

from solrorbit.tools.launchr import matrix
from solrorbit.tools.launchr.config import load
from solrorbit.tools.launchr.errors import ConfigError


def config(tmp_path, **document):
    path = tmp_path / "launchr.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return load(path, env={})


class TestExpand:
    def test_one_cell_per_version(self, tmp_path):
        cells = matrix.expand(config(tmp_path, solr_versions=["9.0.0", "9.7.0", "9.11.0"],
                                     workloads=["nyc_taxis"]))
        assert [c.solr_version for c in cells] == ["9.0.0", "9.7.0", "9.11.0"]

    def test_full_cross_product(self, tmp_path):
        cells = matrix.expand(config(
            tmp_path,
            solr_versions=["9.10.0", "9.11.0"],
            workloads=[{"name": "a", "test_procedures": ["p", "q"]}, {"name": "b"}],
            cluster_configs={"c1": {"heap": "1g"}, "c2": {"heap": "2g"}},
            defaults={"provisioning": ["local-docker"], "cluster_config": ["c1", "c2"]},
        ))
        # 2 versions x (2 procedures + 1) x 2 cluster configs
        assert len(cells) == 12

    def test_workload_outer_version_inner(self, tmp_path):
        # All versions of one workload are adjacent: its corpus is fetched once
        # and its trend line completes before the next workload starts.
        cells = matrix.expand(config(tmp_path, solr_versions=["9.0.0", "9.11.0"],
                                     workloads=["a", "b"]))
        assert [(c.workload, c.solr_version) for c in cells] == [
            ("a", "9.0.0"), ("a", "9.11.0"), ("b", "9.0.0"), ("b", "9.11.0"),
        ]

    def test_procedures_come_between_workload_and_version(self, tmp_path):
        cells = matrix.expand(config(tmp_path, solr_versions=["9.0.0", "9.11.0"],
                                     workloads=[{"name": "a", "test_procedures": ["p", "q"]}]))
        assert [(c.test_procedure, c.solr_version) for c in cells] == [
            ("p", "9.0.0"), ("p", "9.11.0"), ("q", "9.0.0"), ("q", "9.11.0"),
        ]

    def test_no_versions_says_how_to_supply_them(self, tmp_path):
        with pytest.raises(ConfigError, match="--versions"):
            matrix.expand(config(tmp_path, workloads=["a"]))

    def test_no_workloads_says_how_to_supply_them(self, tmp_path):
        with pytest.raises(ConfigError, match="--workloads"):
            matrix.expand(config(tmp_path, solr_versions=["9.11.0"]))


class TestCellId:
    def test_includes_every_dimension(self, tmp_path):
        cell = matrix.expand(config(tmp_path, solr_versions=["9.11.0"],
                                    workloads=[{"name": "nyc_taxis", "test_procedures": ["default"]}]))[0]
        assert cell.cell_id == "nyc_taxis__default__9.11.0__local-docker__default-1s1r"

    def test_absent_procedure_reads_as_default(self, tmp_path):
        cell = matrix.expand(config(tmp_path, solr_versions=["9.11.0"], workloads=["w"]))[0]
        assert "__default__" in cell.cell_id

    def test_is_filesystem_safe(self, tmp_path):
        cell = matrix.expand(config(
            tmp_path, solr_versions=["10.0.0-SNAPSHOT"],
            workloads=[{"name": "a/b", "test_procedures": ["p q"]}]))[0]
        assert "/" not in cell.cell_id and " " not in cell.cell_id


class TestGrouping:
    def test_one_profile_is_one_group(self, tmp_path):
        cfg = config(tmp_path, solr_versions=["9.0.0", "9.11.0"], workloads=["a"])
        groups = matrix.group_by_profile(matrix.expand(cfg), cfg)
        assert len(groups) == 1
        assert len(groups[0].cells) == 2

    def test_profiles_differing_only_in_node_count_share_a_group(self, tmp_path):
        # Provisioned once at the maximum; a smaller cell uses a subset. An idle
        # node-hour is cheaper than a teardown-and-rebuild cycle.
        cfg = config(
            tmp_path, solr_versions=["9.11.0"], workloads=["a"],
            provisioning_profiles={
                "two": {"provisioning": "local", "install_method": "docker", "nodes": 2},
                "three": {"provisioning": "local", "install_method": "docker", "nodes": 3}},
            defaults={"provisioning": ["two", "three"], "cluster_config": ["default-1s1r"]},
        )
        groups = matrix.group_by_profile(matrix.expand(cfg), cfg)
        assert len(groups) == 1
        assert groups[0].nodes == 3
        assert sorted(groups[0].profile_names) == ["three", "two"]

    def test_different_install_methods_do_not_share(self, tmp_path):
        cfg = config(
            tmp_path, solr_versions=["9.11.0"], workloads=["a"],
            provisioning_profiles={
                "d": {"provisioning": "local", "install_method": "docker"},
                "n": {"provisioning": "preconfigured", "install_method": "none",
                      "solr_url": "http://localhost:8983"}},
            defaults={"provisioning": ["d", "n"], "cluster_config": ["default-1s1r"]},
        )
        assert len(matrix.group_by_profile(matrix.expand(cfg), cfg)) == 2

    def test_cell_order_is_preserved_inside_a_group(self, tmp_path):
        cfg = config(tmp_path, solr_versions=["9.0.0", "9.7.0", "9.11.0"], workloads=["a", "b"])
        group = matrix.group_by_profile(matrix.expand(cfg), cfg)[0]
        assert [(c.workload, c.solr_version) for c in group.cells] == [
            ("a", "9.0.0"), ("a", "9.7.0"), ("a", "9.11.0"),
            ("b", "9.0.0"), ("b", "9.7.0"), ("b", "9.11.0"),
        ]


class TestDescribePlan:
    def test_shows_every_cell_and_a_teardown(self, tmp_path):
        cfg = config(tmp_path, solr_versions=["9.0.0", "9.11.0"], workloads=["nyc_taxis"])
        described = matrix.describe_plan(matrix.plan(cfg))
        assert "2 cell(s) in 1 provisioning group(s)" in described
        assert "cell 1/2" in described and "cell 2/2" in described
        assert "teardown" in described

    def test_numbers_cells_across_groups(self, tmp_path):
        cfg = config(
            tmp_path, solr_versions=["9.11.0"], workloads=["a"],
            provisioning_profiles={
                "d": {"provisioning": "local", "install_method": "docker"},
                "n": {"provisioning": "preconfigured", "install_method": "none",
                      "solr_url": "http://localhost:8983"}},
            defaults={"provisioning": ["d", "n"], "cluster_config": ["default-1s1r"]},
        )
        described = matrix.describe_plan(matrix.plan(cfg))
        assert "cell 1/2" in described and "cell 2/2" in described
