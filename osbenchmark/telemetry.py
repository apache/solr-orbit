# SPDX-License-Identifier: Apache-2.0
#
# Modifications by Apache Solr contributors; see git log for details.
# Licensed under the Apache License, Version 2.0.
#
# The OpenSearch Contributors require contributions made to
# this file be licensed under the Apache-2.0 license or a
# compatible open source license.
# Modifications Copyright OpenSearch Contributors. See
# GitHub history for details.
# Licensed to Elasticsearch B.V. under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Elasticsearch B.V. licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import json
import logging
import os
import re
import threading
from abc import abstractmethod

import tabulate

from osbenchmark import metrics, time, exceptions
from osbenchmark.utils import io, sysstats, console, process

def list_telemetry():
    console.println("Available telemetry devices:\n")

    # --- Solr-native devices (always enabled) ---
    console.println("Always-enabled Solr devices (no --telemetry flag needed):\n")
    solr_devices = [
        [d.command, d.human_name, d.help] for d in [
            SolrJvmStats,
            SolrNodeStats,
            SolrCollectionStats,
            SolrQueryStats,
            SolrIndexingStats,
            SolrCacheStats,
        ]
    ]
    console.println(tabulate.tabulate(solr_devices, ["Command", "Name", "Description"]))
    console.println("\nAll always-on devices poll /solr/admin/metrics (JSON on Solr 9.x, Prometheus text on Solr 10.x).")

    # --- Optional REST devices (all pipelines) ---
    console.println("\n\nOptional REST devices (all pipelines — enable with --telemetry <command>):\n")
    rest_devices = [[device.command, device.human_name, device.help] for device in [
        SegmentStats, ShardStats, ClusterEnvironmentInfo,
    ]]
    console.println(tabulate.tabulate(rest_devices, ["Command", "Name", "Description"]))

    # --- Optional JVM/process devices (provisioned pipelines only) ---
    console.println("\n\nOptional JVM/process devices (docker or from-distribution pipelines only):\n")
    jvm_devices = [[device.command, device.human_name, device.help] for device in [
        FlightRecorder, Gc, JitCompiler, Heapdump,
    ]]
    console.println(tabulate.tabulate(jvm_devices, ["Command", "Name", "Description"]))
    console.println("\nJVM/process devices inject flags into SOLR_OPTS before Solr starts.")
    console.println("They are silently skipped when pipeline is benchmark-only.")
    console.println("\nNote: disk-io (disk I/O byte counters) is always active on provisioned pipelines.")


class Telemetry:
    def __init__(self, enabled_devices=None, devices=None):
        if devices is None:
            devices = []
        if enabled_devices is None:
            enabled_devices = []
        self.enabled_devices = enabled_devices
        self.devices = devices

    def instrument_candidate_java_opts(self):
        opts = []
        for device in self.devices:
            if self._enabled(device):
                additional_opts = device.instrument_java_opts()
                # properly merge values with the same key
                opts.extend(additional_opts)
        return opts

    def on_pre_node_start(self, node_name):
        for device in self.devices:
            if self._enabled(device):
                device.on_pre_node_start(node_name)

    def attach_to_node(self, node):
        for device in self.devices:
            if self._enabled(device):
                device.attach_to_node(node)

    def detach_from_node(self, node, running):
        for device in self.devices:
            if self._enabled(device):
                device.detach_from_node(node, running)

    def on_benchmark_start(self):
        for device in self.devices:
            if self._enabled(device):
                device.on_benchmark_start()

    def on_benchmark_stop(self):
        for device in self.devices:
            if self._enabled(device):
                device.on_benchmark_stop()

    def store_system_metrics(self, node, metrics_store):
        for device in self.devices:
            if self._enabled(device):
                device.store_system_metrics(node, metrics_store)

    def _enabled(self, device):
        return device.internal or device.command in self.enabled_devices


########################################################################################
#
# Telemetry devices
#
########################################################################################

class TelemetryDevice:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def instrument_java_opts(self):
        return {}

    def on_pre_node_start(self, node_name):
        pass

    def attach_to_node(self, node):
        pass

    def detach_from_node(self, node, running):
        pass

    def on_benchmark_start(self):
        pass

    def on_benchmark_stop(self):
        pass

    def store_system_metrics(self, node, metrics_store):
        pass

    def __getstate__(self):
        state = self.__dict__.copy()
        del state["logger"]
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.logger = logging.getLogger(__name__)


class InternalTelemetryDevice(TelemetryDevice):
    internal = True


class SamplerThread(threading.Thread):
    def __init__(self, recorder):
        threading.Thread.__init__(self)
        self.stop = False
        self.recorder = recorder

    def finish(self):
        self.stop = True
        self.join()

    def run(self):
        # noinspection PyBroadException
        try:
            while not self.stop:
                self.recorder.record()
                time.sleep(self.recorder.sample_interval)
        except BaseException:
            logging.getLogger(__name__).exception("Could not determine %s", self.recorder)


class FlightRecorder(TelemetryDevice):
    internal = False
    command = "jfr"
    human_name = "Flight Recorder"
    help = "Enables Java Flight Recorder (requires OpenJDK 11+); injected into SOLR_OPTS."

    def __init__(self, telemetry_params, log_root, java_major_version):
        super().__init__()
        self.telemetry_params = telemetry_params
        self.log_root = log_root
        self.java_major_version = java_major_version

    def instrument_java_opts(self):
        if self.telemetry_params.get("pipeline", "") == "benchmark-only":
            self.logger.warning("jfr: Solr was not provisioned by Solr Benchmark; skipping JFR flags.")
            return []

        io.ensure_dir(self.log_root)
        log_file = os.path.join(self.log_root, "profile.jfr")
        console.info("%s: Writing flight recording to [%s]" % (self.human_name, log_file), logger=self.logger)
        java_opts = self.java_opts(log_file)
        self.logger.info("jfr: Adding JVM arguments: [%s].", java_opts)
        return java_opts

    def java_opts(self, log_file):
        recording_template = self.telemetry_params.get("recording-template")
        java_opts = ["-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints"]
        jfr_cmd = "-XX:StartFlightRecording=maxsize=0,maxage=0s,disk=true,dumponexit=true,filename={}".format(log_file)
        if recording_template:
            self.logger.info("jfr: Using recording template [%s].", recording_template)
            jfr_cmd += ",settings={}".format(recording_template)
        else:
            self.logger.info("jfr: Using default recording template.")
        java_opts.append(jfr_cmd)
        return java_opts


class JitCompiler(TelemetryDevice):
    internal = False
    command = "jit"
    human_name = "JIT Compiler Profiler"
    help = "Enables JIT compiler logs; injected into SOLR_OPTS."

    def __init__(self, log_root, telemetry_params=None):
        super().__init__()
        self.log_root = log_root
        self.telemetry_params = telemetry_params or {}

    def instrument_java_opts(self):
        if self.telemetry_params.get("pipeline", "") == "benchmark-only":
            self.logger.warning("jit: Solr was not provisioned by Solr Benchmark; skipping JIT flags.")
            return []

        io.ensure_dir(self.log_root)
        log_file = os.path.join(self.log_root, "jit.log")
        console.info("%s: Writing JIT compiler log to [%s]" % (self.human_name, log_file), logger=self.logger)
        return ["-XX:+UnlockDiagnosticVMOptions", "-XX:+TraceClassLoading", "-XX:+LogCompilation",
                "-XX:LogFile={}".format(log_file), "-XX:+PrintAssembly"]


class Gc(TelemetryDevice):
    internal = False
    command = "gc"
    human_name = "GC log"
    help = "Enables GC logs (Java 9+ -Xlog: format); injected into SOLR_OPTS."

    def __init__(self, telemetry_params, log_root, java_major_version):
        super().__init__()
        self.telemetry_params = telemetry_params
        self.log_root = log_root
        self.java_major_version = java_major_version

    def instrument_java_opts(self):
        if self.telemetry_params.get("pipeline", "") == "benchmark-only":
            self.logger.warning("gc: Solr was not provisioned by Solr Benchmark; skipping GC flags.")
            return []

        io.ensure_dir(self.log_root)
        log_file = os.path.join(self.log_root, "gc.log")
        console.info("%s: Writing GC log to [%s]" % (self.human_name, log_file), logger=self.logger)
        log_config = self.telemetry_params.get("gc-log-config", "gc*=info,safepoint=info,age*=trace")
        # see https://docs.oracle.com/javase/9/tools/java.htm#JSWOR-GUID-BE93ABDC-999C-4CB5-A88B-1994AAAC74D5
        return [f"-Xlog:{log_config}:file={log_file}:utctime,uptimemillis,level,tags:filecount=0"]


class Heapdump(TelemetryDevice):
    internal = False
    command = "heapdump"
    human_name = "Heap Dump"
    help = "Captures a heap dump from the Solr JVM on benchmark stop."

    def __init__(self, log_root, docker_container=None):
        super().__init__()
        self.log_root = log_root
        self.docker_container = docker_container

    def detach_from_node(self, node, running):
        if running:
            heap_dump_file = os.path.join(self.log_root, "heap_at_exit_{}.hprof".format(node.pid))
            console.info("{}: Writing heap dump to [{}]".format(self.human_name, heap_dump_file), logger=self.logger)
            # noinspection PyBroadException
            try:
                if self.docker_container:
                    cmd = "docker exec {} jmap -dump:format=b,file={} {}".format(
                        self.docker_container, heap_dump_file, node.pid)
                else:
                    cmd = "jmap -dump:format=b,file={} {}".format(heap_dump_file, node.pid)
                if process.run_subprocess_with_logging(cmd):
                    self.logger.warning("Could not write heap dump to [%s]", heap_dump_file)
            except BaseException:
                self.logger.warning("Could not write heap dump to [%s]", heap_dump_file)


class SegmentStats(TelemetryDevice):
    internal = False
    command = "segment-stats"
    human_name = "Segment Stats"
    help = "Captures per-collection segment stats (numDocs, deletedDocs, segmentCount, sizeInBytes) via the Solr Luke API."

    def __init__(self, log_root, admin_client):
        super().__init__()
        self.log_root = log_root
        self.admin_client = admin_client

    def on_benchmark_stop(self):
        # noinspection PyBroadException
        try:
            collections = self.admin_client.list_collections()
            stats_file = os.path.join(self.log_root, "segment_stats.log")
            console.info(f"{self.human_name}: Writing segment stats to [{stats_file}]", logger=self.logger)
            io.ensure_dir(self.log_root)
            with open(stats_file, "wt") as f:
                for coll in collections:
                    try:
                        idx = self.admin_client.get_luke_stats(coll)
                        row = {
                            "collection": coll,
                            "numDocs": idx.get("numDocs"),
                            "maxDoc": idx.get("maxDoc"),
                            "deletedDocs": idx.get("deletedDocs"),
                            "segmentCount": idx.get("segmentCount"),
                            "sizeInBytes": idx.get("sizeInBytes"),
                        }
                        f.write(json.dumps(row) + "\n")
                    except BaseException:
                        self.logger.warning("Could not retrieve Luke stats for collection [%s].", coll)
        except BaseException:
            self.logger.exception("Could not retrieve segment stats.")


class ShardStats(TelemetryDevice):
    """
    Collects per-shard document count and index size for SolrCloud clusters.
    Skipped silently on standalone Solr (no cluster.collections in CLUSTERSTATUS).
    """

    internal = False
    command = "shard-stats"
    human_name = "Shard Stats"
    help = "Regularly samples per-shard document count and index size (SolrCloud only)."

    def __init__(self, telemetry_params, admin_client, metrics_store):
        """
        :param telemetry_params: May optionally specify
            ``shard-stats-sample-interval``: positive integer, seconds between polls. Default: 60.
        :param admin_client: A SolrClient instance used for admin API calls.
        :param metrics_store: The configured metrics store we write to.
        """
        super().__init__()
        self.admin_client = admin_client
        self.metrics_store = metrics_store
        self.sample_interval = telemetry_params.get("shard-stats-sample-interval", 60)
        if self.sample_interval <= 0:
            raise exceptions.SystemSetupError(
                f"The telemetry parameter 'shard-stats-sample-interval' must be greater than zero but was {self.sample_interval}."
            )
        self.samplers = []

    def on_benchmark_start(self):
        # noinspection PyBroadException
        try:
            data = self.admin_client.get_clusterstatus()
        except BaseException:
            self.logger.exception("ShardStats: could not retrieve CLUSTERSTATUS; device will not run.")
            return

        if "cluster" not in data or "collections" not in data.get("cluster", {}):
            self.logger.info("ShardStats: no cluster.collections in CLUSTERSTATUS — skipping (standalone Solr).")
            return

        recorder = ShardStatsRecorder(self.admin_client, self.metrics_store, self.sample_interval)
        sampler = SamplerThread(recorder)
        self.samplers.append(sampler)
        sampler.daemon = True
        sampler.start()

    def on_benchmark_stop(self):
        for sampler in self.samplers:
            sampler.finish()


class ShardStatsRecorder:
    """
    Polls CLUSTERSTATUS and Core STATUS for each shard leader; pushes metrics per shard.
    """

    def __init__(self, admin_client, metrics_store, sample_interval):
        self.admin_client = admin_client
        self.metrics_store = metrics_store
        self.sample_interval = sample_interval
        self.logger = logging.getLogger(__name__)

    def __str__(self):
        return "shard stats"

    def record(self):
        # noinspection PyBroadException
        try:
            data = self.admin_client.get_clusterstatus()
            collections = data.get("cluster", {}).get("collections", {})
        except BaseException:
            self.logger.exception("ShardStats: could not retrieve CLUSTERSTATUS.")
            return

        for _coll_name, coll_data in collections.items():
            shards = coll_data.get("shards", {})
            for shard_name, shard_data in shards.items():
                replicas = shard_data.get("replicas", {})
                for _replica_key, replica in replicas.items():
                    if replica.get("state") == "active" and replica.get("leader") == "true":
                        core_name = replica.get("core")
                        if not core_name:
                            continue
                        # noinspection PyBroadException
                        try:
                            core_status = self.admin_client.get_core_status(core_name)
                            idx = core_status.get("index", {})
                            num_docs = idx.get("numDocs", 0)
                            size_bytes = idx.get("sizeInBytes", 0)
                            self.metrics_store.put_value_cluster_level(
                                f"shard_{shard_name}_num_docs", num_docs, "")
                            self.metrics_store.put_value_cluster_level(
                                f"shard_{shard_name}_size_bytes", size_bytes, "byte")
                        except BaseException:
                            self.logger.warning("ShardStats: could not get core STATUS for [%s].", core_name)
                        break  # only need the leader replica per shard

class StartupTime(InternalTelemetryDevice):
    def __init__(self, stopwatch=time.StopWatch):
        super().__init__()
        self.timer = stopwatch()

    def on_pre_node_start(self, node_name):
        self.timer.start()

    def attach_to_node(self, node):
        self.timer.stop()

    def store_system_metrics(self, node, metrics_store):
        metrics_store.put_value_node_level(node.node_name, "node_startup_time", self.timer.total_time(), "s")


class DiskIo(InternalTelemetryDevice):
    """
    Gathers disk I/O stats.
    """
    def __init__(self, node_count_on_host):
        super().__init__()
        self.node_count_on_host = node_count_on_host
        self.read_bytes = None
        self.write_bytes = None

    def attach_to_node(self, node):
        os_process = sysstats.setup_process_stats(node.pid)
        process_start = sysstats.process_io_counters(os_process)
        if process_start:
            self.read_bytes = process_start.read_bytes
            self.write_bytes = process_start.write_bytes
            self.logger.info("Using more accurate process-based I/O counters.")
        else:
            # noinspection PyBroadException
            try:
                disk_start = sysstats.disk_io_counters()
                self.read_bytes = disk_start.read_bytes
                self.write_bytes = disk_start.write_bytes
                self.logger.warning("Process I/O counters are not supported on this platform. Falling back to less "
                                    "accurate disk I/O counters.")
            except BaseException:
                self.logger.exception("Could not determine I/O stats at benchmark start.")

    def detach_from_node(self, node, running):
        if running:
            # Be aware the semantics of write counts etc. are different for disk and process statistics.
            # Thus we're conservative and only publish I/O bytes now.
            # noinspection PyBroadException
            try:
                os_process = sysstats.setup_process_stats(node.pid)
                process_end = sysstats.process_io_counters(os_process)
                # we have process-based disk counters, no need to worry how many nodes are on this host
                if process_end:
                    self.read_bytes = process_end.read_bytes - self.read_bytes
                    self.write_bytes = process_end.write_bytes - self.write_bytes
                else:
                    disk_end = sysstats.disk_io_counters()
                    if self.node_count_on_host > 1:
                        self.logger.info("There are [%d] nodes on this host and ASB fell back to disk I/O counters. "
                                         "Attributing [1/%d] of total I/O to [%s].",
                                         self.node_count_on_host, self.node_count_on_host, node.node_name)

                    self.read_bytes = (disk_end.read_bytes - self.read_bytes) // self.node_count_on_host
                    self.write_bytes = (disk_end.write_bytes - self.write_bytes) // self.node_count_on_host
            # Catching RuntimeException is not sufficient: psutil might raise AccessDenied (derived from Exception)
            except BaseException:
                self.logger.exception("Could not determine I/O stats at benchmark end.")
                # reset all counters so we don't attempt to write inconsistent numbers to the metrics store later on
                self.read_bytes = None
                self.write_bytes = None

    def store_system_metrics(self, node, metrics_store):
        if self.write_bytes is not None:
            metrics_store.put_value_node_level(node.node_name, "disk_io_write_bytes", self.write_bytes, "byte")
        if self.read_bytes is not None:
            metrics_store.put_value_node_level(node.node_name, "disk_io_read_bytes", self.read_bytes, "byte")


def store_node_attribute_metadata(metrics_store, nodes_info):
    # push up all node level attributes to cluster level iff the values are identical for all nodes
    pseudo_cluster_attributes = {}
    for node in nodes_info:
        if "attributes" in node:
            for k, v in node["attributes"].items():
                attribute_key = "attribute_%s" % str(k)
                metrics_store.add_meta_info(metrics.MetaInfoScope.node, node["name"], attribute_key, v)
                if attribute_key not in pseudo_cluster_attributes:
                    pseudo_cluster_attributes[attribute_key] = set()
                pseudo_cluster_attributes[attribute_key].add(v)

    for k, v in pseudo_cluster_attributes.items():
        if len(v) == 1:
            metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, k, next(iter(v)))


def store_plugin_metadata(metrics_store, nodes_info):
    # push up all plugins to cluster level iff all nodes have the same ones
    all_nodes_plugins = []
    all_same = False

    for node in nodes_info:
        plugins = [p["name"] for p in extract_value(node, ["plugins"], fallback=[]) if "name" in p]
        if not all_nodes_plugins:
            all_nodes_plugins = plugins.copy()
            all_same = True
        else:
            # order does not matter so we do a set comparison
            all_same = all_same and set(all_nodes_plugins) == set(plugins)

        if plugins:
            metrics_store.add_meta_info(metrics.MetaInfoScope.node, node["name"], "plugins", plugins)

    if all_same and all_nodes_plugins:
        metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "plugins", all_nodes_plugins)


def extract_value(node, path, fallback="unknown"):
    value = node
    try:
        for k in path:
            value = value[k]
    except KeyError:
        value = fallback
    return value


class ClusterEnvironmentInfo(TelemetryDevice):
    """
    Gathers static environment information on a cluster level (Solr version, JVM, CPU).
    Called once at benchmark start; stores results as run metadata.
    """
    internal = False
    command = "cluster-environment-info"
    human_name = "Cluster Environment Info"
    help = "Stores Solr version, JVM version, and CPU core count as benchmark metadata."

    def __init__(self, admin_client, metrics_store):
        super().__init__()
        self.admin_client = admin_client
        self.metrics_store = metrics_store

    def on_benchmark_start(self):
        # noinspection PyBroadException
        try:
            resp = self.admin_client.raw_request("GET", "/api/node/system")
            resp.raise_for_status()
            data = resp.json()
        except BaseException:
            self.logger.exception("ClusterEnvironmentInfo: could not retrieve /api/node/system")
            return

        lucene = data.get("lucene", {})
        jvm = data.get("jvm", {})
        system = data.get("system", {})
        distribution_version = lucene.get("solr-spec-version", "unknown")
        jvm_version = jvm.get("version", "unknown")
        jvm_vendor = jvm.get("name", "unknown")
        cpu_logical_cores = system.get("availableProcessors", -1)

        self.metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "distribution_version", distribution_version)
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "jvm_version", jvm_version)
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "jvm_vendor", jvm_vendor)
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "cpu_logical_cores", cpu_logical_cores)

        # noinspection PyBroadException
        try:
            cs_resp = self.admin_client.raw_request("GET", "/solr/admin/collections?action=CLUSTERSTATUS&wt=json")
            cs_resp.raise_for_status()
            cluster = cs_resp.json().get("cluster", {})
            live_nodes = cluster.get("liveNodes", [])
            self.metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "cluster_node_count", len(live_nodes))
        except BaseException:
            self.logger.warning("ClusterEnvironmentInfo: could not retrieve CLUSTERSTATUS node count.")


def add_metadata_for_node(metrics_store, node_name, host_name):
    """
    Gathers static environment information like OS or CPU details for benchmark-provisioned nodes.
    """
    metrics_store.add_meta_info(metrics.MetaInfoScope.node, node_name, "os_name", sysstats.os_name())
    metrics_store.add_meta_info(metrics.MetaInfoScope.node, node_name, "os_version", sysstats.os_version())
    metrics_store.add_meta_info(metrics.MetaInfoScope.node, node_name, "cpu_logical_cores", sysstats.logical_cpu_cores())
    metrics_store.add_meta_info(metrics.MetaInfoScope.node, node_name, "cpu_physical_cores", sysstats.physical_cpu_cores())
    metrics_store.add_meta_info(metrics.MetaInfoScope.node, node_name, "cpu_model", sysstats.cpu_model())
    metrics_store.add_meta_info(metrics.MetaInfoScope.node, node_name, "node_name", node_name)
    metrics_store.add_meta_info(metrics.MetaInfoScope.node, node_name, "host_name", host_name)



class IndexSize(InternalTelemetryDevice):
    """
    Measures the final size of the index
    """
    def __init__(self, data_paths):
        super().__init__()
        self.data_paths = data_paths
        self.attached = False
        self.index_size_bytes = None

    def attach_to_node(self, node):
        self.attached = True

    def detach_from_node(self, node, running):
        # we need to gather the file size after the node has terminated so we can be sure that it has written all its buffers.
        if not running and self.attached and self.data_paths:
            self.attached = False
            index_size_bytes = 0
            for data_path in self.data_paths:
                index_size_bytes += io.get_size(data_path)
            self.index_size_bytes = index_size_bytes

    def store_system_metrics(self, node, metrics_store):
        if self.index_size_bytes:
            metrics_store.put_value_node_level(node.node_name, "final_index_size_bytes", self.index_size_bytes, "byte")


# ===========================================================================
# Solr telemetry devices
# ===========================================================================

# ---------------------------------------------------------------------------
# Prometheus text format parser (shared with runner.py)
# ---------------------------------------------------------------------------

def _parse_prometheus_text(text: str) -> dict:
    """
    Parse Prometheus exposition text format into a flat dict of {metric_name: float}.

    Lines starting with '#' are comments/help/type headers and are skipped.
    Handles optional labels: metric_name{label="value"} value [timestamp]

    When multiple series share the same base metric name (different labels),
    values are accumulated (summed).
    """
    parsed_metrics = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name_part = parts[0]
        try:
            value = float(parts[1])
        except ValueError:
            continue
        base_name = re.sub(r"\{[^}]*\}", "", name_part)
        parsed_metrics[base_name] = parsed_metrics.get(base_name, 0.0) + value
    return parsed_metrics


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class SolrTelemetryDevice(TelemetryDevice):
    """
    Abstract base for Solr telemetry polling devices.

    Extends TelemetryDevice so that Solr devices integrate seamlessly with
    the existing Telemetry wrapper. Setting ``internal = True`` means the
    device is always enabled (not filtered by the ``--telemetry`` flag).

    Subclasses implement `_collect()` which is called periodically on a
    background thread between `on_benchmark_start()` and `on_benchmark_stop()`.
    """

    internal = True
    command = None
    human_name = "Solr Telemetry"
    help = "Solr-specific background polling telemetry device."

    def __init__(self, admin_client, metrics_store, sample_interval_s: float = 5.0):
        super().__init__()
        self._client = admin_client
        self._metrics_store = metrics_store
        self._sample_interval = sample_interval_s
        self._thread = None
        self._stop_event = threading.Event()

    def on_benchmark_start(self) -> None:
        """Start background polling thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def on_benchmark_stop(self) -> None:
        """Stop background polling thread and flush any remaining metrics."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._sample_interval * 2 + 5)

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._collect()
            except Exception as exc:
                logging.getLogger(__name__).warning("%s: collection error: %s", self.__class__.__name__, exc)
            self._stop_event.wait(self._sample_interval)

    @abstractmethod
    def _collect(self) -> None:
        """Collect metrics and store them via self._metrics_store."""

    # ------------------------------------------------------------------
    # Dual-format helpers
    # ------------------------------------------------------------------

    def _fetch_node_metrics_parsed(self):
        """
        Fetch /admin/metrics and return ``(format_str, data_dict)``.

        ``format_str`` is ``"json"`` or ``"prometheus"``.
        """
        raw = self._client.get_node_metrics()
        if isinstance(raw, str):
            return "prometheus", _parse_prometheus_text(raw)
        return "json", raw if isinstance(raw, dict) else {}

    @staticmethod
    def _get_metric_json(data: dict, *keys, default=None):
        """Navigate a nested dict using successive key lookups."""
        current = data
        for key in keys:
            if not isinstance(current, dict):
                return default
            current = current.get(key)
            if current is None:
                return default
        return current

    @staticmethod
    def _get_metric_prometheus(data: dict, metric_name: str, default=None):
        """Look up a metric by exact base name from a parsed Prometheus dict."""
        return data.get(metric_name, default)

    def _put(self, name: str, value, unit: str, task: str = "", meta: dict = None) -> None:
        """Write a single metric to the metrics store."""
        if not hasattr(self._metrics_store, "put_value_cluster_level"):
            self._metrics_store[name] = {"value": value, "unit": unit}
            return
        self._metrics_store.put_value_cluster_level(
            name=name, value=value, unit=unit,
            task=task, operation_type="telemetry",
            meta_data=meta or {},
        )


# ---------------------------------------------------------------------------
# Device: SolrJvmStats
# ---------------------------------------------------------------------------

class SolrJvmStats(SolrTelemetryDevice):
    """
    Collect JVM heap, GC, thread, and buffer pool metrics from Solr.

    Metrics: jvm_heap_used_bytes, jvm_heap_max_bytes, jvm_gc_count, jvm_gc_time_ms,
             jvm_gc_young_count, jvm_gc_young_time_ms, jvm_gc_old_count, jvm_gc_old_time_ms,
             jvm_thread_count, jvm_thread_peak_count, jvm_buffer_pool_direct_bytes,
             jvm_buffer_pool_mapped_bytes
    """

    human_name = "Solr JVM Stats"
    help = "JVM heap, GC (total/young/old), threads, and buffer pool metrics"

    def _collect(self) -> None:
        fmt, data = self._fetch_node_metrics_parsed()
        if fmt == "prometheus":
            self._collect_prometheus(data)
        else:
            self._collect_json(data)

    def _collect_json(self, data: dict) -> None:
        jvm = self._get_metric_json(data, "metrics", "solr.jvm") or {}

        heap_used = jvm.get("memory.heap.used")
        heap_max = jvm.get("memory.heap.max")
        if heap_used is not None:
            self._put("jvm_heap_used_bytes", heap_used, "bytes")
        if heap_max is not None:
            self._put("jvm_heap_max_bytes", heap_max, "bytes")

        thread_count = jvm.get("threads.count")
        thread_peak = jvm.get("threads.peak.count")
        if thread_count is not None:
            self._put("jvm_thread_count", thread_count, "")
        if thread_peak is not None:
            self._put("jvm_thread_peak_count", thread_peak, "")

        direct_bytes = jvm.get("buffers.direct.MemoryUsed")
        mapped_bytes = jvm.get("buffers.mapped.MemoryUsed")
        if direct_bytes is not None:
            self._put("jvm_buffer_pool_direct_bytes", direct_bytes, "bytes")
        if mapped_bytes is not None:
            self._put("jvm_buffer_pool_mapped_bytes", mapped_bytes, "bytes")

        gc_count_total = None
        gc_time_total = None
        gc_young_count = None
        gc_young_time = None
        gc_old_count = None
        gc_old_time = None

        for k, v in jvm.items():
            if v is None:
                continue
            if k.endswith(".count") and "gc." in k:
                gc_count_total = (gc_count_total or 0) + v
                k_lower = k.lower()
                if "young" in k_lower or "minor" in k_lower or "eden" in k_lower:
                    gc_young_count = (gc_young_count or 0) + v
                elif "old" in k_lower or "major" in k_lower or "tenured" in k_lower:
                    gc_old_count = (gc_old_count or 0) + v
            if k.endswith(".time") and "gc." in k:
                gc_time_total = (gc_time_total or 0) + v
                k_lower = k.lower()
                if "young" in k_lower or "minor" in k_lower or "eden" in k_lower:
                    gc_young_time = (gc_young_time or 0) + v
                elif "old" in k_lower or "major" in k_lower or "tenured" in k_lower:
                    gc_old_time = (gc_old_time or 0) + v

        if gc_count_total is not None:
            self._put("jvm_gc_count", gc_count_total, "")
        if gc_time_total is not None:
            self._put("jvm_gc_time_ms", gc_time_total, "ms")
        if gc_young_count is not None:
            self._put("jvm_gc_young_count", gc_young_count, "")
        if gc_young_time is not None:
            self._put("jvm_gc_young_time_ms", gc_young_time, "ms")
        if gc_old_count is not None:
            self._put("jvm_gc_old_count", gc_old_count, "")
        if gc_old_time is not None:
            self._put("jvm_gc_old_time_ms", gc_old_time, "ms")

    def _collect_prometheus(self, data: dict) -> None:
        mapping = {
            "jvm_memory_heap_used_bytes": ("jvm_heap_used_bytes", "bytes"),
            "jvm_memory_heap_max_bytes": ("jvm_heap_max_bytes", "bytes"),
            "jvm_gc_collection_count": ("jvm_gc_count", ""),
            "jvm_gc_collection_time_ms": ("jvm_gc_time_ms", "ms"),
            "jvm_threads_current": ("jvm_thread_count", ""),
            "jvm_threads_peak": ("jvm_thread_peak_count", ""),
            "jvm_buffer_pool_used_bytes": ("jvm_buffer_pool_direct_bytes", "bytes"),
        }
        for prom_name, (osb_name, unit) in mapping.items():
            val = self._get_metric_prometheus(data, prom_name)
            if val is not None:
                self._put(osb_name, val, unit)


# ---------------------------------------------------------------------------
# Device: SolrNodeStats
# ---------------------------------------------------------------------------

class SolrNodeStats(SolrTelemetryDevice):
    """
    Collect OS, file-descriptor, HTTP, and query-handler metrics from Solr.

    Metrics: cpu_usage_percent, os_memory_free_bytes, node_file_descriptors_open,
             node_file_descriptors_max, node_http_requests_total,
             query_handler_requests_total, query_handler_errors_total,
             query_handler_avg_latency_ms
    """

    human_name = "Solr Node Stats"
    help = "CPU usage, OS memory, file descriptors, HTTP requests, and query handler latency"

    def _collect(self) -> None:
        self._collect_system_stats()
        self._collect_metrics_stats()

    def _collect_system_stats(self) -> None:
        try:
            resp = self._client._get("/api/node/system")
            system = resp.json()
            os_data = system.get("system", {})

            cpu = os_data.get("processCpuLoad") or os_data.get("systemCpuLoad")
            if cpu is not None:
                self._put("cpu_usage_percent", cpu * 100.0, "%")

            free_mem = os_data.get("freePhysicalMemorySize")
            if free_mem is not None:
                self._put("os_memory_free_bytes", free_mem, "bytes")

            open_fds = os_data.get("openFileDescriptorCount")
            max_fds = os_data.get("maxFileDescriptorCount")
            if open_fds is not None:
                self._put("node_file_descriptors_open", open_fds, "")
            if max_fds is not None:
                self._put("node_file_descriptors_max", max_fds, "")
        except Exception as exc:
            logging.getLogger(__name__).debug("SolrNodeStats: /api/node/system error: %s", exc)

    def _collect_metrics_stats(self) -> None:
        try:
            fmt, data = self._fetch_node_metrics_parsed()
            if fmt == "prometheus":
                self._collect_metrics_prometheus(data)
            else:
                self._collect_metrics_json(data)
        except Exception as exc:
            logging.getLogger(__name__).debug("SolrNodeStats: metrics error: %s", exc)

    def _collect_metrics_json(self, data: dict) -> None:
        core = self._get_metric_json(data, "metrics", "solr.core") or {}

        requests = core.get("QUERY./select.requests")
        errors = core.get("QUERY./select.errors")
        avg_latency = core.get("QUERY./select.requestTimes.mean")

        if requests is not None:
            self._put("query_handler_requests_total", requests, "")
        if errors is not None:
            self._put("query_handler_errors_total", errors, "")
        if avg_latency is not None:
            self._put("query_handler_avg_latency_ms", avg_latency, "ms")

        jetty = self._get_metric_json(data, "metrics", "solr.jetty") or {}
        http_requests = jetty.get(
            "org.eclipse.jetty.server.handler.StatisticsHandler.requests"
        )
        if http_requests is not None:
            self._put("node_http_requests_total", http_requests, "")

    def _collect_metrics_prometheus(self, data: dict) -> None:
        mapping = {
            "solr_metrics_core_query_requests_total": ("query_handler_requests_total", ""),
            "solr_metrics_core_query_errors_total": ("query_handler_errors_total", ""),
            "solr_metrics_core_query_request_times_mean_ms": ("query_handler_avg_latency_ms", "ms"),
            "solr_metrics_jetty_requests_total": ("node_http_requests_total", ""),
        }
        for prom_name, (osb_name, unit) in mapping.items():
            val = self._get_metric_prometheus(data, prom_name)
            if val is not None:
                self._put(osb_name, val, unit)


# ---------------------------------------------------------------------------
# Device: SolrCollectionStats
# ---------------------------------------------------------------------------

class SolrCollectionStats(SolrTelemetryDevice):
    """
    Collect per-collection document count, index size, segment count, and deleted docs.

    Metrics (per collection): num_docs, index_size_bytes, segment_count, num_deleted_docs
    """

    human_name = "Solr Collection Stats"
    help = "Per-collection: doc count, deleted docs, index size, and segment count (30 s interval)"

    def __init__(self, admin_client, metrics_store,
                 collections: list = None, sample_interval_s: float = 30.0):
        super().__init__(admin_client, metrics_store, sample_interval_s)
        self._collections = collections

    def _collect(self) -> None:
        try:
            cluster = self._client.get_cluster_status()
            col_state = cluster.get("collections", {})
            target_collections = self._collections or list(col_state.keys())

            for col_name in target_collections:
                self._collect_collection(col_name)
        except Exception as exc:
            logging.getLogger(__name__).debug("SolrCollectionStats: cluster status error: %s", exc)

    def _collect_collection(self, collection: str) -> None:
        try:
            resp = self._client._get(f"/api/collections/{collection}/core-properties")
            data = resp.json()
            num_docs = 0
            index_size = 0
            for _core_name, props in data.get("core-properties", {}).items():
                num_docs += props.get("numDocs", 0)
                index_size += props.get("indexHeapUsageBytes", 0)

            self._put("num_docs", num_docs, "docs", meta={"collection": collection})
            if index_size:
                self._put("index_size_bytes", index_size, "bytes",
                          meta={"collection": collection})
        except Exception:
            pass

        self._fetch_luke_stats(collection)

    def _fetch_luke_stats(self, collection: str) -> None:
        try:
            resp = self._client._get(
                f"/solr/{collection}/admin/luke?numTerms=0&wt=json"
            )
            info = resp.json().get("index", {})
            num_docs = info.get("numDocs")
            deleted_docs = info.get("deletedDocs") or info.get("numDeletedDocs")
            segment_count = info.get("segmentCount")

            if num_docs is not None:
                self._put("num_docs", num_docs, "docs", meta={"collection": collection})
            if deleted_docs is not None:
                self._put("num_deleted_docs", deleted_docs, "docs",
                          meta={"collection": collection})
            if segment_count is not None:
                self._put("segment_count", segment_count, "",
                          meta={"collection": collection})
        except Exception as exc:
            logging.getLogger(__name__).debug("SolrCollectionStats: luke fallback failed for %s: %s",
                         collection, exc)


# ---------------------------------------------------------------------------
# Device: SolrQueryStats
# ---------------------------------------------------------------------------

class SolrQueryStats(SolrTelemetryDevice):
    """
    Collect query latency percentiles and cache hit ratio metrics from Solr.

    Metrics: query_latency_p50_ms, query_latency_p99_ms, query_latency_p999_ms,
             query_requests_total, query_errors_total, query_cache_hit_ratio
    """

    human_name = "Solr Query Stats"
    help = "Query latency percentiles (p50/p99/p999), cache hit ratio, request and error totals"

    def _collect(self) -> None:
        fmt, data = self._fetch_node_metrics_parsed()
        if fmt == "prometheus":
            self._collect_prometheus(data)
        else:
            self._collect_json(data)

    def _collect_json(self, data: dict) -> None:
        core = self._get_metric_json(data, "metrics", "solr.core") or {}

        mappings = [
            ("QUERY./select.requestTimes.p_50", "query_latency_p50_ms", "ms"),
            ("QUERY./select.requestTimes.p_99", "query_latency_p99_ms", "ms"),
            ("QUERY./select.requestTimes.p_99_9", "query_latency_p999_ms", "ms"),
            ("QUERY./select.requests", "query_requests_total", ""),
            ("QUERY./select.errors", "query_errors_total", ""),
            ("CACHE.searcher.filterCache.hitratio", "query_cache_hit_ratio", ""),
        ]
        for json_key, osb_name, unit in mappings:
            val = core.get(json_key)
            if val is None and json_key.endswith("p_99_9"):
                val = core.get(json_key.replace("p_99_9", "p_999"))
            if val is not None:
                self._put(osb_name, val, unit)

    def _collect_prometheus(self, data: dict) -> None:
        mapping = {
            "solr_metrics_core_query_request_times_p50_ms": ("query_latency_p50_ms", "ms"),
            "solr_metrics_core_query_request_times_p99_ms": ("query_latency_p99_ms", "ms"),
            "solr_metrics_core_query_request_times_p999_ms": ("query_latency_p999_ms", "ms"),
            "solr_metrics_core_query_requests_total": ("query_requests_total", ""),
            "solr_metrics_core_query_errors_total": ("query_errors_total", ""),
            "solr_metrics_core_cache_hitratio": ("query_cache_hit_ratio", ""),
        }
        for prom_name, (osb_name, unit) in mapping.items():
            val = self._get_metric_prometheus(data, prom_name)
            if val is not None:
                self._put(osb_name, val, unit)


# ---------------------------------------------------------------------------
# Device: SolrIndexingStats
# ---------------------------------------------------------------------------

class SolrIndexingStats(SolrTelemetryDevice):
    """
    Collect indexing throughput and merge metrics from Solr.

    Metrics: indexing_requests_total, indexing_errors_total, indexing_avg_time_ms,
             index_merge_major_running, index_merge_minor_running
    """

    human_name = "Solr Indexing Stats"
    help = "Indexing request counts, average indexing time, and major/minor merge activity"

    def _collect(self) -> None:
        fmt, data = self._fetch_node_metrics_parsed()
        if fmt == "prometheus":
            self._collect_prometheus(data)
        else:
            self._collect_json(data)

    def _collect_json(self, data: dict) -> None:
        core = self._get_metric_json(data, "metrics", "solr.core") or {}

        mappings = [
            ("UPDATE./update.requests", "indexing_requests_total", ""),
            ("UPDATE./update.errors", "indexing_errors_total", ""),
            ("UPDATE./update.requestTimes.mean", "indexing_avg_time_ms", "ms"),
            ("INDEX.merge.major.running", "index_merge_major_running", ""),
            ("INDEX.merge.minor.running", "index_merge_minor_running", ""),
        ]
        for json_key, osb_name, unit in mappings:
            val = core.get(json_key)
            if val is not None:
                self._put(osb_name, val, unit)

    def _collect_prometheus(self, data: dict) -> None:
        mapping = {
            "solr_metrics_core_update_requests_total": ("indexing_requests_total", ""),
            "solr_metrics_core_update_errors_total": ("indexing_errors_total", ""),
            "solr_metrics_core_update_request_times_mean_ms": ("indexing_avg_time_ms", "ms"),
            "solr_metrics_core_index_merge_major_running": ("index_merge_major_running", ""),
            "solr_metrics_core_index_merge_minor_running": ("index_merge_minor_running", ""),
        }
        for prom_name, (osb_name, unit) in mapping.items():
            val = self._get_metric_prometheus(data, prom_name)
            if val is not None:
                self._put(osb_name, val, unit)


# ---------------------------------------------------------------------------
# Device: SolrCacheStats
# ---------------------------------------------------------------------------

class SolrCacheStats(SolrTelemetryDevice):
    """
    Collect Solr internal cache statistics for the three primary caches.

    Metrics (per cache): cache_hits_total, cache_inserts_total, cache_evictions_total,
                         cache_memory_bytes, cache_hit_ratio
    """

    human_name = "Solr Cache Stats"
    help = "Per-cache hits, inserts, evictions, memory, and hit ratio (query/filter/document caches)"

    CACHE_NAMES = ["queryResultCache", "filterCache", "documentCache"]

    def _collect(self) -> None:
        fmt, data = self._fetch_node_metrics_parsed()
        if fmt == "prometheus":
            self._collect_prometheus(data)
        else:
            self._collect_json(data)

    def _collect_json(self, data: dict) -> None:
        core = self._get_metric_json(data, "metrics", "solr.core") or {}

        for cache_name in self.CACHE_NAMES:
            prefix = f"CACHE.searcher.{cache_name}."
            hits = core.get(f"{prefix}hits")
            inserts = core.get(f"{prefix}inserts")
            evictions = core.get(f"{prefix}evictions")
            ram_bytes = core.get(f"{prefix}ramBytesUsed")
            hitratio = core.get(f"{prefix}hitratio")

            meta = {"cache": cache_name}
            if hits is not None:
                self._put("cache_hits_total", hits, "", meta=meta)
            if inserts is not None:
                self._put("cache_inserts_total", inserts, "", meta=meta)
            if evictions is not None:
                self._put("cache_evictions_total", evictions, "", meta=meta)
            if ram_bytes is not None:
                self._put("cache_memory_bytes", ram_bytes, "bytes", meta=meta)
            if hitratio is not None:
                self._put("cache_hit_ratio", hitratio, "", meta=meta)

    def _collect_prometheus(self, data: dict) -> None:
        aggregate_mappings = {
            "solr_metrics_core_cache_hits_total": ("cache_hits_total", ""),
            "solr_metrics_core_cache_inserts_total": ("cache_inserts_total", ""),
            "solr_metrics_core_cache_evictions_total": ("cache_evictions_total", ""),
            "solr_metrics_core_cache_ram_bytes_used": ("cache_memory_bytes", "bytes"),
            "solr_metrics_core_cache_hitratio": ("cache_hit_ratio", ""),
        }
        for prom_name, (osb_name, unit) in aggregate_mappings.items():
            val = self._get_metric_prometheus(data, prom_name)
            if val is not None:
                self._put(osb_name, val, unit, meta={"cache": "aggregate"})
