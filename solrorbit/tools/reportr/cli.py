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
"""The ``reportr`` command line.

``build``
    Read the stored reports and write the site. ``--serve`` then serves it on
    localhost, which is the whole local development loop.
``metrics``
    List the metric keys the stored reports could supply, since which
    percentiles exist depends on how the benchmark was run.
"""

import argparse
import json
import logging
import sys

from solrorbit.tools.launchr import storage
from solrorbit.tools.launchr.errors import LaunchrError
from solrorbit.tools.reportr import __version__, builder, extract, publish as publish_module, serve
from solrorbit.tools.reportr import config as config_module

PROGRAM = "reportr"

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Build a static benchmark trends site from Solr Orbit reports.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log at DEBUG level.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Log warnings and errors only.")

    sub = parser.add_subparsers(dest="subcommand", metavar="<command>")

    build = sub.add_parser("build", help="Build the site")
    _add_common(build)
    build.add_argument("--out", metavar="DIR", help="Where to write the site (default: ./site-output).")
    build.add_argument("--metrics", help="Comma-separated metric keys, overriding the config.")
    build.add_argument("--serve", action="store_true", help="Serve the site after building it.")
    build.add_argument("--port", type=int, default=8080, help="Port for --serve (default: 8080).")
    build.add_argument("--open", dest="open_browser", action="store_true",
                       help="Open the site in a browser after building.")
    build.add_argument("--publish", metavar="DEST", nargs="?", const="",
                       help="Publish the site after building, to DEST or to site.publish_to.")

    publish = sub.add_parser("publish", help="Upload an already-built site")
    _add_common(publish)
    publish.add_argument("--out", metavar="DIR", help="The built site to upload (default: ./site-output).")
    publish.add_argument("--to", metavar="DEST",
                         help="s3://bucket/prefix or a directory (default: site.publish_to).")
    publish.add_argument("--dry-run", action="store_true",
                         help="List what would be uploaded, upload nothing.")

    metrics = sub.add_parser("metrics", help="List the metric keys the reports could supply")
    _add_common(metrics)

    sub.add_parser("version", help="Print the reportr version")
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--config", metavar="FILE",
                        help=f"Config file (default: ./{config_module.DEFAULT_CONFIG_FILE} if present).")
    parser.add_argument("--local", metavar="DIR",
                        help="Read reports from this directory (shorthand for a local storage path).")
    parser.add_argument("--storage", dest="storage_backend",
                        help=f"Storage backend ({', '.join(storage.available())}). "
                             f"Inferred from an s3:// storage path.")
    parser.add_argument("--storage-path", help="Storage root, e.g. s3://bucket/prefix.")


def _overrides(args: argparse.Namespace) -> dict:
    mapping = {
        "storage.backend": getattr(args, "storage_backend", None),
        # --local is the friendly spelling of --storage-path for the common case.
        "storage.path": getattr(args, "local", None) or getattr(args, "storage_path", None),
        "site.out": getattr(args, "out", None),
    }
    metrics = getattr(args, "metrics", None)
    if metrics:
        mapping["metrics"] = [m.strip() for m in metrics.split(",") if m.strip()]
    return {k: v for k, v in mapping.items() if v is not None}


def _configure_logging(args: argparse.Namespace) -> None:
    level = logging.INFO
    if getattr(args, "verbose", False):
        level = logging.DEBUG
    elif getattr(args, "quiet", False):
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)


def cmd_build(args: argparse.Namespace) -> int:
    config = config_module.load(args.config, overrides=_overrides(args))
    result = builder.build(config)
    print(result.describe())

    if not result.points:
        print(f"\nNo plottable points found under {config.storage_path}/runs/.")
        print("Run a benchmark first:")
        print("  launchr run --versions 9.9.0,9.10.1,9.11.0 --workloads nyc_taxis --test-mode")

    url = f"http://127.0.0.1:{args.port}/"
    if args.open_browser and result.points:
        import webbrowser

        webbrowser.open(url)
    destination = getattr(args, "publish", None)
    if destination is not None:
        code = _publish(config, result.out_dir, destination or config.publish_to)
        if code:
            return code

    if args.serve:
        serve.serve(result.out_dir, port=args.port)
    elif result.points:
        print(f"\nOpen it with:  reportr build --local {config.storage_path} --serve")
    return 0


def _publish(config, site_dir, destination: str, *, dry_run: bool = False) -> int:
    """Shared by `build --publish` and `publish`."""
    if not destination:
        print("Nothing to publish to: pass --to, or set site.publish_to in reportr.yaml.",
              file=sys.stderr)
        return 2
    try:
        store = storage.backend_for(destination, options=dict(config.storage_options))
        written = publish_module.publish(site_dir, destination, backend=store, dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001 - the CLI reports, it does not traceback
        print(f"Could not publish to {destination}: {exc}", file=sys.stderr)
        return 1

    verb = "Would publish" if dry_run else "Published"
    print(f"\n{verb} {len(written)} file(s) to {destination}")
    url = publish_module.entry_url(destination, _region_of(store, config))
    if url and not dry_run:
        print(f"Open it at:    {url}")
    return 0


def _region_of(store, config) -> str | None:
    """The region to build a URL from.

    Preferring the client's resolved region over the configured one matters:
    the cross-region S3 endpoint answers a GET with a 307 to the regional one,
    so a URL without the region works in a browser but not in `curl` or a
    `fetch` that does not follow redirects.
    """
    configured = config.storage_options.get("region")
    if configured:
        return configured
    client = getattr(store, "client", None)
    return getattr(getattr(client, "meta", None), "region_name", None)


def cmd_publish(args: argparse.Namespace) -> int:
    config = config_module.load(args.config, overrides=_overrides(args))
    return _publish(config, config.out_dir, args.to or config.publish_to, dry_run=args.dry_run)


def cmd_metrics(args: argparse.Namespace) -> int:
    """List what the stored reports could chart.

    Useful because the available percentiles depend on ``--latency-percentiles``
    and on how many samples a run produced: a test-mode run may offer ``p50``
    and ``p100`` but no ``p99``.
    """
    config = config_module.load(args.config, overrides=_overrides(args))
    store = storage.backend_for(config.storage_path, config.storage_backend,
                                dict(config.storage_options))
    reports = builder.find_reports(store)
    if not reports:
        print(f"No reports under {store.location}/runs/.")
        return 0

    available: dict[str, int] = {}
    for path in reports:
        try:
            report = json.loads(store.read(path).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, LaunchrError):
            continue
        for metric in extract.metrics_in(report):
            available[metric] = available.get(metric, 0) + 1

    print(f"{len(reports)} report(s) under {store.location}/runs/\n")
    print(f"{'metric':34s} present in")
    for metric, count in sorted(available.items()):
        marker = " *" if metric in config.metrics else ""
        print(f"  {metric:32s} {count}/{len(reports)}{marker}")
    print("\n  * currently charted")
    return 0


def cmd_version(_: argparse.Namespace) -> int:
    print(f"{PROGRAM} {__version__}")
    return 0


COMMANDS = {
    "build": cmd_build,
    "publish": cmd_publish,
    "metrics": cmd_metrics,
    "version": cmd_version,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 2
    _configure_logging(args)
    try:
        return COMMANDS[args.subcommand](args)
    except LaunchrError as exc:
        print(f"{PROGRAM}: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(f"\n{PROGRAM}: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
