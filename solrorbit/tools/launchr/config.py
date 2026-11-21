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
"""Load, merge and validate launchr's configuration.

Precedence is ``CLI flag > environment variable > launchr.yaml > built-in
default``, resolved once here and never re-read. Every value remembers where it
came from, which is the only practical way to debug a precedence problem in CI
-- see ``launchr validate-config``.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from solrorbit.tools.launchr import translate
from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.models import (
    DEFAULT_SOLR_PORT,
    ClusterConfigSpec,
    ProfileSpec,
    WorkloadSpec,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_FILE = "launchr.yaml"

def default_storage_path(env: Mapping[str, str] | None = None) -> str:
    """Where runs land when nothing says otherwise.

    Under Solr Orbit's home, beside the caches and installs it already keeps
    there, rather than in whatever directory launchr was invoked from. A result
    store is the history of a machine's benchmarking, not an artifact of one
    shell session: defaulting it to the working directory means running from
    somewhere else silently starts an empty history, and running from a
    repository checkout litters it.

    ``BENCHMARK_HOME`` moves it, the same variable Solr Orbit already honours
    for everything else it stores.
    """
    environ = os.environ if env is None else env
    home = environ.get("BENCHMARK_HOME") or os.path.expanduser("~")
    return os.path.join(home, ".solr-orbit", "benchmark-results")


#: Built-in defaults. Chosen so that ``launchr run --versions X --workloads Y``
#: works on a machine with nothing but Docker: local provisioning, a container
#: per cell, results under Solr Orbit's home.
BUILT_IN: dict[str, Any] = {
    "solr_versions": [],
    "registry": "docker.io/library/solr",
    "nightly_registry": "docker.io/apache/solr-nightly",
    # Empty means "decide when the config is loaded", so BENCHMARK_HOME is read
    # at the moment it matters rather than frozen at import.
    "storage": {"backend": "local", "path": ""},
    "provisioning_profiles": {
        "local-docker": {
            "provisioning": "local",
            "install_method": "docker",
            "nodes": 1,
            "port": DEFAULT_SOLR_PORT,
        }
    },
    "cluster_configs": {
        "default-1s1r": {"heap": "4g", "gc": "G1GC", "shards": 1, "replicas": 1}
    },
    "defaults": {"provisioning": ["local-docker"], "cluster_config": ["default-1s1r"]},
    "workloads": [],
    "benchmark": {
        "iterations": 1,
        "aggregate": False,
        "test_mode": False,
        "workload_repository": "default",
        "user_tags": {},
    },
    "versions": {"cache": "~/.launchr/version-cache.json", "offline": False},
}

#: Setting path -> environment variable. Only settings with a CLI flag get one,
#: so the three ways of saying the same thing stay in step.
ENV_VARS: dict[str, str] = {
    "solr_versions": "SOLR_VERSIONS",
    "workloads": "LAUNCHR_WORKLOADS",
    "defaults.provisioning": "LAUNCHR_PROVISIONING",
    "defaults.cluster_config": "LAUNCHR_CLUSTER_CONFIG",
    "storage.backend": "LAUNCHR_STORAGE_BACKEND",
    "storage.path": "LAUNCHR_STORAGE_PATH",
    "registry": "LAUNCHR_REGISTRY",
}

#: Keys whose value is a comma-separated list on the command line and in the
#: environment, but a real list in YAML.
LIST_SETTINGS = {"solr_versions", "workloads", "defaults.provisioning", "defaults.cluster_config"}

#: Config keys that must never hold a secret. launchr reads credentials from the
#: ambient chain (environment, cloud profile, instance role) and nowhere else.
_CREDENTIAL_HINTS = ("password", "secret", "token", "access_key", "secret_key", "credential", "api_key")


@dataclass
class Provenance:
    """Where each resolved setting came from."""

    sources: dict[str, str] = field(default_factory=dict)

    def record(self, key: str, source: str) -> None:
        self.sources[key] = source

    def of(self, key: str) -> str:
        return self.sources.get(key, "built-in default")


@dataclass
class LaunchrConfig:
    """A fully resolved configuration."""

    data: dict[str, Any]
    provenance: Provenance
    config_path: Path | None = None

    # -- scalars ----------------------------------------------------------

    @property
    def registry(self) -> str:
        return str(self.data["registry"])

    @property
    def nightly_registry(self) -> str:
        return str(self.data["nightly_registry"])

    @property
    def solr_versions(self) -> list[str]:
        return [str(v) for v in self.data["solr_versions"]]

    @property
    def storage_backend(self) -> str:
        return str(self.data["storage"]["backend"])

    @property
    def storage_path(self) -> str:
        return str(self.data["storage"]["path"])

    @property
    def benchmark(self) -> Mapping[str, Any]:
        return self.data["benchmark"]

    @property
    def version_cache_path(self) -> str | None:
        return self.data.get("versions", {}).get("cache")

    @property
    def offline(self) -> bool:
        return bool(self.data.get("versions", {}).get("offline", False))

    # -- structured sections ---------------------------------------------

    def profile(self, name: str) -> ProfileSpec:
        """Return one provisioning profile, validated."""
        profiles = self.data["provisioning_profiles"]
        if name not in profiles:
            known = ", ".join(sorted(profiles)) or "(none defined)"
            raise ConfigError(f"Unknown provisioning profile {name!r}. Defined: {known}")
        raw = dict(profiles[name] or {})
        provisioning = raw.pop("provisioning", None)
        install_method = raw.pop("install_method", None)
        if not provisioning:
            raise ConfigError(f"Provisioning profile {name!r} does not set 'provisioning'")
        if not install_method:
            raise ConfigError(f"Provisioning profile {name!r} does not set 'install_method'")
        options = dict(raw.pop("options", {}) or {})
        spec = ProfileSpec(
            name=name,
            provisioning=str(provisioning),
            install_method=str(install_method),
            nodes=int(raw.pop("nodes", 1)),
            port=int(raw.pop("port", DEFAULT_SOLR_PORT)),
            solr_url=raw.pop("solr_url", None),
            startup_timeout=int(raw.pop("startup_timeout", 300)),
            options=options,
        )
        if raw:
            # Unknown keys are nearly always typos, and a silently ignored
            # instance_type is exactly the kind of thing that wastes a night.
            raise ConfigError(
                f"Provisioning profile {name!r} has unknown keys: {', '.join(sorted(raw))}. "
                f"Put plugin-specific settings under 'options:'."
            )
        return spec

    @property
    def profile_names(self) -> list[str]:
        return sorted(self.data["provisioning_profiles"])

    def cluster_config(self, name: str) -> ClusterConfigSpec:
        """Return one cluster-config, validated."""
        configs = self.data["cluster_configs"]
        if name not in configs:
            known = ", ".join(sorted(configs)) or "(none defined)"
            raise ConfigError(f"Unknown cluster config {name!r}. Defined: {known}")
        raw = dict(configs[name] or {})
        spec = ClusterConfigSpec(
            name=name,
            heap=raw.pop("heap", None),
            gc=raw.pop("gc", None),
            solr_opts=raw.pop("solr_opts", None),
            shards=raw.pop("shards", None),
            replicas=raw.pop("replicas", None),
        )
        if raw:
            raise ConfigError(
                f"Cluster config {name!r} has unknown keys: {', '.join(sorted(raw))}"
            )
        return spec

    @property
    def cluster_config_names(self) -> list[str]:
        return sorted(self.data["cluster_configs"])

    @property
    def workloads(self) -> list[WorkloadSpec]:
        """The workloads to run, as specs."""
        specs: list[WorkloadSpec] = []
        for entry in self.data["workloads"]:
            if isinstance(entry, str):
                specs.append(WorkloadSpec(name=entry))
                continue
            raw = dict(entry or {})
            name = raw.pop("name", None)
            if not name:
                raise ConfigError(f"Workload entry {entry!r} has no 'name'")
            procedures = raw.pop("test_procedures", None)
            if procedures in (None, []):
                tests: tuple[str | None, ...] = (None,)
            elif isinstance(procedures, str):
                tests = (procedures,)
            else:
                tests = tuple(str(p) for p in procedures)
            specs.append(WorkloadSpec(
                name=str(name),
                test_procedures=tests,
                workload_params=dict(raw.pop("workload_params", {}) or {}),
            ))
            if raw:
                raise ConfigError(
                    f"Workload {name!r} has unknown keys: {', '.join(sorted(raw))}"
                )
        return specs

    def default_profiles(self) -> list[str]:
        return [str(p) for p in self.data["defaults"]["provisioning"]]

    def default_cluster_configs(self) -> list[str]:
        return [str(c) for c in self.data["defaults"]["cluster_config"]]

    # -- reporting --------------------------------------------------------

    def describe(self) -> str:
        """Render the resolved configuration with the provenance of each value."""
        lines = [f"config file: {self.config_path or '(none; built-in defaults)'}", ""]
        for key in sorted(_flatten(self.data)):
            value = _get(self.data, key)
            lines.append(f"{key} = {value!r}".ljust(60) + f"  <- {self.provenance.of(key)}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load(config_path: str | os.PathLike | None = None, *, env: Mapping[str, str] | None = None,
         overrides: Mapping[str, Any] | None = None) -> LaunchrConfig:
    """Resolve the configuration from defaults, a YAML file, the environment and CLI overrides.

    :param config_path: explicit config file. When omitted, ``./launchr.yaml``
        is used if it exists; otherwise built-in defaults apply.
    :param env: environment mapping, for testing. Defaults to ``os.environ``.
    :param overrides: CLI overrides, keyed by dotted setting path. ``None``
        values are ignored, so an unset flag does not clobber the file.
    """
    environ = os.environ if env is None else env
    data = _deep_copy(BUILT_IN)
    provenance = Provenance()

    resolved_path = _locate(config_path)
    if resolved_path is not None:
        file_data = _read_yaml(resolved_path)
        _merge(data, file_data, provenance, origin=str(resolved_path))

    for key, var in ENV_VARS.items():
        raw = environ.get(var)
        if raw is None or raw == "":
            continue
        value = _coerce(key, raw)
        _set(data, key, value)
        provenance.record(key, f"${var}")

    for key, value in (overrides or {}).items():
        if value is None:
            continue
        _set(data, key, value)
        provenance.record(key, "CLI flag")

    if not str(data["storage"].get("path") or "").strip():
        data["storage"]["path"] = default_storage_path(environ)
        provenance.record("storage.path", "default")

    config = LaunchrConfig(data=data, provenance=provenance, config_path=resolved_path)
    validate(config)
    return config


def apply_solr_port(config: LaunchrConfig, port: int) -> None:
    """Override the Solr port on every provisioning profile.

    A convenience for the common case of one local profile. Assuming 8983 is a
    bad default for a Solr developer, who very likely has their own Solr there,
    and the provisioning pipelines refuse to start when the port is busy.
    """
    for name, profile in config.data["provisioning_profiles"].items():
        if profile is None:
            continue
        profile["port"] = int(port)
        config.provenance.record(f"provisioning_profiles.{name}.port", "CLI flag")


def _locate(config_path: str | os.PathLike | None) -> Path | None:
    if config_path:
        path = Path(os.path.expanduser(str(config_path)))
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        return path
    default = Path(DEFAULT_CONFIG_FILE)
    return default if default.exists() else None


def _read_yaml(path: Path) -> dict:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    unknown = set(loaded) - set(BUILT_IN)
    if unknown:
        raise ConfigError(
            f"{path} has unknown top-level keys: {', '.join(sorted(unknown))}. "
            f"Known: {', '.join(sorted(BUILT_IN))}"
        )
    return loaded


def validate(config: LaunchrConfig) -> None:
    """Check the configuration for problems worth catching before anything runs."""
    _reject_credentials(config.data)

    # Resolving each section is the validation: the properties raise on bad input.
    for name in config.profile_names:
        config.profile(name)
    for name in config.cluster_config_names:
        # cluster_config() only builds a spec. translate.resolve() is what
        # rejects an unknown gc or a bad shard count, and left to run time it
        # would raise from inside a cell, after infrastructure is provisioned
        # and outside the per-cell handler -- aborting the whole session with
        # no failed-cell report.
        translate.resolve(config.cluster_config(name))
    config.workloads

    for profile in config.default_profiles():
        if profile not in config.data["provisioning_profiles"]:
            raise ConfigError(
                f"defaults.provisioning names unknown profile {profile!r}. "
                f"Defined: {', '.join(config.profile_names) or '(none)'}"
            )
    for cluster_config in config.default_cluster_configs():
        if cluster_config not in config.data["cluster_configs"]:
            raise ConfigError(
                f"defaults.cluster_config names unknown config {cluster_config!r}. "
                f"Defined: {', '.join(config.cluster_config_names) or '(none)'}"
            )

    iterations = int(config.benchmark.get("iterations", 1))
    if iterations < 1:
        raise ConfigError(f"benchmark.iterations must be at least 1, got {iterations}")
    if iterations > 1:
        # Solr Orbit's multi-iteration path generates its own run ids for the
        # second and later iterations and for the aggregate, so launchr cannot
        # locate those reports. Supporting this needs launchr to drive the
        # iterations itself plus an upstream fix to `aggregate --test-runs-id`.
        raise ConfigError(
            f"benchmark.iterations is {iterations}, but this phase supports 1. "
            f"Multi-iteration runs with aggregation need launchr to own every test-run id; "
            f"see the plan's Appendix B."
        )

    if bool(config.benchmark.get("aggregate", False)):
        # Aggregation combines several iterations, and only one is supported, so
        # the invocation passes --aggregate=false. Accepting the setting would
        # put "aggregated: true" in a report of a single unaggregated run.
        raise ConfigError(
            "benchmark.aggregate is true, but this phase runs a single iteration "
            "and cannot aggregate. Remove the setting; see the plan's Appendix B."
        )


def _reject_credentials(data: Any, path: str = "") -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            full = f"{path}.{key}" if path else str(key)
            if any(hint in str(key).lower() for hint in _CREDENTIAL_HINTS):
                raise ConfigError(
                    f"Config key {full!r} looks like a credential. launchr reads credentials "
                    f"from the environment, your cloud profile or an instance role -- never "
                    f"from a config file that gets committed."
                )
            _reject_credentials(value, full)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            _reject_credentials(item, f"{path}[{index}]")


# ---------------------------------------------------------------------------
# Dotted-path helpers
# ---------------------------------------------------------------------------


def _coerce(key: str, raw: str) -> Any:
    if key in LIST_SETTINGS:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    return raw


def _set(data: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    cursor = data
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _get(data: dict, key: str) -> Any:
    cursor: Any = data
    for part in key.split("."):
        cursor = cursor[part]
    return cursor


def _flatten(data: Any, prefix: str = "") -> list[str]:
    """Dotted paths of every leaf, treating lists as leaves."""
    if isinstance(data, dict) and data:
        keys: list[str] = []
        for key, value in data.items():
            keys.extend(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return keys
    return [prefix] if prefix else []


def _merge(target: dict, source: Mapping, provenance: Provenance, *, origin: str = "",
           prefix: str = "") -> None:
    """Recursively merge ``source`` into ``target``, recording provenance."""
    for key, value in source.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value, provenance, origin=origin, prefix=path)
        else:
            target[key] = _deep_copy(value)
            for leaf in _flatten(value, path) or [path]:
                provenance.record(leaf, origin)


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value
