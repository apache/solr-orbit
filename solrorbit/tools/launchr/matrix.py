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
"""Expand the test matrix and decide what runs in what order.

One ``launchr run`` walks the full cross-product of versions x workloads x
procedures x profiles x cluster-configs. Two rules shape the walk:

**Grouping.** Cells are grouped by the infrastructure they need, so it is
provisioned once and reused. Node *count* is not part of the group key: two
profiles differing only in ``nodes`` share one group, provisioned at the
maximum.

**Ordering.** Within a group: workload, then procedure, then version. Keeping
all versions of one workload adjacent means its corpus is fetched once and
stays warm, and it front-loads usable output -- a complete trend line for the
first workload exists a third of the way into a three-workload run, so a matrix
that dies half-way has still produced something publishable.
"""

from dataclasses import dataclass, field

from solrorbit.tools.launchr.config import LaunchrConfig
from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.models import MatrixCell, ProfileSpec


@dataclass
class ProfileGroup:
    """Cells that share one provisioned set of machines."""

    profile: ProfileSpec
    cells: list[MatrixCell] = field(default_factory=list)
    #: Maximum node count any cell in this group needs.
    nodes: int = 1
    #: Every profile name folded into this group (they differ only in node count).
    profile_names: list[str] = field(default_factory=list)

    def describe(self) -> str:
        names = ", ".join(sorted(self.profile_names))
        return f"{names} ({self.profile.provisioning}/{self.profile.install_method}, {self.nodes} node(s))"


def expand(config: LaunchrConfig) -> list[MatrixCell]:
    """Expand the configuration into cells, in execution order.

    Order is workload, then test procedure, then version, then profile, then
    cluster-config -- so grouping by profile later preserves the
    workload-outer, version-inner walk within each group.
    """
    versions = config.solr_versions
    workloads = config.workloads
    if not versions:
        raise ConfigError(
            "No Solr versions to run. Pass --versions 9.11.0, set SOLR_VERSIONS, "
            "or add solr_versions to launchr.yaml."
        )
    if not workloads:
        raise ConfigError(
            "No workloads to run. Pass --workloads nyc_taxis, set LAUNCHR_WORKLOADS, "
            "or add workloads to launchr.yaml."
        )

    default_profiles = config.default_profiles()
    default_configs = config.default_cluster_configs()
    if not default_profiles:
        raise ConfigError("defaults.provisioning is empty; name at least one profile")
    if not default_configs:
        raise ConfigError("defaults.cluster_config is empty; name at least one cluster config")

    cells: list[MatrixCell] = []
    for workload in workloads:
        for procedure in workload.test_procedures:
            for version in versions:
                for profile in default_profiles:
                    for cluster_config in default_configs:
                        cells.append(MatrixCell(
                            workload=workload.name,
                            test_procedure=procedure,
                            solr_version=version,
                            profile=profile,
                            cluster_config=cluster_config,
                        ))
    return cells


def group_by_profile(cells: list[MatrixCell], config: LaunchrConfig) -> list[ProfileGroup]:
    """Group cells onto shared infrastructure, preserving cell order within a group."""
    groups: dict[tuple, ProfileGroup] = {}
    for cell in cells:
        profile = config.profile(cell.profile)
        key = profile.group_key
        group = groups.get(key)
        if group is None:
            group = ProfileGroup(profile=profile, nodes=profile.nodes, profile_names=[])
            groups[key] = group
        group.cells.append(cell)
        group.nodes = max(group.nodes, profile.nodes)
        if cell.profile not in group.profile_names:
            group.profile_names.append(cell.profile)
    return list(groups.values())


def plan(config: LaunchrConfig) -> list[ProfileGroup]:
    """Expand and group in one step: the execution plan for a run."""
    return group_by_profile(expand(config), config)


def describe_plan(groups: list[ProfileGroup]) -> str:
    """Render an execution plan for ``--dry-run``."""
    total = sum(len(g.cells) for g in groups)
    lines = [f"{total} cell(s) in {len(groups)} provisioning group(s)", ""]
    index = 0
    for group in groups:
        lines.append(f"group {group.describe()}")
        for cell in group.cells:
            index += 1
            lines.append(f"  cell {index}/{total}  {cell.describe()}")
        lines.append("  teardown")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
