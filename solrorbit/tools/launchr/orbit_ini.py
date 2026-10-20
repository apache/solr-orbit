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
"""Render Solr Orbit's ``benchmark.ini`` for a remote driver.

Left alone, Solr Orbit writes this file itself the first time it runs, from
its own bundled template, and a remote driver therefore always runs on stock
defaults. That is fine until you want something else -- a filesystem metrics
store so the raw per-sample data survives the instance, a different workloads
repository, a shared results store -- at which point there is nowhere to say
so. A remote run should be configurable from ``launchr.yaml`` and nothing
else; everything it needs is then delegated to Solr Orbit through this file.

**The bundled template stays the source of defaults.** This module reads it
from the installed package and applies overrides on top, so a new key added
upstream appears on the driver without launchr knowing about it. Writing a
file from scratch here would mean re-stating Solr Orbit's defaults and then
watching them drift.

**Local runs are never touched.** This writes to a *remote* driver, which is
a fresh machine with no config of its own. Rewriting the operator's own
``~/.solr-orbit/benchmark.ini`` would be an unpleasant surprise, so the local
provisioning strategy does not call this at all.
"""

import configparser
import logging
from pathlib import Path
from string import Template
from typing import Any, Mapping

from solrorbit.tools.launchr.errors import ConfigError

logger = logging.getLogger(__name__)

#: Where Solr Orbit keeps its configuration, relative to the user's home.
CONFIG_DIRNAME = ".solr-orbit"
CONFIG_FILENAME = "benchmark.ini"

#: What launchr sets that the stock template does not.
#:
#: ``filesystem`` makes Solr Orbit write every metric document to
#: ``metrics.jsonl`` beside the report, rather than keeping them in memory and
#: discarding everything but the aggregates when the process exits. On a
#: throwaway EC2 driver that distinction is total: the raw samples are gone
#: with the instance otherwise, and they are what any later analysis of
#: latency distributions or of a result that looks wrong would need.
DEFAULT_OVERRIDES: dict[str, dict[str, str]] = {
    "reporting": {"datastore.type": "filesystem"},
}


def template_path() -> Path:
    """The bundled ``benchmark.ini`` Solr Orbit would install itself."""
    import solrorbit

    path = Path(solrorbit.__file__).parent / "resources" / CONFIG_FILENAME
    if not path.is_file():
        raise ConfigError(
            f"Solr Orbit's bundled {CONFIG_FILENAME} is missing at {path}. "
            f"This build cannot configure a remote driver."
        )
    return path


def render(home: str, overrides: Mapping[str, Mapping[str, Any]] | None = None,
           *, apply_defaults: bool = True) -> str:
    """Return the ``benchmark.ini`` to place on a driver whose home is ``home``.

    ``overrides`` is ``{section: {key: value}}``, merged over the bundled
    template. A section that does not exist in the template is created, so a
    caller can add configuration Solr Orbit only reads when present.
    """
    config_dir = f"{home.rstrip('/')}/{CONFIG_DIRNAME}"
    raw = Template(template_path().read_text(encoding="utf-8")).substitute(
        CONFIG_DIR=config_dir)

    parser = configparser.ConfigParser()
    # Solr Orbit's own loader is case-sensitive about keys such as
    # `datastore.type`; configparser lowercases them by default, which would
    # silently rewrite the file into something subtly different.
    parser.optionxform = str
    parser.read_string(raw)

    merged: dict[str, dict[str, str]] = {}
    if apply_defaults:
        for section, values in DEFAULT_OVERRIDES.items():
            merged.setdefault(section, {}).update(values)
    for section, values in (overrides or {}).items():
        if not isinstance(values, Mapping):
            raise ConfigError(
                f"orbit_config.{section} must be a mapping of key to value, "
                f"got {type(values).__name__}"
            )
        merged.setdefault(str(section), {}).update(
            {str(k): _render_value(v) for k, v in values.items()})

    for section, values in merged.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in values.items():
            parser.set(section, key, value)

    from io import StringIO

    out = StringIO()
    out.write(
        "# Written by launchr before the benchmark started.\n"
        "# Solr Orbit's own bundled defaults, with this run's overrides applied.\n"
        "# Editing it by hand has no effect: the next run writes it again.\n\n"
    )
    parser.write(out)
    return out.getvalue()


def _render_value(value: Any) -> str:
    """Render a YAML scalar the way an ini file expects it.

    ``True`` has to become ``true``: Solr Orbit reads several of these with
    ``getboolean``, which accepts ``true``/``false`` but not Python's
    capitalised repr.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def describe(overrides: Mapping[str, Mapping[str, Any]] | None,
             *, apply_defaults: bool = True) -> dict[str, dict[str, str]]:
    """What this run overrode, for the report.

    Recorded because a result produced against a different workloads
    repository, or with a metrics store the reader did not expect, is not
    comparable with one produced on the defaults -- and nothing else in the
    report would say so.
    """
    merged: dict[str, dict[str, str]] = {}
    if apply_defaults:
        for section, values in DEFAULT_OVERRIDES.items():
            merged.setdefault(section, {}).update(values)
    for section, values in (overrides or {}).items():
        merged.setdefault(str(section), {}).update(
            {str(k): _render_value(v) for k, v in (values or {}).items()})
    return merged
