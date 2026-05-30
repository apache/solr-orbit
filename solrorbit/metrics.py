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
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import collections
import glob
import json
import logging
import math
import os
import pickle
import statistics
import sys
import zlib
import webbrowser
from enum import Enum, IntEnum
import psutil
import tabulate

from solrorbit import time, exceptions, version, paths
from solrorbit.utils import convert, console, io, versions
from solrorbit.visualizations.benchmark_report_renderer import render_results_html


class MetaInfoScope(Enum):
    """
    Defines the scope of a meta-information. Meta-information provides more context for a metric, for example the concrete version
    of OpenSearch that has been benchmarked or environment information like CPU model or OS.
    """

    cluster = 1
    """
    Cluster level meta-information is valid for all nodes in the cluster (e.g. the benchmarked OpenSearch version)
    """
    node = 3
    """
    Node level meta-information is valid for a single node (e.g. GC times)
    """


def calculate_results(store, test_run):
    calc = GlobalStatsCalculator(
        store, test_run.workload, test_run.test_procedure, latency_percentiles=test_run.latency_percentiles, throughput_percentiles=test_run.throughput_percentiles
    )
    return calc()


def calculate_system_results(store, node_name):
    calc = SystemStatsCalculator(store, node_name)
    return calc()


def metrics_store(cfg, read_only=True, workload=None, test_procedure=None, cluster_config=None, meta_info=None):
    """
    Creates a proper metrics store based on the current configuration.

    :param cfg: Config object.
    :param read_only: Whether to open the metrics store only for reading (Default: True).
    :return: A metrics store implementation.
    """
    store_type = cfg.opts("reporting", "datastore.type", mandatory=False, default_value="in-memory")
    cls = FilesystemMetricsStore if store_type == "filesystem" else InMemoryMetricsStore
    store = cls(cfg=cfg, meta_info=meta_info)
    logging.getLogger(__name__).info("Creating %s", str(store))

    test_run_id = cfg.opts("system", "test_run.id")
    test_run_timestamp = cfg.opts("system", "time.start")
    selected_cluster_config = cfg.opts("builder", "cluster_config.names") if cluster_config is None else cluster_config

    store.open(test_run_id, test_run_timestamp, workload, test_procedure, selected_cluster_config, create=not read_only)
    return store


def extract_user_tags_from_config(cfg):
    """
    Extracts user tags into a structured dict

    :param cfg: The current configuration object.
    :return: A dict containing user tags. If no user tags are given, an empty dict is returned.
    """
    user_tags = cfg.opts("test_run", "user.tag", mandatory=False)
    return extract_user_tags_from_string(user_tags)


def extract_user_tags_from_string(user_tags):
    """
    Extracts user tags into a structured dict

    :param user_tags: A string containing user tags (tags separated by comma, key and value separated by colon).
    :return: A dict containing user tags. If no user tags are given, an empty dict is returned.
    """
    user_tags_dict = {}
    if user_tags and user_tags.strip() != "":
        try:
            for user_tag in user_tags.split(","):
                user_tag_key, user_tag_value = user_tag.split(":")
                user_tags_dict[user_tag_key] = user_tag_value
        except ValueError:
            msg = "User tag keys and values have to separated by a ':'. Invalid value [%s]" % user_tags
            logging.getLogger(__name__).exception(msg)
            raise exceptions.SystemSetupError(msg)
    return user_tags_dict


class SampleType(IntEnum):
    Warmup = 0
    Normal = 1


class MetricsStore:
    """
    Abstract metrics store
    """

    def __init__(self, cfg, clock=time.Clock, meta_info=None):
        """
        Creates a new metrics store.

        :param cfg: The config object. Mandatory.
        :param clock: This parameter is optional and needed for testing.
        :param meta_info: This parameter is optional and intended for creating a metrics store with a previously serialized meta-info.
        """
        self._config = cfg
        self._test_run_id = None
        self._test_run_timestamp = None
        self._workload = None
        self._workload_params = cfg.opts("workload", "params", default_value={}, mandatory=False)
        self._test_procedure = None
        self._cluster_config = None
        self._cluster_config_name = None
        self._environment_name = cfg.opts("system", "env.name")
        self.opened = False
        if meta_info is None:
            self._meta_info = {}
        else:
            self._meta_info = meta_info
        # ensure mandatory keys are always present
        if MetaInfoScope.cluster not in self._meta_info:
            self._meta_info[MetaInfoScope.cluster] = {}
        if MetaInfoScope.node not in self._meta_info:
            self._meta_info[MetaInfoScope.node] = {}
        self._clock = clock
        self._stop_watch = self._clock.stop_watch()
        self.logger = logging.getLogger(__name__)

    def open(self, test_run_id=None, test_run_timestamp=None, workload_name=None, test_procedure_name=None, cluster_config_name=None, ctx=None, create=False):
        """
        Opens a metrics store for a specific test_run, workload, test_procedure and cluster_config.

        :param test_run_id: The test run id. This attribute is sufficient to uniquely identify a test_run.
        :param test_run_timestamp: The test run timestamp as a datetime.
        :param workload_name: Workload name.
        :param test_procedure_name: TestProcedure name.
        :param cluster_config_name: ClusterConfigInstance name.
        :param ctx: An metrics store open context retrieved from another metrics store with ``#open_context``.
        :param create: True if an index should be created (if necessary). This is typically True, when attempting to write metrics and
        False when it is just opened for reading (as we can assume all necessary indices exist at this point).
        """
        if ctx:
            self._test_run_id = ctx["test-run-id"]
            self._test_run_timestamp = ctx["test-run-timestamp"]
            self._workload = ctx["workload"]
            self._test_procedure = ctx["test_procedure"]
            self._cluster_config = ctx["cluster-config-instance"]
        else:
            self._test_run_id = test_run_id
            self._test_run_timestamp = time.to_iso8601(test_run_timestamp)
            self._workload = workload_name
            self._test_procedure = test_procedure_name
            self._cluster_config = cluster_config_name
        assert self._test_run_id is not None, "Attempting to open metrics store without a test run id"
        assert self._test_run_timestamp is not None, "Attempting to open metrics store without a test run timestamp"

        self._cluster_config_name = "+".join(self._cluster_config) if isinstance(self._cluster_config, list) else self._cluster_config

        self.logger.info(
            "Opening metrics store for test run timestamp=[%s], workload=[%s],test_procedure=[%s], cluster_config=[%s]",
            self._test_run_timestamp,
            self._workload,
            self._test_procedure,
            self._cluster_config_name,
        )

        user_tags = extract_user_tags_from_config(self._config)
        for k, v in user_tags.items():
            # prefix user tag with "tag_" in order to avoid clashes with our internal meta data
            self.add_meta_info(MetaInfoScope.cluster, None, "tag_%s" % k, v)
        # Don't store it for each metrics record as it's probably sufficient on test run level
        # self.add_meta_info(MetaInfoScope.cluster, None, "benchmark_version", version.version())
        self._stop_watch.start()
        self.opened = True

    def reset_relative_time(self):
        """
        Resets the internal relative-time counter to zero.
        """
        self._stop_watch.start()

    def flush(self, refresh=True):
        """
        Explicitly flushes buffered metrics to the metric store. It is not required to flush before closing the metrics store.
        """
        raise NotImplementedError("abstract method")

    def close(self):
        """
        Closes the metric store. Note that it is mandatory to close the metrics store when it is no longer needed as it only persists
        metrics on close (in order to avoid additional latency during the benchmark).
        """
        self.logger.info("Closing metrics store.")
        self.flush()
        self._clear_meta_info()
        self.opened = False

    def add_meta_info(self, scope, scope_key, key, value):
        """
        Adds new meta information to the metrics store. All metrics entries that are created after calling this method are guaranteed to
        contain the added meta info (provided is on the same level or a level below, e.g. a cluster level metric will not contain node
        level meta information but all cluster level meta information will be contained in a node level metrics record).

        :param scope: The scope of the meta information. See MetaInfoScope.
        :param scope_key: The key within the scope. For cluster level metrics None is expected, for node level metrics the node name.
        :param key: The key of the meta information.
        :param value: The value of the meta information.
        """
        if scope == MetaInfoScope.cluster:
            self._meta_info[MetaInfoScope.cluster][key] = value
        elif scope == MetaInfoScope.node:
            if scope_key not in self._meta_info[MetaInfoScope.node]:
                self._meta_info[MetaInfoScope.node][scope_key] = {}
            self._meta_info[MetaInfoScope.node][scope_key][key] = value
        else:
            raise exceptions.SystemSetupError("Unknown meta info scope [%s]" % scope)

    def _clear_meta_info(self):
        """
        Clears all internally stored meta-info. This is considered Solr Orbit internal API and not intended for normal client consumption.
        """
        self._meta_info = {MetaInfoScope.cluster: {}, MetaInfoScope.node: {}}

    @property
    def open_context(self):
        return {
            "test-run-id": self._test_run_id,
            "test-run-timestamp": self._test_run_timestamp,
            "workload": self._workload,
            "test_procedure": self._test_procedure,
            "cluster-config-instance": self._cluster_config,
        }

    def put_value_cluster_level(
        self, name, value, unit=None, task=None, operation=None, operation_type=None, sample_type=SampleType.Normal, absolute_time=None, relative_time=None, meta_data=None
    ):
        """
        Adds a new cluster level value metric.

        :param name: The name of the metric.
        :param value: The metric value. It is expected to be numeric.
        :param unit: The unit of this metric value (e.g. ms, docs/s). Optional. Defaults to None.
        :param task: The task name to which this value applies. Optional. Defaults to None.
        :param operation: The operation name to which this value applies. Optional. Defaults to None.
        :param operation_type: The operation type to which this value applies. Optional. Defaults to None.
        :param sample_type: Whether this is a warmup or a normal measurement sample. Defaults to SampleType.Normal.
        :param absolute_time: The absolute timestamp in seconds since epoch when this metric record is stored. Defaults to None. The metrics
               store will derive the timestamp automatically.
        :param relative_time: The relative timestamp in seconds since the start of the benchmark when this metric record is stored.
               Defaults to None. The metrics store will derive the timestamp automatically.
        :param meta_data: A dict, containing additional key-value pairs. Defaults to None.
        """
        self._put_metric(MetaInfoScope.cluster, None, name, value, unit, task, operation, operation_type, sample_type, absolute_time, relative_time, meta_data)

    def put_value_node_level(
        self,
        node_name,
        name,
        value,
        unit=None,
        task=None,
        operation=None,
        operation_type=None,
        sample_type=SampleType.Normal,
        absolute_time=None,
        relative_time=None,
        meta_data=None,
    ):
        """
        Adds a new node level value metric.

        :param name: The name of the metric.
        :param node_name: The name of the cluster node for which this metric has been determined.
        :param value: The metric value. It is expected to be numeric.
        :param unit: The unit of this metric value (e.g. ms, docs/s). Optional. Defaults to None.
        :param task: The task name to which this value applies. Optional. Defaults to None.
        :param operation: The operation name to which this value applies. Optional. Defaults to None.
        :param operation_type: The operation type to which this value applies. Optional. Defaults to None.
        :param sample_type: Whether this is a warmup or a normal measurement sample. Defaults to SampleType.Normal.
        :param absolute_time: The absolute timestamp in seconds since epoch when this metric record is stored. Defaults to None. The metrics
               store will derive the timestamp automatically.
        :param relative_time: The relative timestamp in seconds since the start of the benchmark when this metric record is stored.
               Defaults to None. The metrics store will derive the timestamp automatically.
        :param meta_data: A dict, containing additional key-value pairs. Defaults to None.
        """
        self._put_metric(MetaInfoScope.node, node_name, name, value, unit, task, operation, operation_type, sample_type, absolute_time, relative_time, meta_data)

    def _put_metric(self, level, level_key, name, value, unit, task, operation, operation_type, sample_type, absolute_time=None, relative_time=None, meta_data=None):
        if level == MetaInfoScope.cluster:
            meta = self._meta_info[MetaInfoScope.cluster].copy()
        elif level == MetaInfoScope.node:
            meta = self._meta_info[MetaInfoScope.cluster].copy()
            if level_key in self._meta_info[MetaInfoScope.node]:
                meta.update(self._meta_info[MetaInfoScope.node][level_key])
        else:
            raise exceptions.SystemSetupError("Unknown meta info level [%s] for metric [%s]" % (level, name))
        if meta_data:
            meta.update(meta_data)

        if absolute_time is None:
            absolute_time = self._clock.now()
        if relative_time is None:
            relative_time = self._stop_watch.split_time()

        doc = {
            "@timestamp": time.to_epoch_millis(absolute_time),
            "relative-time-ms": convert.seconds_to_ms(relative_time),
            "test-run-id": self._test_run_id,
            "test-run-timestamp": self._test_run_timestamp,
            "environment": self._environment_name,
            "workload": self._workload,
            "test_procedure": self._test_procedure,
            "cluster-config-instance": self._cluster_config_name,
            "name": name,
            "value": value,
            "unit": unit,
            "sample-type": sample_type.name.lower(),
            "meta": meta,
        }
        if task:
            doc["task"] = task
        if operation:
            doc["operation"] = operation
        if operation_type:
            doc["operation-type"] = operation_type
        if self._workload_params:
            doc["workload-params"] = self._workload_params
        self._add(doc)

    def put_doc(self, doc, level=None, node_name=None, meta_data=None, absolute_time=None, relative_time=None):
        """
        Adds a new document to the metrics store. It will merge additional properties into the doc such as timestamps or workload info.

        :param doc: The raw document as a ``dict``. Ownership is transferred to the metrics store (i.e. don't reuse that object).
        :param level: Whether these are cluster or node-level metrics. May be ``None`` if not applicable.
        :param node_name: The name of the node in case metrics are on node level.
        :param meta_data: A dict, containing additional key-value pairs. Defaults to None.
        :param absolute_time: The absolute timestamp in seconds since epoch when this metric record is stored. Defaults to None. The metrics
               store will derive the timestamp automatically.
        :param relative_time: The relative timestamp in seconds since the start of the benchmark when this metric record is stored.
               Defaults to None. The metrics store will derive the timestamp automatically.
        """
        if level == MetaInfoScope.cluster:
            meta = self._meta_info[MetaInfoScope.cluster].copy()
        elif level == MetaInfoScope.node:
            meta = self._meta_info[MetaInfoScope.cluster].copy()
            if node_name in self._meta_info[MetaInfoScope.node]:
                meta.update(self._meta_info[MetaInfoScope.node][node_name])
        elif level is None:
            meta = None
        else:
            raise exceptions.SystemSetupError("Unknown meta info level [{}]".format(level))

        if meta and meta_data:
            meta.update(meta_data)

        if absolute_time is None:
            absolute_time = self._clock.now()
        if relative_time is None:
            relative_time = self._stop_watch.split_time()

        doc.update(
            {
                "@timestamp": time.to_epoch_millis(absolute_time),
                "relative-time-ms": convert.seconds_to_ms(relative_time),
                "test-run-id": self._test_run_id,
                "test-run-timestamp": self._test_run_timestamp,
                "environment": self._environment_name,
                "workload": self._workload,
                "test_procedure": self._test_procedure,
                "cluster-config-instance": self._cluster_config_name,
            }
        )
        if meta:
            doc["meta"] = meta
        if self._workload_params:
            doc["workload-params"] = self._workload_params

        self._add(doc)

    def bulk_add(self, memento):
        """
        Adds raw metrics store documents previously created with #to_externalizable()

        :param memento: The external representation as returned by #to_externalizable().
        """
        if memento:
            self.logger.debug("Restoring in-memory representation of metrics store.")
            for doc in pickle.loads(zlib.decompress(memento)):
                self._add(doc)

    def to_externalizable(self, clear=False):
        raise NotImplementedError("abstract method")

    def _add(self, doc):
        """
        Adds a new document to the metrics store

        :param doc: The new document.
        """
        raise NotImplementedError("abstract method")

    def get_one(self, name, sample_type=None, node_name=None, task=None, mapper=lambda doc: doc["value"], sort_key=None, sort_reverse=False):
        """
        Gets one value for the given metric name (even if there should be more than one).

        :param name: The metric name to query.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :param node_name The name of the node where this metric was gathered. Optional.
        :param task The task name to query. Optional.
        :param sort_key The key to sort the docs before returning the first value. Optional.
        :param sort_reverse  The flag to reverse the sort. Optional.
        :return: The corresponding value for the given metric name or None if there is no value.
        """
        raise NotImplementedError("abstract method")

    @staticmethod
    def _first_or_none(values):
        return values[0] if values else None

    def get(self, name, task=None, operation_type=None, sample_type=None, node_name=None):
        """
        Gets all raw values for the given metric name.

        :param name: The metric name to query.
        :param task The task name to query. Optional.
        :param operation_type The operation type to query. Optional.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :param node_name The name of the node where this metric was gathered. Optional.
        :return: A list of all values for the given metric.
        """
        return self._get(name, task, operation_type, sample_type, node_name, lambda doc: doc["value"])

    def get_raw(self, name, task=None, operation_type=None, sample_type=None, node_name=None, mapper=lambda doc: doc):
        """
        Gets all raw records for the given metric name.

        :param name: The metric name to query.
        :param task The task name to query. Optional.
        :param operation_type The operation type to query. Optional.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :param node_name The name of the node where this metric was gathered. Optional.
        :param mapper A record mapper. By default, the complete record is returned.
        :return: A list of all raw records for the given metric.
        """
        return self._get(name, task, operation_type, sample_type, node_name, mapper)

    def get_unit(self, name, task=None, operation_type=None, node_name=None):
        """
        Gets the unit for the given metric name.

        :param name: The metric name to query.
        :param task The task name to query. Optional.
        :param operation_type The operation type to query. Optional.
        :param node_name The name of the node where this metric was gathered. Optional.
        :return: The corresponding unit for the given metric name or None if no metric record is available.
        """
        # does not make too much sense to ask for a sample type here
        return self._first_or_none(self._get(name, task, operation_type, None, node_name, lambda doc: doc["unit"]))

    def _get(self, name, task, operation_type, sample_type, node_name, mapper):
        raise NotImplementedError("abstract method")

    def get_error_rate(self, task, operation_type=None, sample_type=None):
        """
        Gets the error rate for a specific task.

        :param task The task name to query.
        :param operation_type The operation type to query. Optional.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :return: A float between 0.0 and 1.0 (inclusive) representing the error rate.
        """
        raise NotImplementedError("abstract method")

    def get_stats(self, name, task=None, operation_type=None, sample_type=None):
        """
        Gets standard statistics for the given metric.

        :param name: The metric name to query.
        :param task The task name to query. Optional.
        :param operation_type The operation type to query. Optional.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :return: A metric_stats structure.
        """
        raise NotImplementedError("abstract method")

    def get_percentiles(self, name, task=None, operation_type=None, sample_type=None, percentiles=None):
        """
        Retrieves percentile metrics for the given metric.

        :param name: The metric name to query.
        :param task The task name to query. Optional.
        :param operation_type The operation type to query. Optional.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :param percentiles: An optional list of percentiles to show. If None is provided, by default the 99th, 99.9th and 100th percentile
        are determined. Ensure that there are enough data points in the metrics store (e.g. it makes no sense to retrieve a 99.9999
        percentile when there are only 10 values).
        :return: An ordered dictionary of the determined percentile values in ascending order. Key is the percentile, value is the
        determined value at this percentile. If no percentiles could be determined None is returned.
        """
        raise NotImplementedError("abstract method")

    def get_median(self, name, task=None, operation_type=None, sample_type=None):
        """
        Retrieves median value of the given metric.

        :param name: The metric name to query.
        :param task The task name to query. Optional.
        :param operation_type The operation type to query. Optional.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :return: The median value.
        """
        median = "50.0"
        percentiles = self.get_percentiles(name, task, operation_type, sample_type, percentiles=[median])
        return percentiles[median] if percentiles else None

    def get_mean(self, name, task=None, operation_type=None, sample_type=None):
        """
        Retrieves mean of the given metric.

        :param name: The metric name to query.
        :param task The task name to query. Optional.
        :param operation_type The operation type to query. Optional.
        :param sample_type The sample type to query. Optional. By default, all samples are considered.
        :return: The mean.
        """
        stats = self.get_stats(name, task, operation_type, sample_type)
        return stats["avg"] if stats else None


class InMemoryMetricsStore(MetricsStore):
    # Note that this implementation can run out of memory; generally, this can occur when ingesting very large corpora.

    # Approx size of a metrics doc (after tracking memory consumption during ingestion.
    DOC_SIZE_IN_BYTES = 1500

    # Warn when memory consumption crosses this threshold (percentage usage).
    MEMORY_WARNING_THRESHOLD = 85

    # Check memory usage every-so-many docs.
    MEMORY_CHECK_FREQUENCY = 10000

    def __init__(self, cfg, clock=time.Clock, meta_info=None):
        """

        Creates a new metrics store.

        :param cfg: The config object. Mandatory.
        :param clock: This parameter is optional and needed for testing.
        :param meta_info: This parameter is optional and intended for creating a metrics store with a previously serialized meta-info.
        """
        super().__init__(cfg=cfg, clock=clock, meta_info=meta_info)
        self.docs = []
        self.doc_count = 0
        self.logger = logging.getLogger(__name__)
        self.out_of_memory = False
        self.memory_available_threshold = psutil.virtual_memory().total * (100 - self.MEMORY_WARNING_THRESHOLD) / 100

    def __del__(self):
        """
        Deletes the metrics store instance.
        """
        del self.docs

    def _add(self, doc):
        if self.out_of_memory:
            return
        if self.doc_count % self.MEMORY_CHECK_FREQUENCY == 0 and psutil.virtual_memory().available < self.memory_available_threshold:
            console.warn("Memory threshold exceeded by in-memory metrics store, not adding additional entries", logger=self.logger)
            self.out_of_memory = True
            return
        self.docs.append(doc)
        self.doc_count += 1

    def flush(self, refresh=True):
        pass

    def to_externalizable(self, clear=False):
        docs = self.docs
        if clear:
            self.docs = []
            self.doc_count = 0
            self.out_of_memory = False
        if len(docs) * self.DOC_SIZE_IN_BYTES > psutil.virtual_memory().available - self.memory_available_threshold:
            console.warn("Memory threshold exceeded by in-memory metrics store, skipping summary generation for current operation", logger=self.logger)
            return None
        compressed = zlib.compress(pickle.dumps(docs))
        self.logger.debug("Compression changed size of metric store from [%d] bytes to [%d] bytes", sys.getsizeof(docs, -1), sys.getsizeof(compressed, -1))
        return compressed

    def get_percentiles(self, name, task=None, operation_type=None, sample_type=None, percentiles=None):
        if percentiles is None:
            percentiles = [99, 99.9, 100]
        result = collections.OrderedDict()
        values = self.get(name, task, operation_type, sample_type)
        if len(values) > 0:
            sorted_values = sorted(values)
            for percentile in percentiles:
                result[percentile] = self.percentile_value(sorted_values, percentile)
        return result

    @staticmethod
    def percentile_value(sorted_values, percentile):
        """
        Calculates a percentile value for a given list of values and a percentile.

        The implementation is based on http://onlinestatbook.com/2/introduction/percentiles.html

        :param sorted_values: A sorted list of raw values for which a percentile should be calculated.
        :param percentile: A percentile between [0, 100]
        :return: the corresponding percentile value.
        """
        rank = float(percentile) / 100.0 * (len(sorted_values) - 1)
        if rank == int(rank):
            return sorted_values[int(rank)]
        else:
            lr = math.floor(rank)
            lr_next = math.ceil(rank)
            fr = rank - lr
            lower_score = sorted_values[lr]
            higher_score = sorted_values[lr_next]
            return lower_score + (higher_score - lower_score) * fr

    def get_error_rate(self, task, operation_type=None, sample_type=None):
        error = 0
        total_count = 0
        for doc in self.docs:
            # we can use any request metrics record (i.e. service time or latency)
            if (
                doc["name"] == "service_time"
                and doc["task"] == task
                and (operation_type is None or doc["operation-type"] == operation_type)
                and (sample_type is None or doc["sample-type"] == sample_type.name.lower())
            ):
                total_count += 1
                if doc["meta"]["success"] is False:
                    error += 1
        if total_count > 0:
            return error / total_count
        else:
            return 0.0

    def get_stats(self, name, task=None, operation_type=None, sample_type=SampleType.Normal):
        values = self.get(name, task, operation_type, sample_type)
        sorted_values = sorted(values)
        if len(sorted_values) > 0:
            return {"count": len(sorted_values), "min": sorted_values[0], "max": sorted_values[-1], "avg": statistics.mean(sorted_values), "sum": sum(sorted_values)}
        else:
            return None

    def _get(self, name, task, operation_type, sample_type, node_name, mapper):
        return [
            mapper(doc)
            for doc in self.docs
            if doc["name"] == name
            and (task is None or doc["task"] == task)
            and (operation_type is None or doc["operation-type"] == operation_type)
            and (sample_type is None or doc["sample-type"] == sample_type.name.lower())
            and (node_name is None or doc.get("meta", {}).get("node_name") == node_name)
        ]

    def get_one(self, name, sample_type=None, node_name=None, task=None, mapper=lambda doc: doc["value"], sort_key=None, sort_reverse=False):
        if sort_key:
            docs = sorted(self.docs, key=lambda k: k[sort_key], reverse=sort_reverse)
        else:
            docs = self.docs
        for doc in docs:
            if (
                doc["name"] == name
                and (task is None or doc["task"] == task)
                and (sample_type is None or doc["sample-type"] == sample_type.name.lower())
                and (node_name is None or doc.get("meta", {}).get("node_name") == node_name)
            ):
                return mapper(doc)
        return None

    def __str__(self):
        return "in-memory metrics store"


class FilesystemMetricsStore(InMemoryMetricsStore):
    """Extends InMemoryMetricsStore to also persist each metric document to disk as a JSONL file."""

    def __init__(self, cfg, clock=time.Clock, meta_info=None):
        super().__init__(cfg=cfg, clock=clock, meta_info=meta_info)
        self._metrics_file = None

    def open(self, test_run_id=None, test_run_timestamp=None, workload_name=None, test_procedure_name=None, cluster_config_name=None, ctx=None, create=False):
        super().open(test_run_id, test_run_timestamp, workload_name, test_procedure_name, cluster_config_name, ctx, create)
        if create:
            run_dir = paths.test_run_root(self._config, test_run_id=self._test_run_id)
            io.ensure_dir(run_dir)
            metrics_path = os.path.join(run_dir, "metrics.jsonl")
            # line-buffered so each metric line is flushed immediately
            self._metrics_file = open(metrics_path, "wt", encoding="utf-8", buffering=1)  # pylint: disable=consider-using-with
            self.logger.info("FilesystemMetricsStore writing raw metrics to %s", metrics_path)

    def _add(self, doc):
        super()._add(doc)
        if self._metrics_file is not None:
            self._metrics_file.write(json.dumps(doc) + "\n")

    def flush(self, refresh=True):
        if self._metrics_file is not None:
            self._metrics_file.flush()

    def close(self):
        super().close()
        if self._metrics_file is not None:
            self._metrics_file.close()
            self._metrics_file = None

    def __str__(self):
        return "filesystem metrics store"


def test_run_store(cfg):
    """
    Creates a proper test_run store based on the current configuration.
    :param cfg: Config object. Mandatory.
    :return: A test_run store implementation.
    """
    logger = logging.getLogger(__name__)
    logger.info("Creating file test_run store")
    return FileTestRunStore(cfg)


def results_store(cfg):
    """
    Creates a proper test_run store based on the current configuration.
    :param cfg: Config object. Mandatory.
    :return: A test_run store implementation.
    """
    logger = logging.getLogger(__name__)
    logger.info("Creating no-op results store")
    return NoopResultsStore()


def list_test_helper(store_item, title):
    def format_dict(d):
        if d:
            items = sorted(d.items())
            return ", ".join(["%s=%s" % (k, v) for k, v in items])
        else:
            return None

    test_runs = []
    for test_run in store_item:
        test_runs.append(
            [
                test_run.test_run_id,
                time.to_iso8601(test_run.test_run_timestamp),
                test_run.workload,
                format_dict(test_run.workload_params),
                test_run.test_procedure_name,
                test_run.cluster_config_name,
                format_dict(test_run.user_tags),
                test_run.workload_revision,
                test_run.cluster_config_revision,
            ]
        )

    if len(test_runs) > 0:
        console.println(f"\nRecent {title}:\n")
        console.println(
            tabulate.tabulate(
                test_runs,
                headers=[
                    "TestRun ID",
                    "TestRun Timestamp",
                    "Workload",
                    "Workload Parameters",
                    "TestProcedure",
                    "ClusterConfigInstance",
                    "User Tags",
                    "workload Revision",
                    "Cluster Config Revision",
                ],
            )
        )
    else:
        console.println("")
        console.println(f"No recent {title} found.")


def list_test_runs(cfg):
    list_test_helper(test_run_store(cfg).list(), "test-runs")


def list_aggregated_results(cfg):
    list_test_helper(test_run_store(cfg).list_aggregations(), "aggregated-results")


def create_test_run(cfg, workload, test_procedure, workload_revision=None):
    cluster_config = cfg.opts("builder", "cluster_config.names")
    environment = cfg.opts("system", "env.name")
    test_run_id = cfg.opts("system", "test_run.id")
    test_run_timestamp = cfg.opts("system", "time.start")
    user_tags = extract_user_tags_from_config(cfg)
    pipeline = cfg.opts("test_run", "pipeline")
    workload_params = cfg.opts("workload", "params")
    cluster_config_params = cfg.opts("builder", "cluster_config.params")
    plugin_params = cfg.opts("builder", "plugin.params")
    benchmark_version = version.version()
    benchmark_revision = version.revision()
    latency_percentiles = cfg.opts("workload", "latency.percentiles", mandatory=False, default_value=GlobalStatsCalculator.DEFAULT_LATENCY_PERCENTILES)
    throughput_percentiles = cfg.opts("workload", "throughput.percentiles", mandatory=False, default_value=GlobalStatsCalculator.DEFAULT_THROUGHPUT_PERCENTILES)
    # In tests, we don't get the default command-line arg value for percentiles,
    # so supply them as defaults here as well

    # Get cluster_config_instance if available (stored during provisioning)
    cluster_config_instance = cfg.opts("builder", "cluster_config.instance", mandatory=False, default_value=None)

    return TestRun(
        benchmark_version,
        benchmark_revision,
        environment,
        test_run_id,
        test_run_timestamp,
        pipeline,
        user_tags,
        workload,
        workload_params,
        test_procedure,
        cluster_config,
        cluster_config_params,
        plugin_params,
        workload_revision,
        latency_percentiles=latency_percentiles,
        throughput_percentiles=throughput_percentiles,
        cluster_config_instance=cluster_config_instance,
    )


class TestRun:
    def __init__(
        self,
        benchmark_version,
        benchmark_revision,
        environment_name,
        test_run_id,
        test_run_timestamp,
        pipeline,
        user_tags,
        workload,
        workload_params,
        test_procedure,
        cluster_config,
        cluster_config_params,
        plugin_params,
        workload_revision=None,
        cluster_config_revision=None,
        distribution_version=None,
        distribution_flavor=None,
        revision=None,
        results=None,
        meta_data=None,
        latency_percentiles=None,
        throughput_percentiles=None,
        cluster_config_instance=None,
    ):
        if results is None:
            results = {}
        # this happens when the test run is created initially
        if meta_data is None:
            meta_data = {}
            if workload:
                meta_data.update(workload.meta_data)
            if test_procedure:
                meta_data.update(test_procedure.meta_data)
        if latency_percentiles:
            # split comma-separated string into list of floats
            latency_percentiles = [float(value) for value in latency_percentiles.split(",")]
        if throughput_percentiles:
            throughput_percentiles = [float(value) for value in throughput_percentiles.split(",")]
        self.benchmark_version = benchmark_version
        self.benchmark_revision = benchmark_revision
        self.environment_name = environment_name
        self.test_run_id = test_run_id
        self.test_run_timestamp = test_run_timestamp
        self.pipeline = pipeline
        self.user_tags = user_tags
        self.workload = workload
        self.workload_params = workload_params
        self.test_procedure = test_procedure
        self.cluster_config = cluster_config
        self.cluster_config_params = cluster_config_params
        self.plugin_params = plugin_params
        self.workload_revision = workload_revision
        self.cluster_config_revision = cluster_config_revision
        self.distribution_version = distribution_version
        self.distribution_flavor = distribution_flavor
        self.revision = revision
        self.results = results
        self.meta_data = meta_data
        self.latency_percentiles = latency_percentiles
        self.throughput_percentiles = throughput_percentiles
        self.cluster_config_instance = cluster_config_instance

    @property
    def workload_name(self):
        return str(self.workload)

    @property
    def test_procedure_name(self):
        return str(self.test_procedure) if self.test_procedure else None

    @property
    def cluster_config_name(self):
        return "+".join(self.cluster_config) if isinstance(self.cluster_config, list) else self.cluster_config

    def add_results(self, results):
        self.results = results

    def as_dict(self):
        """
        :return: A dict representation suitable for persisting this test run instance as JSON.
        """
        d = {
            "benchmark-version": self.benchmark_version,
            "benchmark-revision": self.benchmark_revision,
            "environment": self.environment_name,
            "test-run-id": self.test_run_id,
            "test-run-timestamp": time.to_iso8601(self.test_run_timestamp),
            "pipeline": self.pipeline,
            "user-tags": self.user_tags,
            "workload": self.workload_name,
            "cluster-config-instance": self.cluster_config,
            "cluster": {
                "revision": self.revision,
                "distribution-version": self.distribution_version,
                "distribution-flavor": self.distribution_flavor,
                "cluster-config-revision": self.cluster_config_revision,
            },
        }
        if self.results:
            # if results was loaded from JSON it’s already a dict
            if isinstance(self.results, dict):
                d["results"] = self.results
            elif hasattr(self.results, "as_dict"):
                d["results"] = self.results.as_dict()
            else:
                # Fallback: just stick whatever it is in there
                d["results"] = self.results
        if self.workload_revision:
            d["workload-revision"] = self.workload_revision
        d["test_procedure"] = self.test_procedure_name
        if self.workload_params:
            d["workload-params"] = self.workload_params
        if self.cluster_config_params:
            d["cluster-config-instance-params"] = self.cluster_config_params
        if self.plugin_params:
            d["plugin-params"] = self.plugin_params
        # Add complete cluster-config specification for result portal display and time-series analysis
        if self.cluster_config_instance:
            d["cluster-config-spec"] = {
                "names": self.cluster_config_instance.names if hasattr(self.cluster_config_instance, "names") else [],
                "variables": self.cluster_config_instance.variables if hasattr(self.cluster_config_instance, "variables") else {},
                "config_paths": self.cluster_config_instance.config_paths if hasattr(self.cluster_config_instance, "config_paths") else [],
                "root_path": self.cluster_config_instance.root_path if hasattr(self.cluster_config_instance, "root_path") else None,
                "provider": str(self.cluster_config_instance.provider) if hasattr(self.cluster_config_instance, "provider") else None,
                "flavor": str(self.cluster_config_instance.flavor) if hasattr(self.cluster_config_instance, "flavor") else None,
            }
        return d

    def to_result_dicts(self):
        """
        :return: a list of dicts, suitable for persisting the results of this test run in a format that is Kibana-friendly.
        """
        result_template = {
            "benchmark-version": self.benchmark_version,
            "benchmark-revision": self.benchmark_revision,
            "environment": self.environment_name,
            "test-run-id": self.test_run_id,
            "test-run-timestamp": time.to_iso8601(self.test_run_timestamp),
            "distribution-version": self.distribution_version,
            "distribution-flavor": self.distribution_flavor,
            "user-tags": self.user_tags,
            "workload": self.workload_name,
            "test_procedure": self.test_procedure_name,
            "cluster-config-instance": self.cluster_config_name,
            # allow to logically delete records, e.g. for UI purposes when we only want to show the latest result
            "active": True,
        }
        if self.distribution_version:
            result_template["distribution-major-version"] = versions.major_version(self.distribution_version)
        if self.cluster_config_revision:
            result_template["cluster-config-revision"] = self.cluster_config_revision
        if self.workload_revision:
            result_template["workload-revision"] = self.workload_revision
        if self.workload_params:
            result_template["workload-params"] = self.workload_params
        if self.cluster_config_params:
            result_template["cluster-config-instance-params"] = self.cluster_config_params
        if self.plugin_params:
            result_template["plugin-params"] = self.plugin_params
        if self.meta_data:
            result_template["meta"] = self.meta_data

        all_results = []

        for item in self.results.as_flat_list():
            result = result_template.copy()
            result.update(item)
            all_results.append(result)

        return all_results

    @classmethod
    def from_dict(cls, d):
        user_tags = d.get("user-tags", {})
        # TODO: cluster is optional for BWC. This can be removed after some grace period.
        cluster = d.get("cluster", {})
        return TestRun(
            d["benchmark-version"],
            d.get("benchmark-revision"),
            d["environment"],
            d["test-run-id"],
            time.from_is8601(d["test-run-timestamp"]),
            d["pipeline"],
            user_tags,
            d["workload"],
            d.get("workload-params"),
            d.get("test_procedure"),
            d["cluster-config-instance"],
            d.get("cluster-config-instance-params"),
            d.get("plugin-params"),
            workload_revision=d.get("workload-revision"),
            cluster_config_revision=cluster.get("cluster-config-revision"),
            distribution_version=cluster.get("distribution-version"),
            distribution_flavor=cluster.get("distribution-flavor"),
            revision=cluster.get("revision"),
            results=d.get("results"),
            meta_data=d.get("meta", {}),
        )


class TestRunStore:
    def __init__(self, cfg):
        self.cfg = cfg
        self.environment_name = cfg.opts("system", "env.name")

    def find_by_test_run_id(self, test_run_id):
        raise NotImplementedError("abstract method")

    def list(self):
        raise NotImplementedError("abstract method")

    def store_test_run(self, test_run):
        raise NotImplementedError("abstract method")

    def _max_results(self):
        return int(self.cfg.opts("system", "list.test_runs.max_results"))


# NOT USED — retained as placeholder for a future external store (e.g. S3TestRunStore).
class CompositeTestRunStore:
    """
    Placeholder delegating test-run store for a future external store integration
    (e.g. S3TestRunStore). Delegates writes to both an external store and the local
    file store; reads are served from the external store.

    Not wired into any active code path. Does not inherit from TestRunStore —
    it is a delegator with the same API.
    """

    def __init__(self, external_store, file_store):
        self.external_store = external_store
        self.file_store = file_store

    def find_by_test_run_id(self, test_run_id):
        return self.external_store.find_by_test_run_id(test_run_id)

    def store_test_run(self, test_run):
        self.file_store.store_test_run(test_run)
        self.external_store.store_test_run(test_run)

    def store_html_results(self, test_run):
        self.file_store.store_html_results(test_run)

    def list(self):
        return self.external_store.list()


class FileTestRunStore(TestRunStore):
    _browser_opened = {}

    def __init__(self, cfg):
        super().__init__(cfg)
        self._max_results = lambda: int(cfg.opts("system", "list.test_runs.max_results"))

    def store_test_run(self, test_run):
        open_browser = False
        doc = test_run.as_dict()
        test_run_path = paths.test_run_root(self.cfg, test_run_id=test_run.test_run_id)
        io.ensure_dir(test_run_path)
        with open(self._test_run_file(), mode="wt", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=True, ensure_ascii=False))

        # Check if visualization is enabled
        if self.cfg.opts("workload", "visualize", mandatory=False, default_value=False):
            # Reset the browser opened flag when we're storing the final results
            if hasattr(test_run, "results") and test_run.results:
                FileTestRunStore._browser_opened[test_run.test_run_id] = False
                open_browser = True
            self.store_html_results(test_run, open_browser)

    def store_aggregated_run(self, test_run):
        doc = test_run.as_dict()
        aggregated_execution_path = paths.aggregated_results_root(self.cfg, test_run_id=test_run.test_run_id)
        io.ensure_dir(aggregated_execution_path)
        aggregated_file = os.path.join(aggregated_execution_path, "aggregated_test_run.json")
        with open(aggregated_file, mode="wt", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=True, ensure_ascii=False))

    def store_html_results(self, test_run, open_browser=True):
        # Check if custom output path is specified
        custom_output_path = self.cfg.opts("workload", "visualize.output.path", mandatory=False, default_value=None)

        html_content = render_results_html(test_run, self.cfg)

        if custom_output_path:
            dest = os.path.expanduser(custom_output_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            print("[DEBUG]: ", dest)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(html_content)
            console.info(f"HTML report saved to: {dest}")
            if open_browser:
                webbrowser.open(f"file://{dest}")
            return dest
        else:
            # Use default behavior
            report_file = os.path.join(paths.test_run_root(self.cfg, test_run_id=test_run.test_run_id), "test_run_report.html")
            print("[DEBUG]: ", report_file)
            with open(report_file, mode="w", encoding="utf-8") as f:
                f.write(html_content)
            if open_browser:
                webbrowser.open(f"file://{report_file}")
            console.info(f"HTML report saved to: {report_file}")
            return report_file

    def _test_run_file(self, test_run_id=None, is_aggregated=False):
        if is_aggregated:
            return os.path.join(paths.aggregated_results_root(cfg=self.cfg, test_run_id=test_run_id), "aggregated_test_run.json")
        else:
            return os.path.join(paths.test_run_root(cfg=self.cfg, test_run_id=test_run_id), "test_run.json")

    def list(self):
        results = glob.glob(self._test_run_file(test_run_id="*"))
        all_test_runs = self._to_test_runs(results)
        return all_test_runs[: self._max_results()]

    def list_aggregations(self):
        aggregated_results = glob.glob(self._test_run_file(test_run_id="*", is_aggregated=True))
        return self._to_test_runs(aggregated_results)

    def find_by_test_run_id(self, test_run_id):
        is_aggregated = test_run_id.startswith("aggregate")
        test_run_file = self._test_run_file(test_run_id=test_run_id, is_aggregated=is_aggregated)
        if io.exists(test_run_file):
            test_runs = self._to_test_runs([test_run_file])
            if test_runs:
                return test_runs[0]
        raise exceptions.NotFound("No test run with test run id [{}]".format(test_run_id))

    def _to_test_runs(self, results):
        test_runs = []
        for result in results:
            # noinspection PyBroadException
            try:
                with open(result, mode="rt", encoding="utf-8") as f:
                    test_runs.append(TestRun.from_dict(json.loads(f.read())))
            except BaseException:
                logging.getLogger(__name__).exception("Could not load test_run file [%s] (incompatible format?) Skipping...", result)
        return sorted(test_runs, key=lambda r: r.test_run_timestamp, reverse=True)


class NoopResultsStore:
    """
    Does not store any results separately as these are stored as part of the test_run on the file system.
    """

    def store_results(self, test_run):
        pass


# helper function for encoding and decoding float keys so that the OpenSearch metrics store can save them.
def encode_float_key(k):
    # ensure that the key is indeed a float to unify the representation (e.g. 50 should be represented as "50_0")
    return str(float(k)).replace(".", "_")


def filter_percentiles_by_sample_size(sample_size, percentiles):
    # Don't show percentiles if there aren't enough samples for the value to be distinct.
    # For example, we should only show p99.9, p45.6, or p0.01 if there are at least 1000 values.
    # If nothing is suitable, default to just returning [100] rather than an empty list.
    if sample_size < 1:
        raise AssertionError("Percentiles require at least one sample")

    filtered_percentiles = []
    # Treat the cases below 10 separately, to return p25, 50, 75, 100 if present
    if sample_size == 1:
        filtered_percentiles = [100]
    elif sample_size < 4:
        for p in [50, 100]:
            if p in percentiles:
                filtered_percentiles.append(p)
    elif sample_size < 10:
        for p in [25, 50, 75, 100]:
            if p in percentiles:
                filtered_percentiles.append(p)
    else:
        effective_sample_size = 10 ** (int(math.log10(sample_size)))  # round down to nearest power of ten
        delta = 0.000001  # If (p / 100) * effective_sample_size is within this value of a whole number,
        # assume the discrepancy is due to floating point and allow it
        for p in percentiles:
            fraction = p / 100
            # check if fraction * effective_sample_size is close enough to a whole number
            if abs((effective_sample_size * fraction) - round(effective_sample_size * fraction)) < delta or p in [25, 75]:
                filtered_percentiles.append(p)
    # if no percentiles are suitable, just return 100
    if len(filtered_percentiles) == 0:
        return [100]
    return filtered_percentiles


def percentiles_for_sample_size(sample_size, percentiles_list=None):
    # If latency_percentiles is present, as a list, display those values instead (assuming there are enough samples)
    percentiles = []
    if percentiles_list:
        percentiles = percentiles_list  # Defaults get overridden if a value is provided
        percentiles.sort()
    return filter_percentiles_by_sample_size(sample_size, percentiles)


class GlobalStatsCalculator:
    DEFAULT_LATENCY_PERCENTILES = "50,90,99,99.9,99.99,100"
    DEFAULT_LATENCY_PERCENTILES_LIST = [float(value) for value in DEFAULT_LATENCY_PERCENTILES.split(",")]

    DEFAULT_THROUGHPUT_PERCENTILES = ""
    DEFAULT_THROUGHPUT_PERCENTILES_LIST = []

    OTHER_PERCENTILES = [50, 90, 99, 99.9, 99.99, 100]
    # Use these percentiles when the single_latency fn is called for something other than latency

    def __init__(self, store, workload, test_procedure, latency_percentiles=None, throughput_percentiles=None):
        self.store = store
        self.logger = logging.getLogger(__name__)
        self.workload = workload
        self.test_procedure = test_procedure
        self.latency_percentiles = latency_percentiles
        self.throughput_percentiles = throughput_percentiles

    def __call__(self):
        result = GlobalStats()

        for tasks in self.test_procedure.schedule:
            for task in tasks:
                task_name = task.name
                op_type = task.operation.type
                error_rate = self.error_rate(task_name, op_type)
                duration = self.duration(task_name)

                if task.operation.include_in_reporting or error_rate > 0:
                    self.logger.debug("Gathering request metrics for [%s].", task_name)
                    result.add_op_metrics(
                        task_name,
                        task.operation.name,
                        self.summary_stats("throughput", task_name, op_type, percentiles_list=self.throughput_percentiles),
                        self.single_latency(task_name, op_type),
                        self.single_latency(task_name, op_type, metric_name="service_time"),
                        self.single_latency(task_name, op_type, metric_name="client_processing_time"),
                        self.single_latency(task_name, op_type, metric_name="processing_time"),
                        error_rate,
                        duration,
                        self.merge(
                            self.workload.meta_data,
                            self.test_procedure.meta_data,
                            task.operation.meta_data,
                            task.meta_data,
                        ),
                    )

                    result.add_correctness_metrics(
                        task_name,
                        task.operation.name,
                        self.single_latency(task_name, op_type, metric_name="recall@k"),
                        self.single_latency(task_name, op_type, metric_name="recall@1"),
                        error_rate,
                        duration,
                    )

                    profile_metrics = task.operation.params.get("profile-metrics", None)
                    if profile_metrics:
                        profile_metrics.append("query_time")
                        result.add_profile_metrics(task_name, task.operation.name, {name: self.single_latency(task_name, op_type, metric_name=name) for name in profile_metrics})

        self.logger.debug("Gathering indexing metrics.")
        result.total_time = self.sum("indexing_total_time")
        result.total_time_per_shard = self.shard_stats("indexing_total_time")
        result.indexing_throttle_time = self.sum("indexing_throttle_time")
        result.indexing_throttle_time_per_shard = self.shard_stats("indexing_throttle_time")
        result.merge_time = self.sum("merges_total_time")
        result.merge_time_per_shard = self.shard_stats("merges_total_time")
        result.merge_count = self.sum("merges_total_count")
        result.refresh_time = self.sum("refresh_total_time")
        result.refresh_time_per_shard = self.shard_stats("refresh_total_time")
        result.refresh_count = self.sum("refresh_total_count")
        result.flush_time = self.sum("flush_total_time")
        result.flush_time_per_shard = self.shard_stats("flush_total_time")
        result.flush_count = self.sum("flush_total_count")
        result.merge_throttle_time = self.sum("merges_total_throttled_time")
        result.merge_throttle_time_per_shard = self.shard_stats("merges_total_throttled_time")

        self.logger.debug("Gathering ML max processing times.")
        result.ml_processing_time = self.ml_processing_time_stats()

        self.logger.debug("Gathering garbage collection metrics.")
        result.young_gc_time = self.sum("node_total_young_gen_gc_time")
        result.young_gc_count = self.sum("node_total_young_gen_gc_count")
        result.old_gc_time = self.sum("node_total_old_gen_gc_time")
        result.old_gc_count = self.sum("node_total_old_gen_gc_count")

        self.logger.debug("Gathering segment memory metrics.")
        result.memory_segments = self.median("segments_memory_in_bytes")
        result.memory_doc_values = self.median("segments_doc_values_memory_in_bytes")
        result.memory_terms = self.median("segments_terms_memory_in_bytes")
        result.memory_norms = self.median("segments_norms_memory_in_bytes")
        result.memory_points = self.median("segments_points_memory_in_bytes")
        result.memory_stored_fields = self.median("segments_stored_fields_memory_in_bytes")
        result.store_size = self.sum("store_size_in_bytes")
        result.translog_size = self.sum("translog_size_in_bytes")

        # convert to int, fraction counts are senseless
        median_segment_count = self.median("segments_count")
        result.segment_count = int(median_segment_count) if median_segment_count is not None else median_segment_count

        self.logger.debug("Gathering transform processing times.")
        result.total_transform_processing_times = self.total_transform_metric("total_transform_processing_time")
        result.total_transform_index_times = self.total_transform_metric("total_transform_index_time")
        result.total_transform_search_times = self.total_transform_metric("total_transform_search_time")
        result.total_transform_throughput = self.total_transform_metric("total_transform_throughput")

        return result

    def merge(self, *args):
        # This is similar to dict(collections.ChainMap(args)) except that we skip `None` in our implementation.
        result = {}
        for arg in args:
            if arg is not None:
                result.update(arg)
        return result

    def sum(self, metric_name):
        values = self.store.get(metric_name)
        if values:
            return sum(values)
        else:
            return None

    def one(self, metric_name):
        return self.store.get_one(metric_name)

    def summary_stats(self, metric_name, task_name, operation_type, percentiles_list=None):
        mean = self.store.get_mean(metric_name, task=task_name, operation_type=operation_type, sample_type=SampleType.Normal)
        median = self.store.get_median(metric_name, task=task_name, operation_type=operation_type, sample_type=SampleType.Normal)
        unit = self.store.get_unit(metric_name, task=task_name, operation_type=operation_type)
        stats = self.store.get_stats(metric_name, task=task_name, operation_type=operation_type, sample_type=SampleType.Normal)

        result = {}
        if mean and median and stats:
            result = {"min": stats["min"], "mean": mean, "median": median, "max": stats["max"], "unit": unit}
        else:
            result = {"min": None, "mean": None, "median": None, "max": None, "unit": unit}

        if percentiles_list:  # modified from single_latency()
            sample_size = stats["count"]
            percentiles = self.store.get_percentiles(
                metric_name,
                task=task_name,
                operation_type=operation_type,
                sample_type=SampleType.Normal,
                percentiles=percentiles_for_sample_size(sample_size, percentiles_list=percentiles_list),
            )
            for k, v in percentiles.items():
                # safely encode so we don't have any dots in field names
                result[encode_float_key(k)] = v
        return result

    def shard_stats(self, metric_name):
        values = self.store.get_raw(metric_name, mapper=lambda doc: doc["per-shard"])
        unit = self.store.get_unit(metric_name)
        if values:
            flat_values = [w for v in values for w in v]
            return {"min": min(flat_values), "median": statistics.median(flat_values), "max": max(flat_values), "unit": unit}
        else:
            return {}

    def ml_processing_time_stats(self):
        values = self.store.get_raw("ml_processing_time")
        result = []
        if values:
            for v in values:
                result.append({"job": v["job"], "min": v["min"], "mean": v["mean"], "median": v["median"], "max": v["max"], "unit": v["unit"]})
        return result

    def total_transform_metric(self, metric_name):
        values = self.store.get_raw(metric_name)
        result = []
        if values:
            for v in values:
                transform_id = v.get("meta", {}).get("transform_id")
                if transform_id is not None:
                    result.append({"id": transform_id, "mean": v["value"], "unit": v["unit"]})
        return result

    def error_rate(self, task_name, operation_type):
        return self.store.get_error_rate(task=task_name, operation_type=operation_type, sample_type=SampleType.Normal)

    def duration(self, task_name):
        return self.store.get_one("service_time", task=task_name, mapper=lambda doc: doc["relative-time-ms"], sort_key="relative-time-ms", sort_reverse=True)

    def median(self, metric_name, task_name=None, operation_type=None, sample_type=None):
        return self.store.get_median(metric_name, task=task_name, operation_type=operation_type, sample_type=sample_type)

    def single_latency(self, task, operation_type, metric_name="latency"):
        sample_type = SampleType.Normal
        stats = self.store.get_stats(metric_name, task=task, operation_type=operation_type, sample_type=sample_type)
        sample_size = stats["count"] if stats else 0
        percentiles_list = self.OTHER_PERCENTILES
        if metric_name == "latency":
            percentiles_list = self.latency_percentiles
        if sample_size > 0:
            # The custom latency percentiles have to be supplied here as the workload runs,
            # or else they aren't present when results are published
            percentiles = self.store.get_percentiles(
                metric_name,
                task=task,
                operation_type=operation_type,
                sample_type=sample_type,
                percentiles=percentiles_for_sample_size(sample_size, percentiles_list=percentiles_list),
            )
            mean = self.store.get_mean(metric_name, task=task, operation_type=operation_type, sample_type=sample_type)
            unit = self.store.get_unit(metric_name, task=task, operation_type=operation_type)
            stats = collections.OrderedDict()
            for k, v in percentiles.items():
                # safely encode so we don't have any dots in field names
                stats[encode_float_key(k)] = v
            stats["mean"] = mean
            stats["unit"] = unit
            return stats
        else:
            return {}


class GlobalStats:
    def __init__(self, d=None):
        self.op_metrics = self.v(d, "op_metrics", default=[])
        self.correctness_metrics = self.v(d, "correctness_metrics", default=[])
        self.profile_metrics = self.v(d, "profile_metrics", default=[])
        self.total_time = self.v(d, "total_time")
        self.total_time_per_shard = self.v(d, "total_time_per_shard", default={})
        self.indexing_throttle_time = self.v(d, "indexing_throttle_time")
        self.indexing_throttle_time_per_shard = self.v(d, "indexing_throttle_time_per_shard", default={})
        self.merge_time = self.v(d, "merge_time")
        self.merge_time_per_shard = self.v(d, "merge_time_per_shard", default={})
        self.merge_count = self.v(d, "merge_count")
        self.refresh_time = self.v(d, "refresh_time")
        self.refresh_time_per_shard = self.v(d, "refresh_time_per_shard", default={})
        self.refresh_count = self.v(d, "refresh_count")
        self.flush_time = self.v(d, "flush_time")
        self.flush_time_per_shard = self.v(d, "flush_time_per_shard", default={})
        self.flush_count = self.v(d, "flush_count")
        self.merge_throttle_time = self.v(d, "merge_throttle_time")
        self.merge_throttle_time_per_shard = self.v(d, "merge_throttle_time_per_shard", default={})
        self.ml_processing_time = self.v(d, "ml_processing_time", default=[])

        self.young_gc_time = self.v(d, "young_gc_time")
        self.young_gc_count = self.v(d, "young_gc_count")
        self.old_gc_time = self.v(d, "old_gc_time")
        self.old_gc_count = self.v(d, "old_gc_count")

        self.memory_segments = self.v(d, "memory_segments")
        self.memory_doc_values = self.v(d, "memory_doc_values")
        self.memory_terms = self.v(d, "memory_terms")
        self.memory_norms = self.v(d, "memory_norms")
        self.memory_points = self.v(d, "memory_points")
        self.memory_stored_fields = self.v(d, "memory_stored_fields")
        self.store_size = self.v(d, "store_size")
        self.translog_size = self.v(d, "translog_size")
        self.segment_count = self.v(d, "segment_count")

        self.total_transform_search_times = self.v(d, "total_transform_search_times")
        self.total_transform_index_times = self.v(d, "total_transform_index_times")
        self.total_transform_processing_times = self.v(d, "total_transform_processing_times")
        self.total_transform_throughput = self.v(d, "total_transform_throughput")

    def as_dict(self):
        return self.__dict__

    def as_flat_list(self):
        def op_metrics(op_item, key, single_value=False):
            doc = {"task": op_item["task"], "operation": op_item["operation"], "name": key}
            if single_value:
                doc["value"] = {"single": op_item[key]}
            else:
                doc["value"] = op_item[key]
            if "meta" in op_item:
                doc["meta"] = op_item["meta"]
            return doc

        all_results = []
        for metric, value in self.as_dict().items():
            if metric == "op_metrics":
                for item in value:
                    if "throughput" in item:
                        all_results.append(op_metrics(item, "throughput"))
                    if "latency" in item:
                        all_results.append(op_metrics(item, "latency"))
                    if "service_time" in item:
                        all_results.append(op_metrics(item, "service_time"))
                    if "client_processing_time" in item:
                        all_results.append(op_metrics(item, "client_processing_time"))
                    if "processing_time" in item:
                        all_results.append(op_metrics(item, "processing_time"))
                    if "error_rate" in item:
                        all_results.append(op_metrics(item, "error_rate", single_value=True))
                    if "duration" in item:
                        all_results.append(op_metrics(item, "duration", single_value=True))
            elif metric == "ml_processing_time":
                for item in value:
                    all_results.append(
                        {"job": item["job"], "name": "ml_processing_time", "value": {"min": item["min"], "mean": item["mean"], "median": item["median"], "max": item["max"]}}
                    )
            elif metric == "correctness_metrics":
                for item in value:
                    for knn_metric in ["recall@k", "recall@1"]:
                        if knn_metric in item:
                            all_results.append({"task": item["task"], "operation": item["operation"], "name": knn_metric, "value": item[knn_metric]})
            elif metric == "profile_metrics":
                for item in value:
                    for metric_name in item.keys():
                        if metric_name not in ["task", "operation", "error_rate", "duration"]:
                            all_results.append({"task": item["task"], "operation": item["operation"], "name": metric_name, "value": item[metric_name]})
            elif metric.startswith("total_transform_") and value is not None:
                for item in value:
                    all_results.append({"id": item["id"], "name": metric, "value": {"single": item["mean"]}})
            elif metric.endswith("_time_per_shard"):
                if value:
                    all_results.append({"name": metric, "value": value})
            elif value is not None:
                result = {"name": metric, "value": {"single": value}}
                all_results.append(result)
        # sorting is just necessary to have a stable order for tests. As we just have a small number of metrics, the overhead is neglible.
        return sorted(all_results, key=lambda m: m["name"])

    def v(self, d, k, default=None):
        return d.get(k, default) if d else default

    def add_op_metrics(self, task, operation, throughput, latency, service_time, client_processing_time, processing_time, error_rate, duration, meta):
        doc = {
            "task": task,
            "operation": operation,
            "throughput": throughput,
            "latency": latency,
            "service_time": service_time,
            "client_processing_time": client_processing_time,
            "processing_time": processing_time,
            "error_rate": error_rate,
            "duration": duration,
        }
        if meta:
            doc["meta"] = meta
        self.op_metrics.append(doc)

    def add_correctness_metrics(self, task, operation, recall_at_k_stats, recall_at_1_stats, error_rate, duration):
        self.correctness_metrics.append(
            {
                "task": task,
                "operation": operation,
                "recall@k": recall_at_k_stats,
                "recall@1": recall_at_1_stats,
                "error_rate": error_rate,
                "duration": duration,
            }
        )

    def add_profile_metrics(self, task, operation, profile_metrics):
        self.profile_metrics.append({"task": task, "operation": operation, "metrics": profile_metrics})

    def tasks(self):
        # ensure we can read test_run.json files before Solr Orbit 0.8.0
        return [v.get("task", v["operation"]) for v in self.op_metrics]

    def metrics(self, task):
        # ensure we can read test_run.json files before Solr Orbit 0.8.0
        for r in self.op_metrics:
            if r.get("task", r["operation"]) == task:
                return r
        return None


class SystemStatsCalculator:
    def __init__(self, store, node_name):
        self.store = store
        self.logger = logging.getLogger(__name__)
        self.node_name = node_name

    def __call__(self):
        result = SystemStats()
        self.logger.debug("Calculating system metrics for [%s]", self.node_name)
        self.logger.debug("Gathering disk metrics.")
        self.add(result, "final_index_size_bytes", "index_size")
        self.add(result, "disk_io_write_bytes", "bytes_written")
        self.logger.debug("Gathering node startup time metrics.")
        self.add(result, "node_startup_time", "startup_time")
        return result

    def add(self, result, raw_metric_key, summary_metric_key):
        metric_value = self.store.get_one(raw_metric_key, node_name=self.node_name)
        metric_unit = self.store.get_unit(raw_metric_key, node_name=self.node_name)
        if metric_value:
            self.logger.debug("Adding record for [%s] with value [%s].", raw_metric_key, str(metric_value))
            result.add_node_metrics(self.node_name, summary_metric_key, metric_value, metric_unit)
        else:
            self.logger.debug("Skipping incomplete [%s] record.", raw_metric_key)


class SystemStats:
    def __init__(self, d=None):
        self.node_metrics = self.v(d, "node_metrics", default=[])

    def v(self, d, k, default=None):
        return d.get(k, default) if d else default

    def add_node_metrics(self, node, name, value, unit):
        metric = {"node": node, "name": name, "value": value}
        if unit:
            metric["unit"] = unit
        self.node_metrics.append(metric)

    def as_flat_list(self):
        all_results = []
        for v in self.node_metrics:
            all_results.append({"node": v["node"], "name": v["name"], "value": {"single": v["value"]}})
        # Sort for a stable order in tests.
        return sorted(all_results, key=lambda m: m["name"])
