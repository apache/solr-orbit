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
"""Load reportr's configuration.

Small by design: where the reports are, where the site goes, which metrics to
chart, and optionally which tasks matter per workload. Everything else is
derived from the data.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from solrorbit.tools.launchr import config as launchr_config
from solrorbit.tools.launchr.errors import ConfigError

DEFAULT_CONFIG_FILE = "reportr.yaml"

#: Metrics charted when the config does not say otherwise: how fast it indexed,
#: how slow the typical and the tail request were, and whether anything failed.
DEFAULT_METRICS = [
    "throughput.mean",
    "service_time.mean",
    "service_time.p50",
    "service_time.p90",
    "service_time.p99",
    "error_rate",
]

#: What a per-workload block may contain. Spelled out so a typo is an error at
#: load time rather than a setting that silently does nothing.
WORKLOAD_KEYS = {"description", "tasks", "default_tasks", "featured_tasks"}

BUILT_IN: dict[str, Any] = {
    # Empty means "decide when the config is loaded": the same store launchr
    # writes to, so `reportr build` with no arguments reads what the last run
    # produced. --local or reportr.yaml points it elsewhere.
    "storage": {"backend": "local", "path": ""},
    "site": {"out": "./site-output", "title": "Apache Solr Benchmarks"},
    "metrics": DEFAULT_METRICS,
    "workloads": {},
    # Curated notes about a particular Solr build: what a release fixed, what it
    # broke, why a step in the line is not a mystery. Nothing is inferred -- a
    # regression detector that cried wolf would be worse than no annotation.
    "annotations": [],
}

#: What an annotation entry may say.
ANNOTATION_KEYS = {"version", "text", "url", "workload", "task"}


@dataclass
class ReportrConfig:
    """A resolved reportr configuration."""

    data: dict[str, Any]
    config_path: Path | None = None

    @property
    def storage_backend(self) -> str:
        return str(self.data["storage"]["backend"])

    @property
    def storage_path(self) -> str:
        return str(self.data["storage"]["path"])

    @property
    def out_dir(self) -> Path:
        return Path(os.path.expanduser(str(self.data["site"]["out"])))

    @property
    def title(self) -> str:
        return str(self.data["site"]["title"])

    @property
    def metrics(self) -> list[str]:
        return [str(m) for m in self.data["metrics"]]

    def annotations_for(self, workload: str) -> list[dict]:
        """Curated release notes that apply to this workload's charts."""
        return [
            entry for entry in (self.data.get("annotations") or [])
            if not entry.get("workload") or entry["workload"] == workload
        ]

    def workload_entry(self, workload: str) -> dict:
        """This workload's config block, or an empty one."""
        entry = (self.data.get("workloads") or {}).get(workload)
        return entry if isinstance(entry, dict) else {}

    def tasks_for(self, workload: str) -> list[str] | None:
        """Curated tasks for a workload, or ``None`` meaning every task.

        An unlisted workload charts everything, so a new workload appears on the
        site without a config change and can be trimmed later.
        """
        tasks = self.workload_entry(workload).get("tasks")
        return [str(t) for t in tasks] if tasks else None

    def description_for(self, workload: str) -> str | None:
        """What this workload measures, in the operator's words.

        Overrides whatever the workload says about itself: the person running
        the site knows which comparison this particular site is for.
        """
        text = self.workload_entry(workload).get("description")
        return str(text).strip() or None if text else None

    def default_tasks_for(self, workload: str) -> list[str] | None:
        """Tasks charted before the reader picks, or ``None`` to decide."""
        tasks = self.workload_entry(workload).get("default_tasks")
        return [str(t) for t in tasks] if tasks else None

    def featured_tasks_for(self, workload: str) -> list[str] | None:
        """Tasks that each deserve a chart of their own, or ``None``."""
        tasks = self.workload_entry(workload).get("featured_tasks")
        return [str(t) for t in tasks] if tasks else None


def load(config_path: str | os.PathLike | None = None, *,
         overrides: Mapping[str, Any] | None = None) -> ReportrConfig:
    """Resolve the configuration from defaults, a YAML file and CLI overrides."""
    data = _deep_copy(BUILT_IN)
    resolved = _locate(config_path)
    if resolved is not None:
        _merge(data, _read_yaml(resolved))
    for key, value in (overrides or {}).items():
        if value is None:
            continue
        _set(data, key, value)
    if not str(data["storage"].get("path") or "").strip():
        data["storage"]["path"] = launchr_config.default_storage_path()

    config = ReportrConfig(data=data, config_path=resolved)
    _validate(config)
    return config


def _validate(config: ReportrConfig) -> None:
    if config.storage_backend != "local":
        raise ConfigError(
            f"Unknown storage backend {config.storage_backend!r}. This phase reads the local "
            f"filesystem only; cloud backends arrive with the storage plugin work."
        )
    if not config.metrics:
        raise ConfigError("metrics is empty; name at least one, e.g. throughput.mean")
    annotations = config.data.get("annotations") or []
    if not isinstance(annotations, list):
        raise ConfigError("annotations must be a list of entries")
    for index, entry in enumerate(annotations):
        if not isinstance(entry, dict):
            raise ConfigError(f"annotations[{index}] must be a mapping")
        unknown = set(entry) - ANNOTATION_KEYS
        if unknown:
            raise ConfigError(
                f"annotations[{index}] has unknown keys: {', '.join(sorted(unknown))}. "
                f"Known: {', '.join(sorted(ANNOTATION_KEYS))}"
            )
        if not str(entry.get("version") or "").strip():
            raise ConfigError(f"annotations[{index}] needs a version to attach itself to")
        if not str(entry.get("text") or "").strip():
            raise ConfigError(f"annotations[{index}] needs text; an unexplained marker explains nothing")

    for workload, entry in (config.data.get("workloads") or {}).items():
        if not isinstance(entry, dict):
            raise ConfigError(f"workloads.{workload} must be a mapping, got {type(entry).__name__}")
        unknown = set(entry) - WORKLOAD_KEYS
        if unknown:
            raise ConfigError(
                f"workloads.{workload} has unknown keys: {', '.join(sorted(unknown))}. "
                f"Known: {', '.join(sorted(WORKLOAD_KEYS))}"
            )
        for key in ("tasks", "default_tasks", "featured_tasks"):
            value = entry.get(key)
            if value is not None and not isinstance(value, list):
                raise ConfigError(f"workloads.{workload}.{key} must be a list of task names")
        # A featured task that is not charted would silently never appear.
        restricted = entry.get("tasks")
        if restricted:
            for key in ("default_tasks", "featured_tasks"):
                stray = [t for t in (entry.get(key) or []) if t not in restricted]
                if stray:
                    raise ConfigError(
                        f"workloads.{workload}.{key} names {', '.join(stray)}, which "
                        f"workloads.{workload}.tasks leaves out"
                    )


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


def _merge(target: dict, source: Mapping) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = _deep_copy(value)


def _set(data: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    cursor = data
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value
