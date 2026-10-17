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
"""Write the YAML session summary.

One file per ``launchr run``, listing every cell in execution order with its
outcome and where its report landed. It is what makes a session reviewable
without opening any report, and what ``--retry-failed`` will read in a later
phase.
"""

from datetime import datetime, timezone
from typing import Iterable

import yaml

from solrorbit.tools.launchr.matrix import ProfileGroup
from solrorbit.tools.launchr.models import RunOutcome


def summary_path(session_id: str, started_at: datetime) -> str:
    """Storage-relative path for a session's summary."""
    return f"summaries/{started_at.strftime('%Y-%m-%d')}-{session_id}.yaml"


def build(session_id: str, started_at: datetime, finished_at: datetime,
          groups: Iterable[ProfileGroup], outcomes: Iterable[RunOutcome],
          *, launchr_version: str | None = None) -> dict:
    """Build the summary document."""
    outcome_list = list(outcomes)
    completed = sum(1 for o in outcome_list if o.completed)
    return {
        "session_id": session_id,
        "launchr_version": launchr_version,
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
        "cells": len(outcome_list),
        "completed": completed,
        "failed": len(outcome_list) - completed,
        "groups": [
            {
                "profiles": sorted(g.profile_names),
                "provisioning": g.profile.provisioning,
                "install_method": g.profile.install_method,
                "nodes": g.nodes,
            }
            for g in groups
        ],
        "matrix": [
            {
                "run_id": o.run_id,
                "workload": o.cell.workload,
                "test_procedure": o.cell.test_procedure,
                "solr_version": o.cell.solr_version,
                "provisioning_profile": o.cell.profile,
                "cluster_config": o.cell.cluster_config,
                "status": o.status,
                "started_at": _iso(o.started_at),
                "finished_at": _iso(o.finished_at),
                "test_run_id": o.test_run_id,
                "result_path": o.result_path,
                "error": o.error,
            }
            for o in outcome_list
        ],
    }


def render(document: dict) -> bytes:
    """Serialise a summary document."""
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False).encode("utf-8")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    stamped = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return stamped.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
