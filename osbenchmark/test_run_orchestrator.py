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

import collections
import glob
import logging
import os
import sys
import tarfile
import time

import tabulate
import thespian.actors

from osbenchmark import actor, config, doc_link, \
    worker_coordinator, exceptions, builder, metrics, \
        publisher, workload, version, PROGRAM_NAME
from osbenchmark.builder import cluster_config as cc_module
from osbenchmark.builder.supplier import SourceRepository, Builder
from osbenchmark.builder.solr_provisioner import SolrProvisioner, SolrDockerLauncher
from osbenchmark.utils import console, opts, versions


pipelines = collections.OrderedDict()


class Pipeline:
    """
    Describes a whole test run pipeline. A pipeline can consist of one or more steps. Each pipeline should contain roughly of the following
    steps:

    * Prepare the benchmark candidate: It can build Solr from sources, download a ZIP from somewhere etc.
    * Launch the benchmark candidate: This can be done directly, with tools like Ansible or it can assume the candidate is already launched
    * Run the benchmark
    * Publish results
    """

    def __init__(self, name, description, target, stable=True):
        """
        Creates a new pipeline.

        :param name: A short name of the pipeline. This name will be used to reference it from the command line.
        :param description: A human-readable description what the pipeline does.
        :param target: A function that implements this pipeline
        :param stable True iff the pipeline is considered production quality.
        """
        self.name = name
        self.description = description
        self.target = target
        self.stable = stable
        pipelines[name] = self

    def __call__(self, cfg):
        self.target(cfg)


class Setup:
    def __init__(self, cfg, sources=False, distribution=False, external=False, docker=False):
        self.cfg = cfg
        self.sources = sources
        self.distribution = distribution
        self.external = external
        self.docker = docker


class Success:
    pass


class BenchmarkActor(actor.BenchmarkActor):
    def __init__(self):
        super().__init__()
        self.cfg = None
        self.start_sender = None
        self.builder = None
        self.main_worker_coordinator = None
        self.coordinator = None

    def receiveMsg_PoisonMessage(self, msg, sender):
        self.logger.info("BenchmarkActor got notified of poison message [%s] (forwarding).", (str(msg)))
        if self.coordinator:
            self.coordinator.error = True
        self.send(self.start_sender, msg)

    def receiveUnrecognizedMessage(self, msg, sender):
        self.logger.info("BenchmarkActor received unknown message [%s] (ignoring).", (str(msg)))

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_Setup(self, msg, sender):
        self.start_sender = sender
        self.cfg = msg.cfg
        self.coordinator = BenchmarkCoordinator(msg.cfg)
        self.coordinator.setup(sources=msg.sources)
        self.logger.info("Asking builder to start the engine.")
        self.builder = self.createActor(builder.BuilderActor, targetActorRequirements={"coordinator": True})
        self.send(self.builder, builder.StartEngine(self.cfg,
                                                      self.coordinator.metrics_store.open_context,
                                                      msg.sources,
                                                      msg.distribution,
                                                      msg.external,
                                                      msg.docker))

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_EngineStarted(self, msg, sender):
        self.logger.info("Builder has started engine successfully.")
        self.coordinator.test_run.cluster_config_revision = msg.cluster_config_revision
        self.main_worker_coordinator = self.createActor(
            worker_coordinator.WorkerCoordinatorActor,
            targetActorRequirements={"coordinator": True}
            )
        self.logger.info("Telling worker_coordinator to prepare for benchmarking.")
        self.send(self.main_worker_coordinator, worker_coordinator.PrepareBenchmark(self.cfg, self.coordinator.current_workload))

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_PreparationComplete(self, msg, sender):
        self.coordinator.on_preparation_complete(msg.distribution_flavor, msg.distribution_version, msg.revision)
        self.logger.info("Telling worker_coordinator to start benchmark.")
        self.send(self.main_worker_coordinator, worker_coordinator.StartBenchmark())

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_TaskFinished(self, msg, sender):
        self.coordinator.on_task_finished(msg.metrics)
        # We choose *NOT* to reset our own metrics store's timer as this one is only used to collect complete metrics records from
        # other stores (used by worker_coordinator and builder). Hence there is no need to reset the timer in our own metrics store.
        self.send(self.builder, builder.ResetRelativeTime(msg.next_task_scheduled_in))

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_BenchmarkCancelled(self, msg, sender):
        self.coordinator.cancelled = True
        # even notify the start sender if it is the originator. The reason is that we call #ask() which waits for a reply.
        # We also need to ask in order to avoid test_runs between this notification and the following ActorExitRequest.
        self.send(self.start_sender, msg)

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_BenchmarkFailure(self, msg, sender):
        self.logger.info("Received a benchmark failure from [%s] and will forward it now.", sender)
        self.coordinator.error = True
        self.send(self.start_sender, msg)

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_BenchmarkComplete(self, msg, sender):
        self.coordinator.on_benchmark_complete(msg.metrics)
        self.send(self.main_worker_coordinator, thespian.actors.ActorExitRequest())
        self.main_worker_coordinator = None
        self.logger.info("Asking builder to stop the engine.")
        self.send(self.builder, builder.StopEngine())

    @actor.no_retry("test run orchestrator")  # pylint: disable=no-value-for-parameter
    def receiveMsg_EngineStopped(self, msg, sender):
        self.logger.info("Builder has stopped engine successfully.")
        self.send(self.start_sender, Success())


class BenchmarkCoordinator:
    def __init__(self, cfg):
        self.logger = logging.getLogger(__name__)
        self.cfg = cfg
        self.test_run = None
        self.metrics_store = None
        self.test_run_store = None
        self.cancelled = False
        self.error = False
        self.workload_revision = None
        self.current_workload = None
        self.current_test_procedure = None

    def _check_workload_is_solr_native(self):
        """
        Detect whether the workload is in OpenSearch Benchmark format and, if so,
        abort with a clear error instructing the user to run ``convert-workload`` first.

        No automatic conversion is performed. The benchmark runs ONLY against
        Solr-native workloads (those with a ``"collections"`` key in workload.json).

        Works for both --workload-path (explicit local path) and --workload (repository
        workload, where the local cache path is derived from config).
        """
        workload_path = self.cfg.opts("workload", "workload.path", mandatory=False)

        # For repository workloads (--workload=name without --workload-path), derive
        # the local cache path from the standard repository directory layout.
        if not workload_path:
            workload_name = self.cfg.opts("workload", "workload.name", mandatory=False)
            if workload_name:
                root_dir = self.cfg.opts("node", "root.dir")
                repo_dir_name = self.cfg.opts("benchmarks", "workload.repository.dir")
                repo_name = self.cfg.opts("workload", "repository.name", mandatory=False) or "default"
                workload_path = os.path.join(root_dir, repo_dir_name, repo_name, workload_name)

        if not workload_path or not os.path.isdir(workload_path):
            return

        from osbenchmark.conversion.detector import is_opensearch_workload_path
        if is_opensearch_workload_path(workload_path):
            msg = (
                f"This workload is in OpenSearch Benchmark format and cannot be run directly.\n"
                f"Convert it first using:\n\n"
                f"  solr-benchmark convert-workload "
                f"--workload-path {workload_path} "
                f"--output-path {workload_path}-solr\n\n"
                f"Then re-run with --workload-path {workload_path}-solr"
            )
            console.error(msg)
            raise exceptions.SystemSetupError(
                f"OSB workload detected at '{workload_path}' — convert it first with 'solr-benchmark convert-workload'"
            )

    def setup(self, sources=False):
        # to load the workload we need to know the correct cluster distribution version. Usually, this value should be set
        # but there are rare cases (external pipeline and user did not specify the distribution version) where we need
        # to derive it ourselves. For source builds we always assume "master"
        if not sources and not self.cfg.exists("builder", "distribution.version"):
            distribution_version = builder.cluster_distribution_version(self.cfg)
            self.logger.info("Automatically derived distribution version [%s]", distribution_version)
            self.cfg.add(config.Scope.benchmark, "builder", "distribution.version", distribution_version)
            min_solr_version = versions.Version.from_string(version.minimum_solr_version())
            specified_version = versions.Version.from_string(distribution_version)
            if specified_version < min_solr_version:
                raise exceptions.SystemSetupError(f"Cluster version must be at least [{min_solr_version}] but was [{distribution_version}]")

        # Auto-convert OpenSearch workloads to Solr-native format before loading
        self._check_workload_is_solr_native()

        self.current_workload = workload.load_workload(self.cfg)
        self.workload_revision = self.cfg.opts("workload", "repository.revision", mandatory=False)
        test_procedure_name = self.cfg.opts("workload", "test_procedure.name")
        self.current_test_procedure = self.current_workload.find_test_procedure_or_default(test_procedure_name)
        if self.current_test_procedure is None:
            raise exceptions.SystemSetupError(
                "Workload [{}] does not provide test_procedure [{}]. List the available workloads with {} list workloads.".format(
                    self.current_workload.name, test_procedure_name, PROGRAM_NAME))
        if self.current_test_procedure.user_info:
            console.info(self.current_test_procedure.user_info)

        self.test_run = metrics.create_test_run(
            self.cfg, self.current_workload,
            self.current_test_procedure,
            self.workload_revision)

        self.metrics_store = metrics.metrics_store(
            self.cfg,
            workload=self.test_run.workload_name,
            test_procedure=self.test_run.test_procedure_name,
            read_only=False
        )
        self.test_run_store = metrics.test_run_store(self.cfg)

    def on_preparation_complete(self, distribution_flavor, distribution_version, revision):
        self.test_run.distribution_flavor = distribution_flavor
        self.test_run.distribution_version = distribution_version
        self.test_run.revision = revision

        # If version wasn't detected from cluster, try to get it from config
        if not self.test_run.distribution_version:
            self.test_run.distribution_version = self.cfg.opts("builder", "distribution.version", mandatory=False)

        # store test_run initially (without any results) so other components can retrieve full metadata
        self.test_run_store.store_test_run(self.test_run)

        # test_procedure = the specific benchmark scenario within a workload (e.g., "append-no-conflicts")
        # cluster_config = the cluster configuration variant (e.g., "vanilla", "4gheap")
        # pipeline = how the cluster is provisioned (e.g., "docker", "from-sources", "benchmark-only")
        cluster_cfg_display = ", ".join(self.test_run.cluster_config or ["none"])
        if self.test_run.test_procedure.auto_generated:
            console.info("Running benchmark with pipeline [{}], workload [{}], cluster_config [{}], version [{}].\n"
                         .format(self.test_run.pipeline,
                         self.test_run.workload_name,
                         cluster_cfg_display,
                         self.test_run.distribution_version or "unknown"))
        else:
            console.info("Running benchmark with pipeline [{}], workload [{}], test_procedure [{}], cluster_config [{}], version [{}].\n"
                         .format(
                             self.test_run.pipeline,
                             self.test_run.workload_name,
                             self.test_run.test_procedure_name,
                             cluster_cfg_display,
                             self.test_run.distribution_version or "unknown"
                             ))

    def on_task_finished(self, new_metrics):
        self.logger.info("Task has finished.")
        self.logger.info("Bulk adding request metrics to metrics store.")
        self.metrics_store.bulk_add(new_metrics)

    def on_benchmark_complete(self, new_metrics):
        self.logger.info("ASB is complete.")
        self.logger.info("Bulk adding request metrics to metrics store.")
        self.metrics_store.bulk_add(new_metrics)
        self.metrics_store.flush()
        if not self.cancelled and not self.error:
            final_results = metrics.calculate_results(self.metrics_store, self.test_run)
            self.test_run.add_results(final_results)
            self.test_run_store.store_test_run(self.test_run)
            metrics.results_store(self.cfg).store_results(self.test_run)
            publisher.summarize(final_results, self.cfg)
        else:
            self.logger.info("Suppressing output of summary results. Cancelled = [%r], Error = [%r].", self.cancelled, self.error)
        self.metrics_store.close()


def run_test(cfg, sources=False, distribution=False, external=False, docker=False):
    logger = logging.getLogger(__name__)
    # at this point an actor system has to run and we should only join
    actor_system = actor.bootstrap_actor_system(try_join=True)
    try:
        benchmark_actor = actor_system.createActor(BenchmarkActor, targetActorRequirements={"coordinator": True})
    except thespian.actors.ActorSystemRequestTimeout:
        # The actor system may have gone stale after a long provisioning phase (e.g. Gradle build).
        # Shut it down and start a fresh one, falling back to offline mode if TCP fails.
        logger.warning("Actor system became unresponsive (createActor timed out). Restarting actor system.")
        try:
            actor_system.shutdown()
        except Exception:
            pass
        time.sleep(5)
        try:
            actor_system = actor.bootstrap_actor_system(try_join=False, prefer_local_only=True)
        except Exception:
            logger.warning("Could not restart TCP actor system. Falling back to offline actor system.")
            actor.use_offline_actor_system()
            actor_system = actor.bootstrap_actor_system(try_join=False, prefer_local_only=True)
        benchmark_actor = actor_system.createActor(BenchmarkActor, targetActorRequirements={"coordinator": True})
    try:
        result = actor_system.ask(benchmark_actor, Setup(cfg, sources, distribution, external, docker))
        if isinstance(result, Success):
            logger.info("ASB has finished successfully.")
        # may happen if one of the load generators has detected that the user has cancelled the benchmark.
        elif isinstance(result, actor.BenchmarkCancelled):
            logger.info("User has cancelled the benchmark (detected by actor).")
        elif isinstance(result, actor.BenchmarkFailure):
            logger.error("A benchmark failure has occurred")
            raise exceptions.BenchmarkError(result.message, result.cause)
        else:
            raise exceptions.BenchmarkError("Got an unexpected result during benchmarking: [%s]." % str(result))
    except KeyboardInterrupt:
        logger.info("User has cancelled the benchmark (detected by test run orchestrator).")
        # notify the coordinator so it can properly handle this state. Do it blocking so we don't have a test run between this message
        # and the actor exit request.
        actor_system.ask(benchmark_actor, actor.BenchmarkCancelled())
    finally:
        logger.info("Telling benchmark actor to exit.")
        actor_system.tell(benchmark_actor, thespian.actors.ActorExitRequest())


def set_default_hosts(cfg, host="127.0.0.1", port=9200):
    logger = logging.getLogger(__name__)
    configured_hosts = cfg.opts("client", "hosts")
    if len(configured_hosts.default) != 0:
        logger.info("Using configured hosts %s", configured_hosts.default)
    else:
        logger.info("Setting default host to [%s:%d]", host, port)
        default_host_object = opts.TargetHosts("{}:{}".format(host,port))
        cfg.add(config.Scope.benchmark, "client", "hosts", default_host_object)


# Poor man's curry
def benchmark_only(cfg):
    set_default_hosts(cfg)
    return run_test(cfg, external=True)


Pipeline("benchmark-only",
         "Assumes an already running search engine instance, runs a benchmark and publishes results", benchmark_only)


# ---------------------------------------------------------------------------
# Solr-specific pipelines
# ---------------------------------------------------------------------------

def _load_cluster_config(cfg):
    """
    Load the cluster_config instance from the configured INI repository.

    Returns a ClusterConfigInstance whose ``.variables`` dict contains the
    JVM/GC settings (``heap_size``, ``gc_tune``, ``solr_opts``), or ``None``
    if the config path cannot be determined (infrastructure failure) — in which
    case Solr uses its own defaults.

    Raises ``SystemSetupError`` if the user-specified config name is unknown
    (e.g. ``--cluster-config foo`` where ``foo.ini`` does not exist).  This
    error is intentionally NOT caught so the benchmark fails fast with a clear
    message rather than silently proceeding with the wrong configuration.
    """
    _logger = logging.getLogger(__name__)
    names = cfg.opts("builder", "cluster_config.names")
    params = cfg.opts("builder", "cluster_config.params", mandatory=False, default_value={})
    try:
        repo_path = cc_module.cluster_config_path(cfg)
    except Exception as exc:  # pylint: disable=broad-except
        _logger.warning("Could not determine cluster_config path: %s — proceeding without JVM/GC tuning.", exc)
        return None
    # Do NOT catch SystemSetupError here — an unknown config name must fail loudly.
    instance = cc_module.load_cluster_config(repo_path, names, params)
    _logger.info("Loaded cluster_config '%s' with variables: %s", "+".join(names), instance.variables)
    return instance


def solr_from_sources(cfg):
    """
    Clone/update the Solr source tree, build a distribution with Gradle, provision
    it locally, run the benchmark, then tear down.

    Config keys read:
      - builder.source.revision  — git revision to build: "latest" (default), "current",
                                   a branch name, a tag, or a commit SHA.
      - source.remote.repo.url   — Solr git remote (default: https://github.com/apache/solr.git)
      - solr.port                — Solr port (default: 8983)
      - solr.install_dir         — where to extract the built tarball (default: ~/.solr-benchmark/builds)
    """
    logger = logging.getLogger(__name__)
    base_dir = os.path.expanduser("~/.solr-benchmark")

    revision = cfg.opts("builder", "source.revision", mandatory=False, default_value="latest")
    port = int(cfg.opts("solr", "port", mandatory=False, default_value=8983))
    src_dir = os.path.join(base_dir, "sources", "solr")
    install_dir = cfg.opts("solr", "install_dir", mandatory=False,
                           default_value=os.path.join(base_dir, "builds", revision or "latest"))
    log_dir = os.path.join(base_dir, "logs")
    remote_url = cfg.opts("source", "remote.repo.url", mandatory=False,
                          default_value="https://github.com/apache/solr.git")

    # Step 1: Clone / update source tree
    logger.info("Fetching Solr sources at revision [%s] from [%s].", revision, remote_url)
    git_revision = SourceRepository("Solr", remote_url, src_dir).fetch(revision)
    logger.info("Building from git revision [%s].", git_revision)

    # Step 2: Build with Gradle (produces tgz in solr/packaging/build/distributions/)
    logger.info("Building Solr from source in [%s].", src_dir)
    bldr = Builder(src_dir, build_jdk=21, log_dir=log_dir)
    bldr.build(["./gradlew clean", "./gradlew assemble"])

    # Step 3: Locate the built tarball
    pattern = os.path.join(src_dir, "solr", "packaging", "build", "distributions", "solr-*.tgz")
    tarballs = glob.glob(pattern)
    if not tarballs:
        raise exceptions.SystemSetupError(
            f"No Solr tarball found matching {pattern}. "
            f"Check the Gradle build log at {os.path.join(log_dir, 'build.log')}."
        )
    tarball_path = sorted(tarballs)[-1]  # pick the newest if multiple
    logger.info("Using built Solr tarball: %s", tarball_path)

    # Step 4: Extract tarball and start Solr
    os.makedirs(install_dir, exist_ok=True)
    with tarfile.open(tarball_path, "r:gz") as tf:
        top_level = tf.getnames()[0].split("/")[0]
        tf.extractall(install_dir)
    solr_root = os.path.join(install_dir, top_level)

    cc_instance = _load_cluster_config(cfg)
    solr_modules = cfg.opts("solr", "modules", mandatory=False, default_value="")
    provisioner = SolrProvisioner(cache_dir=os.path.join(base_dir, "cache"), port=port,
                                  cluster_config=cc_instance, solr_modules=solr_modules)
    try:
        provisioner.start(solr_root, mode="cloud")
        set_default_hosts(cfg, host="127.0.0.1", port=port)
        run_test(cfg, external=True)
    finally:
        try:
            provisioner.stop(solr_root)
        except Exception as exc:
            logger.warning("Solr stop failed during teardown: %s", exc)
        try:
            provisioner.clean(install_dir)
        except Exception as exc:
            logger.warning("Solr clean failed during teardown: %s", exc)


Pipeline("from-sources",
         "Builds Solr from source (git clone + Gradle assemble), provisions it locally, "
         "runs a benchmark, and tears down.", solr_from_sources)


def solr_from_distribution(cfg):
    """
    Download and provision a local Solr instance, run benchmark, then tear down.

    Defaults to cloud mode (SolrCloud with embedded ZooKeeper).

    Config keys read:
      - distribution.version  — Solr version to download (e.g. "9.7.0")
      - solr.port             — port for the Solr instance (default: 8983)
      - solr.install_dir      — directory for Solr installation (default: ~/.solr-benchmark/installs)
      - solr.cache_dir        — directory for cached tarballs (default: ~/.solr-benchmark/cache)
    """
    logger = logging.getLogger(__name__)
    version_str = cfg.opts("builder", "distribution.version")
    port = int(cfg.opts("solr", "port", mandatory=False, default_value=8983))
    base_dir = os.path.expanduser("~/.solr-benchmark")
    install_dir = cfg.opts("solr", "install_dir", mandatory=False,
                           default_value=os.path.join(base_dir, "installs", version_str))
    cache_dir = cfg.opts("solr", "cache_dir", mandatory=False,
                         default_value=os.path.join(base_dir, "cache"))

    cc_instance = _load_cluster_config(cfg)
    solr_modules = cfg.opts("solr", "modules", mandatory=False, default_value="")
    provisioner = SolrProvisioner(cache_dir=cache_dir, port=port, cluster_config=cc_instance,
                                  solr_modules=solr_modules)
    _tarball = provisioner.download(version_str)
    solr_root = provisioner.install(version_str, install_dir)

    try:
        provisioner.start(solr_root, mode="cloud")
        set_default_hosts(cfg, host="127.0.0.1", port=port)
        run_test(cfg, external=True)
    finally:
        try:
            provisioner.stop(solr_root)
        except Exception as exc:
            logger.warning("Solr stop failed during teardown: %s", exc)
        try:
            provisioner.clean(install_dir)
        except Exception as exc:
            logger.warning("Solr clean failed during teardown: %s", exc)


def _normalize_solr_docker_tag(version: str) -> str:
    """
    Return the Solr Docker image tag for the given distribution version string.

    Solr uses the full version string as the Docker tag (e.g. "9.10.1", "10.0.0-SNAPSHOT").
    A missing or empty version falls back to "9".
    """
    return version if version else "9"


def solr_docker(cfg):
    """
    Start Solr via Docker, run benchmark, then stop the container.

    Defaults to cloud mode (SolrCloud with embedded ZooKeeper).

    Config keys read:
      - builder.distribution.version  — Docker image tag (e.g. "9", "9.7.0", "10")
      - solr.port                     — port mapping (default: 8983)
    """
    raw_version = cfg.opts("builder", "distribution.version", mandatory=False, default_value="9")
    version_tag = _normalize_solr_docker_tag(raw_version)
    port = int(cfg.opts("solr", "port", mandatory=False, default_value=8983))

    cc_instance = _load_cluster_config(cfg)
    solr_modules = cfg.opts("solr", "modules", mandatory=False, default_value="")
    launcher = SolrDockerLauncher(port=port, cluster_config=cc_instance, solr_modules=solr_modules)
    try:
        launcher.start(version_tag=version_tag, mode="cloud")
        set_default_hosts(cfg, host="127.0.0.1", port=port)
        run_test(cfg, external=True)
    finally:
        try:
            launcher.stop()
        except Exception as exc:
            logging.getLogger(__name__).warning("Solr Docker teardown failed: %s", exc)


Pipeline("from-distribution",
         "Downloads a Solr distribution, provisions it locally, runs a benchmark, and tears down.", solr_from_distribution)

Pipeline("docker",
         "Starts Solr via Docker, runs a benchmark, and removes the container on teardown.", solr_docker)


def available_pipelines():
    return [[pipeline.name, pipeline.description] for pipeline in pipelines.values() if pipeline.stable]


def list_pipelines():
    console.println("Available pipelines:\n")
    console.println(tabulate.tabulate(available_pipelines(), headers=["Name", "Description"]))


def run(cfg):
    logger = logging.getLogger(__name__)
    # pipeline is no more mandatory, will default to benchmark-only
    name = cfg.opts("test_run", "pipeline", mandatory=False)
    test_run_id = cfg.opts("system", "test_run.id")
    logger.info("Test run id [%s]", test_run_id)
    if not name:
        # assume from-distribution pipeline if distribution.version has been specified
        if cfg.exists("builder", "distribution.version"):
            name = "from-distribution"
        else:
            name = "benchmark-only"
            logger.info("User did not specify distribution.version or pipeline. Using default pipeline [%s].", name)

        cfg.add(config.Scope.applicationOverride, "test_run", "pipeline", name)
    else:
        logger.info("User specified pipeline [%s].", name)

    if os.environ.get("BENCHMARK_RUNNING_IN_DOCKER", "").upper() == "TRUE":
        # in this case only benchmarking remote Solr clusters makes sense
        if name != "benchmark-only":
            raise exceptions.SystemSetupError(
                "Only the [benchmark-only] pipeline is supported by the Docker image.\n"
                "Add --pipeline=benchmark-only in your arguments and try again.\n"
                "For more details read the docs for the benchmark-only pipeline in {}\n".format(
                    doc_link("")))

    try:
        pipeline = pipelines[name]
    except KeyError:
        raise exceptions.SystemSetupError(
            "Unknown pipeline [%s]. List the available pipelines with %s list pipelines." % (name, PROGRAM_NAME))
    try:
        pipeline(cfg)
    except exceptions.BenchmarkError as e:
        # just pass on our own errors. It should be treated differently on top-level
        raise e
    except KeyboardInterrupt:
        logger.info("User has cancelled the benchmark.")
    except BaseException:
        tb = sys.exc_info()[2]
        raise exceptions.BenchmarkError("This test_run ended with a fatal crash.").with_traceback(tb)
