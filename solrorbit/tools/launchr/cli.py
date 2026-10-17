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
"""The ``launchr`` command line.

Four subcommands:

``run``
    Walk the matrix. ``--dry-run`` prints the plan and the exact Solr Orbit
    command lines without touching anything -- it is offline and instant, which
    is what makes it usable as a review tool.
``validate-config``
    Print the resolved configuration with the provenance of every value.
``list``
    Inventory of profiles, cluster configs and plugins.
``version``
    What launchr this is.
"""

import argparse
import logging
import signal
import sys
from datetime import datetime

from solrorbit.tools.launchr import __version__, matrix, orbit, translate
from solrorbit.tools.launchr import config as config_module
from solrorbit.tools.launchr import install as install_module
from solrorbit.tools.launchr import provisioning as provisioning_module
from solrorbit.tools.launchr import storage as storage_module
from solrorbit.tools.launchr.errors import LaunchrError
from solrorbit.tools.launchr.models import (
    NodeHandle,
    ProvisionedInfra,
    SolrDeployment,
    SolrEndpoint,
    new_run_id,
    new_session_id,
)

PROGRAM = "launchr"

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Orchestrate Apache Solr Orbit benchmarks over a matrix of versions, "
                    "workloads, hardware profiles and cluster configs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log at DEBUG level.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Log warnings and errors only.")

    sub = parser.add_subparsers(dest="subcommand", metavar="<command>")

    run = sub.add_parser("run", help="Run the benchmark matrix")
    _add_config_args(run)
    run.add_argument("--versions", help="Comma-separated Solr versions, e.g. 9.0.0,9.7.0,9.11.0.")
    run.add_argument("--workloads", help="Comma-separated workload names.")
    run.add_argument("--provisioning", help="Comma-separated provisioning profile names.")
    run.add_argument("--cluster-config", help="Comma-separated cluster config names.")
    run.add_argument("--storage", dest="storage_backend",
                     help=f"Storage backend ({', '.join(storage_module.available())}).")
    run.add_argument("--storage-path", help="Storage root: a directory for the local backend.")
    run.add_argument("--registry", help="Docker repository for released versions.")
    run.add_argument("--solr-port", type=int, metavar="PORT",
                     help="Port for Solr to listen on, overriding every provisioning profile. "
                          "Useful when the default is taken by a Solr of your own.")
    run.add_argument("--test-mode", action="store_true", default=None,
                     help="Truncate every corpus to 1000 documents. Minutes instead of hours; "
                          "for smoke tests, never for publishable results.")
    run.add_argument("--branch", help="Override the inferred git branch for SNAPSHOT versions.")
    run.add_argument("--version-timestamp", metavar="ISO8601",
                     help="Override the x-axis timestamp for every version in this run.")
    run.add_argument("--dry-run", action="store_true",
                     help="Print the plan and the exact solr-orbit command lines; run nothing.")

    validate = sub.add_parser("validate-config", help="Print the resolved configuration")
    _add_config_args(validate)

    listing = sub.add_parser("list", help="List configured profiles, cluster configs or plugins")
    listing.add_argument("what", nargs="?", default="all",
                         choices=["all", "profiles", "cluster-configs", "plugins"])
    _add_config_args(listing)

    sub.add_parser("version", help="Print the launchr version")
    return parser


def _add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--config", metavar="FILE",
                        help=f"Config file (default: ./{config_module.DEFAULT_CONFIG_FILE} if present).")


def _overrides(args: argparse.Namespace) -> dict:
    """Map CLI arguments onto dotted config paths.

    ``None`` means "not given", and is dropped by the config loader so an unset
    flag never clobbers the file.
    """
    def split(value):
        return [p.strip() for p in value.split(",") if p.strip()] if value else None

    mapping = {
        "solr_versions": split(getattr(args, "versions", None)),
        "workloads": split(getattr(args, "workloads", None)),
        "defaults.provisioning": split(getattr(args, "provisioning", None)),
        "defaults.cluster_config": split(getattr(args, "cluster_config", None)),
        "storage.backend": getattr(args, "storage_backend", None),
        "storage.path": getattr(args, "storage_path", None),
        "registry": getattr(args, "registry", None),
        "benchmark.test_mode": getattr(args, "test_mode", None),
    }
    return {k: v for k, v in mapping.items() if v is not None}


def _configure_logging(args: argparse.Namespace) -> None:
    level = logging.INFO
    if getattr(args, "verbose", False):
        level = logging.DEBUG
    elif getattr(args, "quiet", False):
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    config = config_module.load(args.config, overrides=_overrides(args))
    if args.solr_port:
        config_module.apply_solr_port(config, args.solr_port)
    if args.dry_run:
        return _dry_run(config)

    from solrorbit.tools.launchr import orchestrator

    timestamp = None
    if args.version_timestamp:
        try:
            timestamp = datetime.fromisoformat(args.version_timestamp)
        except ValueError:
            raise LaunchrError(
                f"--version-timestamp {args.version_timestamp!r} is not an ISO-8601 timestamp"
            ) from None
    return orchestrator.run(config, version_timestamp=timestamp, branch=args.branch)


def _dry_run(config: config_module.LaunchrConfig) -> int:
    """Print the plan and the argv for each cell, touching nothing.

    Deliberately offline and instant: this is how a reviewer checks a matrix
    expansion and a cluster-config translation without burning benchmark time.
    Anything that needs the network or a workload checkout belongs in a separate
    command.
    """
    groups = matrix.plan(config)
    print(matrix.describe_plan(groups))

    session_id = new_session_id()
    print("Solr Orbit invocations:\n")
    for group in groups:
        for cell in group.cells:
            cluster_config = translate.resolve(config.cluster_config(cell.cluster_config))
            # The same helper the orchestrator uses: when each built its own,
            # the printed command was not the command that would run.
            params = translate.workload_params(
                cluster_config, config.workloads, cell.workload,
                test_mode=bool(config.benchmark.get("test_mode", False)),
            )
            # Every configured URL, not just the first: provisioning returns
            # them all and build_argv targets them all, so showing one would
            # make the printed command a different command from the real one.
            if group.profile.solr_url:
                endpoints = [SolrEndpoint.from_url(url.strip())
                             for url in group.profile.solr_url.split(",") if url.strip()]
            else:
                endpoints = [SolrEndpoint(port=group.profile.port)]
            deployment = SolrDeployment(
                infra=ProvisionedInfra(
                    profile=group.profile, strategy=group.profile.provisioning,
                    install_method=group.profile.install_method,
                    nodes=[NodeHandle(name=f"solr-{index}", endpoint=endpoint)
                           for index, endpoint in enumerate(endpoints, start=1)],
                ),
                version=cell.solr_version, image=None, endpoints=endpoints,
                cluster_config=cluster_config,
            )
            argv = orbit.build_argv(
                cell, deployment,
                test_run_id="<generated-per-cell>",
                session_id=session_id, run_id=new_run_id(),
                workload_params=params,
                workload_repository=str(config.benchmark.get("workload_repository", "default")),
                test_mode=bool(config.benchmark.get("test_mode", False)),
                user_tags=dict(config.benchmark.get("user_tags", {}) or {}),
            )
            print(f"# {cell.describe()}")
            if cluster_config.env:
                applied = " ".join(f"{k}={v}" for k, v in sorted(cluster_config.env.items()))
                print(f"#   solr env: {applied}")
            print(f"{orbit.describe_argv(argv)}\n")

    print(f"storage: {config.storage_backend} at {config.storage_path}")
    print("Nothing was run (--dry-run).")
    return 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    config = config_module.load(args.config, overrides=_overrides(args))
    print(config.describe())
    print("\nConfiguration is valid.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    what = args.what
    if what in ("all", "plugins"):
        print("plugins")
        print(f"  provisioning:  {', '.join(provisioning_module.available())}")
        print(f"  install:       {', '.join(install_module.available())}")
        print(f"  storage:       {', '.join(storage_module.available())}")
        if what == "plugins":
            return 0
        print()

    config = config_module.load(args.config, overrides=_overrides(args))
    if what in ("all", "profiles"):
        print("provisioning profiles")
        defaults = set(config.default_profiles())
        for name in config.profile_names:
            profile = config.profile(name)
            marker = " (default)" if name in defaults else ""
            detail = f"{profile.provisioning}/{profile.install_method}, {profile.nodes} node(s)"
            if profile.solr_url:
                detail += f", solr_url={profile.solr_url}"
            else:
                detail += f", port={profile.port}"
            print(f"  {name}{marker}: {detail}")
        if what == "profiles":
            return 0
        print()

    if what in ("all", "cluster-configs"):
        print("cluster configs")
        defaults = set(config.default_cluster_configs())
        for name in config.cluster_config_names:
            spec = config.cluster_config(name)
            resolved = translate.resolve(spec)
            marker = " (default)" if name in defaults else ""
            applied = ", ".join(f"{k}={v}" for k, v in sorted(resolved.env.items())) or "Solr defaults"
            params = ", ".join(f"{k}={v}" for k, v in sorted(resolved.workload_params.items())) or "-"
            print(f"  {name}{marker}: {applied}; workload params: {params}")
    return 0


def cmd_version(_: argparse.Namespace) -> int:
    print(f"{PROGRAM} {__version__}")
    return 0


COMMANDS = {
    "run": cmd_run,
    "validate-config": cmd_validate_config,
    "list": cmd_list,
    "version": cmd_version,
}


def _install_signal_handlers() -> None:
    """Turn SIGTERM into KeyboardInterrupt so teardown still runs.

    Python raises KeyboardInterrupt for SIGINT, which unwinds the stack and lets
    the orchestrator's ``finally`` blocks stop Solr and release infrastructure.
    SIGTERM has no such default -- the interpreter just dies, leaking whatever
    was running. A CI job cancelling a benchmark, or a ``timeout`` wrapper,
    sends SIGTERM, so this is the difference between a clean stop and a
    container left holding port 8983.
    """
    def terminate(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, terminate)
        except (ValueError, OSError, AttributeError):
            # Not the main thread, or a platform without the signal.
            logger.debug("Could not install a handler for %s", sig)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 2
    _configure_logging(args)
    _install_signal_handlers()
    try:
        return COMMANDS[args.subcommand](args)
    except LaunchrError as exc:
        # A deliberate failure: the message is the whole story, no traceback.
        print(f"{PROGRAM}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"\n{PROGRAM}: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
