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

import logging
import os
import subprocess

import psutil

from osbenchmark import time, telemetry
from osbenchmark.builder import java_resolver, cluster
from osbenchmark.builder.launchers.launcher import Launcher
from osbenchmark.exceptions import LaunchError
from osbenchmark.utils import io, opts
from osbenchmark.utils.periodic_waiter import PeriodicWaiter


class LocalProcessLauncher(Launcher):
    PROCESS_WAIT_TIMEOUT_SECONDS = 90
    PROCESS_WAIT_INTERVAL_SECONDS = 0.5

    def __init__(self, cluster_config, shell_executor, metrics_store, clock=time.Clock):
        super().__init__(shell_executor)
        self.logger = logging.getLogger(__name__)
        self.cluster_config = cluster_config
        self.metrics_store = metrics_store
        self.waiter = PeriodicWaiter(LocalProcessLauncher.PROCESS_WAIT_INTERVAL_SECONDS,
                                     LocalProcessLauncher.PROCESS_WAIT_TIMEOUT_SECONDS, clock=clock)

    def start(self, host, node_configurations):
        node_count_on_host = len(node_configurations)
        return [self._start_node(host, node_configuration, node_count_on_host) for node_configuration in node_configurations]

    def _start_node(self, host, node_configuration, node_count_on_host):
        host_name = node_configuration.ip
        node_name = node_configuration.node_name
        binary_path = node_configuration.binary_path

        java_major_version, java_home = java_resolver.java_home(node_configuration.cluster_config_runtime_jdks,
                                                                self.cluster_config.variables["system"]["runtime"]["jdk"])
        self.logger.info("Java major version: %s", java_major_version)
        self.logger.info("Java home: %s", java_home)
        self.logger.info("Starting node [%s].", node_name)

        telemetry = self._prepare_telemetry(node_configuration, node_count_on_host, java_major_version)
        env = self._prepare_env(node_name, java_home, telemetry)
        telemetry.on_pre_node_start(node_name)

        node_pid = self._start_process(host, binary_path, env)
        self.logger.info("Successfully started node [%s] with PID [%s].", node_name, node_pid)
        node = cluster.Node(node_pid, binary_path, host_name, node_name, telemetry)

        self.logger.info("Attaching telemetry devices to node [%s].", node_name)
        telemetry.attach_to_node(node)

        return node

    def _prepare_telemetry(self, node_configuration, node_count_on_host, java_major_version):
        data_paths = node_configuration.data_paths
        node_telemetry_dir = os.path.join(node_configuration.node_root_path, "telemetry")

        enabled_devices = self.cluster_config.variables["telemetry"]["devices"]
        telemetry_params = self.cluster_config.variables["telemetry"]["params"]

        node_telemetry = [
            telemetry.FlightRecorder(telemetry_params, node_telemetry_dir, java_major_version),
            telemetry.JitCompiler(node_telemetry_dir),
            telemetry.Gc(telemetry_params, node_telemetry_dir, java_major_version),
            telemetry.Heapdump(node_telemetry_dir),
            telemetry.DiskIo(node_count_on_host),
            telemetry.IndexSize(data_paths),
            telemetry.StartupTime(),
        ]

        return telemetry.Telemetry(enabled_devices, devices=node_telemetry)

    def _prepare_env(self, node_name, java_home, telemetry):
        env = {k: v for k, v in os.environ.items() if k in
               opts.csv_to_list(self.cluster_config.variables["system"]["env"]["passenv"])}
        if java_home:
            self._set_env(env, "PATH", os.path.join(java_home, "bin"), separator=os.pathsep, prepend=True)
            env["JAVA_HOME"] = java_home
            self.logger.info("JAVA HOME: %s", env["JAVA_HOME"])
        if not env.get("SOLR_JAVA_OPTS"):
            env["SOLR_JAVA_OPTS"] = "-XX:+ExitOnOutOfMemoryError"

        # we just blindly trust telemetry here...
        for jvm_option in telemetry.instrument_candidate_java_opts():
            self._set_env(env, "SOLR_JAVA_OPTS", jvm_option)

        self.logger.debug("env for [%s]: %s", node_name, str(env))
        return env

    def _set_env(self, env, key, value, separator=' ', prepend=False):
        if value is not None:
            if key not in env:
                env[key] = value
            elif prepend:
                env[key] = value + separator + env[key]
            else:
                env[key] = env[key] + separator + value

    def _start_process(self, host, binary_path, env):
        if os.name == "posix" and os.geteuid() == 0:
            raise LaunchError("Cannot launch Solr as root. Please run as a non-root user.")

        cmd = [io.escape_path(os.path.join(binary_path, "bin", "solr"))]
        cmd.append("start")

        # Solr 9.x requires --cloud flag for SolrCloud mode; Solr 10+ uses it by default
        distribution_version = self.cluster_config.variables.get("distribution", {}).get("version")
        if distribution_version is None:
            cmd.append("--cloud")
        else:
            version_parts = str(distribution_version).split("-", maxsplit=1)[0].split(".")
            try:
                if int(version_parts[0]) < 10:
                    cmd.append("--cloud")
            except (ValueError, IndexError):
                cmd.append("--cloud")

        self.shell_executor.execute(host, " ".join(cmd), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, detach=True)

        port = env.get("SOLR_PORT", "8983")
        pid_file_name = io.escape_path(os.path.join(binary_path, "bin", f"solr-{port}.pid"))
        self._wait_for_pid_file(pid_file_name)

        return self._get_pid_from_file(pid_file_name)

    def _wait_for_pid_file(self, pid_file_name):
        self.waiter.wait(self._is_pid_file_available, pid_file_name)

    def _is_pid_file_available(self, pid_file_name):
        try:
            pid = self._get_pid_from_file(pid_file_name)
            return pid != 0
        except (FileNotFoundError, EOFError):
            self.logger.info("PID file %s is not ready", pid_file_name)
            return False

    def _get_pid_from_file(self, pid_file_name):
        with open(pid_file_name, "rb") as f:
            buf = f.read()
            if not buf:
                raise EOFError
            return int(buf)

    def stop(self, host, nodes):
        self.logger.info("Shutting down [%d] nodes on this host.", len(nodes))
        stopped_nodes = []
        for node in nodes:
            node_stopped = self._stop_node(node)
            if node_stopped:
                stopped_nodes.append(node)

        return stopped_nodes

    def _stop_node(self, node):
        node_stopped = False

        if self.metrics_store:
            telemetry.add_metadata_for_node(self.metrics_store, node.node_name, node.host_name)

        node_process = self._get_node_process(node)
        if node_process:
            node.telemetry.detach_from_node(node, running=True)
            node_stopped = self._stop_process(node_process, node)
            node.telemetry.detach_from_node(node, running=False)
        # store system metrics in any case (telemetry devices may derive system metrics while the node is running)
        if self.metrics_store:
            node.telemetry.store_system_metrics(node, self.metrics_store)

        return node_stopped

    def _get_node_process(self, node):
        try:
            return psutil.Process(pid=node.pid)
        except psutil.NoSuchProcess:
            self.logger.warning("No process found with PID [%s] for node [%s].", node.pid, node.node_name)

    def _stop_process(self, node_process, node):
        process_stopped = False

        try:
            node_process.terminate()
            node_process.wait(10.0)
            process_stopped = True
        except psutil.NoSuchProcess:
            self.logger.warning("No process found with PID [%s] for node [%s].", node_process.pid, node.node_name)
        except psutil.TimeoutExpired:
            self.logger.info("kill -KILL node [%s]", node.node_name)
            try:
                # kill -9
                node_process.kill()
                process_stopped = True
            except psutil.NoSuchProcess:
                self.logger.warning("No process found with PID [%s] for node [%s].", node_process.pid, node.node_name)
        self.logger.info("Done shutting down node [%s].", node.node_name)

        return process_stopped
