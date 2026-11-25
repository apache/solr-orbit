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
"""Translate a launchr cluster-config into what actually gets applied.

A launchr cluster-config mixes three concerns that live in three different
places once a benchmark runs:

* ``heap``, ``gc`` and ``solr_opts`` are environment variables on the Solr
  process, applied by the install method.
* ``shards`` and ``replicas`` are *workload parameters*, read by the workloads
  repository's shared ``create_collection.json`` operation and therefore passed
  to Solr Orbit as ``--workload-params``.

Note what is **not** here: a translation to Solr Orbit cluster-config INI names
such as ``4gheap`` or ``g1gc``. Solr Orbit only loads a cluster-config for its
local pipelines; under ``--pipeline=benchmark-only`` it records the names in the
report without applying them. Passing them would put a claim in the report that
nothing acted on, so launchr applies the settings itself and records exactly
what it applied.
"""

from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.models import ClusterConfigSpec, ResolvedClusterConfig

#: Garbage collector name -> the JVM flags it means.
#:
#: ``G1GC`` and ``ParallelGC`` use the same flags as Solr Orbit's ``g1gc.ini``
#: and ``parallelgc.ini`` mixins, so a launchr run and a ``--pipeline=docker``
#: run with the equivalent cluster-config produce the same JVM.
GC_FLAGS: dict[str, str] = {
    "g1gc": "-XX:+UseG1GC -XX:+UseStringDeduplication",
    "parallelgc": "-XX:+UseParallelGC",
    "zgc": "-XX:+UseZGC",
    "serialgc": "-XX:+UseSerialGC",
    "shenandoah": "-XX:+UseShenandoahGC",
}

#: Workload parameter names for shard and replica counts.
#:
#: These are the names the workloads repository's shared
#: ``common_operations/create_collection.json`` templates, which both
#: ``nyc_taxis`` and ``geonames`` include. Note the underscores: the hyphenated
#: ``num-shards`` / ``replication-factor`` are the *operation* keys that template
#: fills in, not the parameters that drive it.
SHARDS_PARAM = "num_shards"
REPLICAS_PARAM = "replication_factor"


def gc_flags(gc: str) -> str:
    """Return the JVM flags for a garbage collector name.

    Raises :class:`ConfigError` for an unknown name rather than silently
    applying nothing -- a benchmark that quietly ran a different collector than
    its report claims is worse than one that refused to start.
    """
    key = gc.strip().lower().replace("-", "").replace("_", "")
    try:
        return GC_FLAGS[key]
    except KeyError:
        known = ", ".join(sorted(GC_FLAGS))
        raise ConfigError(f"Unknown gc {gc!r}. Known collectors: {known}. "
                          f"To pass raw flags instead, put them in solr_opts.") from None


def resolve(spec: ClusterConfigSpec) -> ResolvedClusterConfig:
    """Turn a cluster-config spec into container environment and workload params."""
    env: dict[str, str] = {}
    if spec.heap:
        env["SOLR_HEAP"] = str(spec.heap)
    if spec.gc:
        env["GC_TUNE"] = gc_flags(spec.gc)
    if spec.solr_opts:
        env["SOLR_OPTS"] = str(spec.solr_opts)

    workload_params: dict[str, object] = {}
    if spec.shards is not None:
        workload_params[SHARDS_PARAM] = _positive(spec.shards, "shards", spec.name)
    if spec.replicas is not None:
        workload_params[REPLICAS_PARAM] = _positive(spec.replicas, "replicas", spec.name)

    return ResolvedClusterConfig(name=spec.name, env=env, workload_params=workload_params, spec=spec)


def _positive(value: object, field: str, config_name: str) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ConfigError(f"cluster_config {config_name!r}: {field} must be an integer, got {value!r}") from None
    if number < 1:
        raise ConfigError(f"cluster_config {config_name!r}: {field} must be at least 1, got {number}")
    return number


#: Inverse of the env names, for install methods that want Solr Orbit's
#: cluster-config *variable* names instead (``SolrDockerLauncher`` maps
#: ``heap_size`` -> ``SOLR_HEAP`` itself).
ENV_TO_ORBIT_VARIABLE = {
    "SOLR_HEAP": "heap_size",
    "GC_TUNE": "gc_tune",
    "SOLR_OPTS": "solr_opts",
}


def to_orbit_variables(env) -> dict[str, str]:
    """Render a resolved env dict as Solr Orbit cluster-config variables."""
    return {ENV_TO_ORBIT_VARIABLE[k]: v for k, v in env.items() if k in ENV_TO_ORBIT_VARIABLE}


#: What launchr asks of every workload unless the config says otherwise.
#:
#: ``use_zstd`` is the whole of it, and it is worth a great deal. The
#: nyc_taxis corpus ships as both bz2 and zstd at essentially the same
#: download size -- 4.82 GB against 4.81 GB -- and Solr Orbit's bz2 path is
#: single-threaded Python. Measured on 1000 real documents from that corpus,
#: zstd decompresses about 73x faster (4156 MB/s against 57), which is the
#: difference between 31 minutes with seven of eight cores idle and roughly a
#: minute.
DEFAULT_WORKLOAD_PARAMS: dict[str, object] = {"use_zstd": True}


def default_workload_params(*, test_mode: bool) -> dict[str, object]:
    """launchr's own workload parameters for this run.

    Empty under ``--test-mode``: test mode rewrites the corpus filename to
    its 1000-document variant, and only the *full* corpus is published as
    zstd -- ``documents-1k.json.zst`` returns 403. Defaulting it on would
    make every smoke run fail at download.
    """
    return {} if test_mode else dict(DEFAULT_WORKLOAD_PARAMS)


def workload_params(cluster_config: ResolvedClusterConfig, workloads, workload_name: str,
                    *, test_mode: bool) -> dict:
    """Every workload parameter for one cell, least specific first.

    launchr's defaults, then the cluster-config's shards and replicas, then
    the workload entry's own -- so anything written in the config wins over
    anything launchr assumes.

    Shared by the orchestrator and by ``--dry-run`` deliberately: when each
    built its own, the printed command line was not the one that would run.
    """
    params: dict = dict(default_workload_params(test_mode=test_mode))
    params.update(cluster_config.workload_params)
    for workload in workloads:
        if workload.name == workload_name:
            params.update(workload.workload_params)
            break
    # An explicit null removes a parameter rather than passing it as None.
    # Solr Orbit rejects a workload parameter the workload does not declare --
    # WorkloadConfigError, fatal -- so without this a workload that has no
    # use_zstd could not be run at all: setting it false would still pass an
    # undeclared name. "use_zstd: null" is the way out.
    return {key: value for key, value in params.items() if value is not None}
