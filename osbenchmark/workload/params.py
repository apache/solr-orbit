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

from __future__ import annotations

import os
import inspect
import logging
import math
import numbers
import operator
import random
import re
import time
import multiprocessing
from enum import Enum

from osbenchmark import exceptions
from osbenchmark.utils import io
from osbenchmark.workload import loader, workload
from osbenchmark.workload.ingestion_manager import IngestionManager

__PARAM_SOURCES_BY_OP = {}
__PARAM_SOURCES_BY_NAME = {}

__STANDARD_VALUE_SOURCES = {}
__STANDARD_VALUES = {}
__QUERY_RANDOMIZATION_INFOS = {}

def param_source_for_operation(op_type, workload, params, task_name):
    try:
        # we know that this can only be a ASB core parameter source
        return __PARAM_SOURCES_BY_OP[op_type](workload, params, operation_name=task_name)
    except KeyError:
        pass
    # Also check name-based registry for user-defined operation types (e.g., "bulk-index")
    if isinstance(op_type, str) and op_type in __PARAM_SOURCES_BY_NAME:
        return param_source_for_name(op_type, workload, params)
    return ParamSource(workload, params, operation_name=task_name)


def param_source_for_name(name, workload, params):
    param_source = __PARAM_SOURCES_BY_NAME[name]

    if inspect.isfunction(param_source):
        return DelegatingParamSource(workload, params, param_source)
    else:
        return param_source(workload, params)

def get_standard_value_source(op_name, field_name):
    try:
        return __STANDARD_VALUE_SOURCES[op_name][field_name]
    except KeyError:
        raise exceptions.SystemSetupError(
            "Could not find standard value source for operation {}, field {}! Make sure this is registered in workload.py"
            .format(op_name, field_name))


def ensure_valid_param_source(param_source):
    if not inspect.isfunction(param_source) and not inspect.isclass(param_source):
        raise exceptions.BenchmarkAssertionError(f"Parameter source [{param_source}] must be either a function or a class.")


def register_param_source_for_operation(op_type, param_source_class):
    ensure_valid_param_source(param_source_class)
    __PARAM_SOURCES_BY_OP[op_type.to_hyphenated_string()] = param_source_class


def register_param_source_for_name(name, param_source_class):
    ensure_valid_param_source(param_source_class)
    __PARAM_SOURCES_BY_NAME[name] = param_source_class

def register_standard_value_source(op_name, field_name, standard_value_source):
    if op_name in __STANDARD_VALUE_SOURCES:
        __STANDARD_VALUE_SOURCES[op_name][field_name] = standard_value_source
        # We have to allow re-registration for the same op/field, since plugins are loaded many times when a workload is run
    else:
        __STANDARD_VALUE_SOURCES[op_name] = {field_name:standard_value_source}

def generate_standard_values_if_absent(op_name, field_name, n):
    if not op_name in __STANDARD_VALUES:
        __STANDARD_VALUES[op_name] = {}
    if not field_name in __STANDARD_VALUES[op_name]:
        __STANDARD_VALUES[op_name][field_name] = []
        try:
            standard_value_source = __STANDARD_VALUE_SOURCES[op_name][field_name]
        except KeyError:
            raise exceptions.SystemSetupError(
                "Cannot generate standard values for operation {}, field {}. Standard value source is missing"
                .format(op_name, field_name))
        for _i in range(n):
            __STANDARD_VALUES[op_name][field_name].append(standard_value_source())

def get_standard_value(op_name, field_name, i):
    try:
        return __STANDARD_VALUES[op_name][field_name][i]
    except KeyError:
        raise exceptions.SystemSetupError("No standard values generated for operation {}, field {}".format(op_name, field_name))
    except IndexError:
        raise exceptions.SystemSetupError(
            "Standard value index {} out of range for operation {}, field name {} ({} values total)"
            .format(i, op_name, field_name, len(__STANDARD_VALUES[op_name][field_name])))

def register_query_randomization_info(op_name, query_name, parameter_name_options_list, optional_parameters):
    # query_randomization_info is registered at the operation level
    query_randomization_info = loader.QueryRandomizerWorkloadProcessor.QueryRandomizationInfo(query_name,
                                                                                              parameter_name_options_list,
                                                                                              optional_parameters
                                                                                              )
    __QUERY_RANDOMIZATION_INFOS[op_name] = query_randomization_info

def get_query_randomization_info(op_name):
    try:
        return  __QUERY_RANDOMIZATION_INFOS[op_name]
    except KeyError:
        return loader.QueryRandomizerWorkloadProcessor.DEFAULT_QUERY_RANDOMIZATION_INFO # If nothing is registered, return the default.

# only intended for tests
def _unregister_param_source_for_name(name):
    # We intentionally do not specify a default value if the key does not exist. If we try to remove a key that we didn't insert then
    # something is fishy with the test and we'd rather know early.
    __PARAM_SOURCES_BY_NAME.pop(name)

# only intended for tests
def _clear_standard_values():
    __STANDARD_VALUES = {}
    __STANDARD_VALUE_SOURCES = {}

def _clear_query_randomization_infos():
    __QUERY_RANDOMIZATION_INFOS = {}

# Default
class ParamSource:
    """
    A `ParamSource` captures the parameters for a given operation.
     Solr Orbit will create one global ParamSource for each operation and will then
     invoke `#partition()` to get a `ParamSource` instance for each client. During the benchmark, `#params()` will be called repeatedly
     before invoking the corresponding runner (that will actually execute the operation against Solr).
    """

    def __init__(self, workload, params, **kwargs):
        """
        Creates a new ParamSource instance.

        :param workload:  The current workload definition
        :param params: A hash of all parameters that have been extracted for this operation.
        """
        self.workload = workload
        self._params = params
        self.kwargs = kwargs

    def partition(self, partition_index, total_partitions):
        """
        This method will be invoked by ASB at the beginning of the lifecycle. It splits a parameter source per client. If the
        corresponding operation is idempotent, return `self` (e.g. for queries). If the corresponding operation has side-effects and it
        matters which client executes which part (e.g. an index operation from a source file), return the relevant part.

        Do NOT assume that you can share state between ParamSource objects in different partitions (technical explanation: each client
        will be a dedicated process, so each object of a `ParamSource` lives in its own process and hence cannot share state with other
        instances).

        :param partition_index: The current partition for which a parameter source is needed. It is in the range [0, `total_partitions`).
        :param total_partitions: The total number of partitions (i.e. clients).
        :return: A parameter source for the current partition.
        """
        return self

    @property
    def infinite(self):
        # for bwc
        return self.size() is None

    # Deprecated
    def size(self):
        """
        OSB has two modes in which it can run:

        * It will either run an operation for a pre-determined number of times or
        * It can run until the parameter source is exhausted.

        In the former case, you should determine the number of times that `#params()` will be invoked. With that number, ASB can show
        the progress made so far to the user. In the latter case, return ``None``.

        :return:  The "size" of this parameter source or ``None`` if should run eternally.
        """
        return None

    def params(self):
        """
        :return: A hash containing the parameters that will be provided to the corresponding operation runner (key: parameter name,
        value: parameter value).
        """
        return self._params

    def _client_params(self):
        """
        For use when a ParamSource does not propagate self._params but does use the cluster client under the hood

        :return: all applicable parameters that are global to ASB and apply to the cluster client
        """
        return {
            "request-timeout": self._params.get("request-timeout"),
            "headers": self._params.get("headers"),
            "opaque-id": self._params.get("opaque-id")
        }


class DelegatingParamSource(ParamSource):
    def __init__(self, workload, params, delegate, **kwargs):
        super().__init__(workload, params, **kwargs)
        self.delegate = delegate

    def params(self):
        return self.delegate(self.workload, self._params, **self.kwargs)


class SleepParamSource(ParamSource):
    def __init__(self, workload, params, **kwargs):
        super().__init__(workload, params, **kwargs)
        try:
            duration = params["duration"]
        except KeyError:
            raise exceptions.InvalidSyntax("parameter 'duration' is mandatory for sleep operation")

        if not isinstance(duration, numbers.Number):
            raise exceptions.InvalidSyntax("parameter 'duration' for sleep operation must be a number")
        if duration < 0:
            raise exceptions.InvalidSyntax("parameter 'duration' must be non-negative but was {}".format(duration))

    def params(self):
        return dict(self._params)


class DeleteCollectionParamSource(ParamSource):
    """
    Param source for the Solr ``delete-collection`` operation.

    Reads collection names from ``workload.collections`` and returns them as
    ``{"collection": name}`` so that ``SolrDeleteCollection`` knows what to delete.
    When an explicit ``"collection"`` is in the operation params it is used as-is.
    """

    def __init__(self, workload, params, **kwargs):
        super().__init__(workload, params, **kwargs)
        self.collection_names = []
        target = params.get("collection") or params.get("index")
        if target:
            self.collection_names = [target] if isinstance(target, str) else list(target)
        elif getattr(workload, "collections", []):
            self.collection_names = [c.name for c in workload.collections]
        else:
            raise exceptions.InvalidSyntax("delete-collection operation targets no collection")

    def params(self):
        p = {}
        p.update(self._params)
        # Pass only the first collection; if multiple are needed the workload should
        # run separate delete-collection tasks or use an explicit "collection" param.
        p["collection"] = self.collection_names[0] if self.collection_names else None
        return p


class CreateCollectionParamSource(ParamSource):
    """
    Param source for the Solr ``create-collection`` operation.

    Reads collection definitions from ``workload.collections`` and returns them
    as ``{"collection": name, "configset": name, "configset-path": path, ...}``
    so that ``SolrCreateCollection`` can create and upload the collection.
    """

    def __init__(self, workload, params, **kwargs):
        super().__init__(workload, params, **kwargs)
        self.collection_def = {}
        target = params.get("collection") or params.get("index")
        collections = getattr(workload, "collections", [])
        if target:
            col = next((c for c in collections if c.name == target), None)
            if col:
                self.collection_def = {
                    "collection": col.name,
                    "configset": col.configset,
                    "configset-path": col.configset_path,
                    "num-shards": col.num_shards,
                    "replication-factor": col.replication_factor,
                    "pull-replicas": col.pull_replicas,
                    "tlog-replicas": col.tlog_replicas,
                }
            else:
                self.collection_def = {"collection": target}
        elif collections:
            col = collections[0]
            self.collection_def = {
                "collection": col.name,
                "configset": col.configset,
                "configset-path": col.configset_path,
                "num-shards": col.num_shards,
                "replication-factor": col.replication_factor,
                "pull-replicas": col.pull_replicas,
                "tlog-replicas": col.tlog_replicas,
            }
        else:
            raise exceptions.InvalidSyntax("create-collection operation targets no collection")

    def params(self):
        p = {}
        p.update(self._params)
        p.update(self.collection_def)
        # Allow operation-level params (typically supplied via --workload-params
        # at template-render time) to override the Collection's topology fields.
        # Path fields (configset, configset-path) are not overridable here:
        # the loader has already resolved configset-path to an absolute path
        # against the workload directory, and the operation template only
        # carries the unresolved relative form.
        for key in ("num-shards", "replication-factor", "tlog-replicas", "pull-replicas"):
            if key in self._params:
                p[key] = self._params[key]
        return p


class SearchParamSource(ParamSource):
    def __init__(self, workload, params, **kwargs):
        super().__init__(workload, params, **kwargs)
        target_name = get_target(workload, params)
        type_name = params.get("type")
        if params.get("data-stream") and type_name:
            raise exceptions.InvalidSyntax(
                f"'type' not supported with 'data-stream' for operation '{kwargs.get('operation_name')}'")
        request_cache = params.get("cache", None)
        detailed_results = params.get("detailed-results", False)
        calculate_recall = params.get("calculate-recall", True)
        query_body = params.get("body", None)
        pages = params.get("pages", None)
        results_per_page = params.get("results-per-page", None)
        request_params = params.get("request-params", {})
        response_compression_enabled = params.get("response-compression-enabled", True)
        with_point_in_time_from = params.get("with-point-in-time-from", None)
        profile_metrics = params.get("profile-metrics", None)
        profile_metrics_sample_size = params.get("profile-metrics-sample-size", 0)

        self.query_params = {
            "index": target_name,
            "type": type_name,
            "cache": request_cache,
            "detailed-results": detailed_results,
            "calculate-recall": calculate_recall,
            "request-params": request_params,
            "response-compression-enabled": response_compression_enabled,
            "body": query_body
        }

        if not target_name:
            raise exceptions.InvalidSyntax(
                f"'index' or 'data-stream' is mandatory and is missing for operation '{kwargs.get('operation_name')}'")

        if pages:
            self.query_params["pages"] = pages
        if results_per_page:
            self.query_params["results-per-page"] = results_per_page
        if with_point_in_time_from:
            self.query_params["with-point-in-time-from"] = with_point_in_time_from
        if profile_metrics:
            self.query_params["profile-metrics"] = profile_metrics
            self.query_params["profile-metrics-sample-size"] = profile_metrics_sample_size
        if "assertions" in params:
            if not detailed_results:
                # for paginated queries the value does not matter because detailed results are always retrieved.
                is_paginated = bool(pages)
                if not is_paginated:
                    raise exceptions.InvalidSyntax("The property [detailed-results] must be [true] if assertions are defined")
            self.query_params["assertions"] = params["assertions"]

        # Ensure we pass global parameters
        self.query_params.update(self._client_params())

    def params(self):
        return self.query_params


class IndexIdConflict(Enum):
    """
    Determines which id conflicts to simulate during indexing.

    * NoConflicts: Produce no id conflicts
    * SequentialConflicts: A document id is replaced with a document id with a sequentially increasing id
    * RandomConflicts: A document id is replaced with a document id with a random other id

    Note that this assumes that each document in the benchmark corpus has an id between [1, size_of(corpus)]
    """
    NoConflicts = 0
    SequentialConflicts = 1
    RandomConflicts = 2


class BulkIndexParamSource(ParamSource):
    def __init__(self, workload, params, **kwargs):
        super().__init__(workload, params, **kwargs)
        id_conflicts = params.get("conflicts", None)
        if not id_conflicts:
            self.id_conflicts = IndexIdConflict.NoConflicts
        elif id_conflicts == "sequential":
            self.id_conflicts = IndexIdConflict.SequentialConflicts
        elif id_conflicts == "random":
            self.id_conflicts = IndexIdConflict.RandomConflicts
        else:
            raise exceptions.InvalidSyntax("Unknown 'conflicts' setting [%s]" % id_conflicts)

        if "data-streams" in params and self.id_conflicts != IndexIdConflict.NoConflicts:
            raise exceptions.InvalidSyntax("'conflicts' cannot be used with 'data-streams'")

        if self.id_conflicts != IndexIdConflict.NoConflicts:
            self.conflict_probability = self.float_param(params, name="conflict-probability", default_value=25, min_value=0, max_value=100,
                                                         min_operator=operator.lt)
            self.on_conflict = params.get("on-conflict", "index")
            if self.on_conflict not in ["index", "update"]:
                raise exceptions.InvalidSyntax("Unknown 'on-conflict' setting [{}]".format(self.on_conflict))
            self.recency = self.float_param(params, name="recency", default_value=0, min_value=0, max_value=1, min_operator=operator.lt)

        else:
            self.conflict_probability = None
            self.on_conflict = None
            self.recency = None

        self.corpora = self.used_corpora(workload, params)

        if len(self.corpora) == 0:
            raise exceptions.InvalidSyntax(f"There is no document corpus definition for workload {workload}. You must add at "
                                           f"least one before making bulk requests to the target cluster.")

        for corpus in self.corpora:
            for document_set in corpus.documents:
                if document_set.includes_action_and_meta_data and self.id_conflicts != IndexIdConflict.NoConflicts:
                    file_name = document_set.document_archive if document_set.has_compressed_corpus() else document_set.document_file

                    raise exceptions.InvalidSyntax("Cannot generate id conflicts [%s] as [%s] in document corpus [%s] already contains an "
                                                   "action and meta-data line." % (id_conflicts, file_name, corpus))

        self.pipeline = params.get("pipeline", None)
        try:
            self.bulk_size = int(params["bulk-size"])
            if self.bulk_size <= 0:
                raise exceptions.InvalidSyntax("'bulk-size' must be positive but was %d" % self.bulk_size)
        except KeyError:
            raise exceptions.InvalidSyntax("Mandatory parameter 'bulk-size' is missing")
        except ValueError:
            raise exceptions.InvalidSyntax("'bulk-size' must be numeric")

        try:
            self.batch_size = int(params.get("batch-size", self.bulk_size))
            if self.batch_size <= 0:
                raise exceptions.InvalidSyntax("'batch-size' must be positive but was %d" % self.batch_size)
            if self.batch_size < self.bulk_size:
                raise exceptions.InvalidSyntax("'batch-size' must be greater than or equal to 'bulk-size'")
            if self.batch_size % self.bulk_size != 0:
                raise exceptions.InvalidSyntax("'batch-size' must be a multiple of 'bulk-size'")
        except ValueError:
            raise exceptions.InvalidSyntax("'batch-size' must be numeric")

        self.ingest_percentage = self.float_param(params, name="ingest-percentage", default_value=100, min_value=0, max_value=100)
        self.looped = params.get("looped", False)
        self.param_source = PartitionBulkIndexParamSource(self.corpora, self.batch_size, self.bulk_size,
                                                          self.ingest_percentage, self.id_conflicts,
                                                          self.conflict_probability, self.on_conflict,
                                                          self.recency, self.pipeline, self.looped, self._params)

    def float_param(self, params, name, default_value, min_value, max_value, min_operator=operator.le):
        try:
            value = float(params.get(name, default_value))
            if min_operator(value, min_value) or value > max_value:
                interval_min = "(" if min_operator is operator.le else "["
                raise exceptions.InvalidSyntax(
                    "'{}' must be in the range {}{:.1f}, {:.1f}] but was {:.1f}".format(name, interval_min, min_value, max_value, value))
            return value
        except ValueError:
            raise exceptions.InvalidSyntax("'{}' must be numeric".format(name))

    def used_corpora(self, t, params):
        corpora = []
        workload_corpora_names = [corpus.name for corpus in t.corpora]
        corpora_names = params.get("corpora", workload_corpora_names)
        if isinstance(corpora_names, str):
            corpora_names = [corpora_names]

        for corpus in t.corpora:
            if corpus.name in corpora_names:
                filtered_corpus = corpus.filter(source_format=workload.Documents.SOURCE_FORMAT_BULK,
                                                target_collections=params.get("indices"))
                if filtered_corpus.streaming_ingestion or \
                   filtered_corpus.number_of_documents(source_format=workload.Documents.SOURCE_FORMAT_BULK) > 0:
                    corpora.append(filtered_corpus)

        # the workload has corpora but none of them match
        if t.corpora and not corpora:
            raise exceptions.BenchmarkAssertionError("The provided corpus %s does not match any of the corpora %s." %
                                                 (corpora_names, workload_corpora_names))

        return corpora

    def partition(self, partition_index, total_partitions):
        # register the new partition internally
        self.param_source.partition(partition_index, total_partitions)
        return self.param_source

    def params(self):
        raise exceptions.BenchmarkError("Do not use a BulkIndexParamSource without partitioning")


class PartitionBulkIndexParamSource:
    def __init__(self, corpora, batch_size, bulk_size, ingest_percentage, id_conflicts, conflict_probability,
                 on_conflict, recency, pipeline=None, looped = False,  original_params=None):
        """

        :param corpora: Specification of affected document corpora.
        :param batch_size: The number of documents to read in one go.
        :param bulk_size: The size of bulk index operations (number of documents per bulk).
        :param ingest_percentage: A number between (0.0, 100.0] that defines how much of the whole corpus should be ingested.
        :param id_conflicts: The type of id conflicts.
        :param conflict_probability: A number between (0.0, 100.0] that defines the probability that a document is replaced by another one.
        :param on_conflict: A string indicating which action should be taken on id conflicts (either "index" or "update").
        :param recency: A number between [0.0, 1.0] indicating whether to bias generation of conflicting ids towards more recent ones.
                        May be None.
        :param pipeline: The name of the ingest pipeline to run.
        :param looped: Set to True for looped mode where bulk requests are repeated from the beginning when entire corpus was ingested.
        :param original_params: The original dict passed to the parent parameter source.
        """
        self.corpora = corpora
        self.partitions = []
        self.total_partitions = None
        self.batch_size = batch_size
        self.bulk_size = bulk_size
        self.ingest_percentage = ingest_percentage
        self.id_conflicts = id_conflicts
        self.conflict_probability = conflict_probability
        self.on_conflict = on_conflict
        self.recency = recency
        self.pipeline = pipeline
        self.looped = looped
        self.original_params = original_params
        # this is only intended for unit-testing
        self.create_reader = original_params.pop("__create_reader", create_default_reader)
        self.current_bulk = 0
        # use a value > 0 so task_progress returns a sensible value
        self.total_bulks = 1
        self.infinite = False
        self.streaming_ingestion = corpora[0].streaming_ingestion

    def partition(self, partition_index, total_partitions):
        if self.total_partitions is None:
            self.total_partitions = total_partitions
        elif self.total_partitions != total_partitions:
            raise exceptions.BenchmarkAssertionError(
                f"Total partitions is expected to be [{self.total_partitions}] but was [{total_partitions}]")
        self.partitions.append(partition_index)

    def params(self):
        if self.current_bulk == 0:
            self._init_internal_params()
        # self.internal_params always reads all files. This is necessary to ensure we terminate early in case
        # the user has specified ingest percentage.
        if not self.streaming_ingestion and self.current_bulk == self.total_bulks:
            if self.looped:
                self.current_bulk = 0
                self._init_internal_params()
            else:
                raise StopIteration()
        self.current_bulk += 1
        return next(self.internal_params)

    def _init_internal_params(self):
        # contains a continuous range of client ids
        self.partitions = sorted(self.partitions)
        start_index = self.partitions[0]
        end_index = self.partitions[-1]

        self.internal_params = bulk_data_based(self.total_partitions, start_index, end_index, self.corpora,
                                               self.batch_size, self.bulk_size, self.id_conflicts,
                                               self.conflict_probability, self.on_conflict, self.recency,
                                               self.pipeline, self.original_params, self.create_reader)

        if not self.streaming_ingestion:
            all_bulks = number_of_bulks(self.corpora, start_index, end_index, self.total_partitions, self.bulk_size)
            self.total_bulks = math.ceil((all_bulks * self.ingest_percentage) / 100)

    @property
    def task_progress(self):
        return (IngestionManager.rd_index.value * IngestionManager.chunk_size/1000, 'GB') if self.streaming_ingestion else (self.current_bulk / self.total_bulks, '%')



def get_target(workload, params):
    if len(workload.collections) == 1:
        default_target = workload.collections[0].name
    else:
        default_target = None
    target_name = params.get("index") or params.get("collection")
    if not target_name:
        target_name = params.get("data-stream", default_target)
    return target_name

def number_of_bulks(corpora, start_partition_index, end_partition_index, total_partitions, bulk_size):
    """
    :return: The number of bulk operations that the given client will issue.
    """
    bulks = 0
    for corpus in corpora:
        for docs in corpus.documents:
            _, num_docs, _ = bounds(docs.number_of_documents, start_partition_index, end_partition_index,
                                    total_partitions, docs.includes_action_and_meta_data)
            complete_bulks, rest = (num_docs // bulk_size, num_docs % bulk_size)
            bulks += complete_bulks
            if rest > 0:
                bulks += 1
    return bulks


def build_conflicting_ids(conflicts, docs_to_index, offset, shuffle=random.shuffle):
    if conflicts is None or conflicts == IndexIdConflict.NoConflicts:
        return None
    all_ids = [0] * docs_to_index
    for i in range(docs_to_index):
        # always consider the offset as each client will index its own range and we don't want uncontrolled conflicts across clients
        all_ids[i] = "%010d" % (offset + i)
    if conflicts == IndexIdConflict.RandomConflicts:
        shuffle(all_ids)
    return all_ids


def chain(*iterables):
    """
    Chains the given iterables similar to `itertools.chain` except that it also respects the context manager contract.

    :param iterables: A number of iterable that should be chained.
    :return: An iterable that will delegate to all provided iterables in turn.
    """
    for it in iterables:
        # execute within a context
        with it:
            for element in it:
                yield element


def create_default_reader(corpus, docs, offset, num_lines, num_docs, batch_size, bulk_size, id_conflicts, conflict_probability,
                          on_conflict, recency):
    source = Slice(io.MmapSource, offset, num_lines, corpus, docs)
    target = None
    use_create = False
    if docs.target_collection:
        target = docs.target_collection

    if docs.includes_action_and_meta_data:
        return SourceOnlyIndexDataReader(docs.document_file, batch_size, bulk_size, source, target, docs.target_type)
    else:
        am_handler = GenerateActionMetaData(target, docs.target_type,
                                            build_conflicting_ids(id_conflicts, num_docs, offset), conflict_probability,
                                            on_conflict, recency, use_create=use_create)
        return MetadataIndexDataReader(docs.document_file, batch_size, bulk_size, source, am_handler, target, docs.target_type)


def create_readers(num_clients, start_client_index, end_client_index, corpora, batch_size, bulk_size, id_conflicts,
                   conflict_probability, on_conflict, recency, create_reader):
    logger = logging.getLogger(__name__)
    readers = []
    for corpus in corpora:
        for docs in corpus.documents:
            if corpus.streaming_ingestion:
                offset = num_lines = num_docs = 0
                readers.append(create_reader(corpus, docs, offset, num_lines, num_docs, batch_size, bulk_size, id_conflicts,
                                             conflict_probability, on_conflict, recency))
            else:
                offset, num_docs, num_lines = bounds(docs.number_of_documents, start_client_index, end_client_index,
                                                     num_clients, docs.includes_action_and_meta_data)
                if num_docs > 0:
                    target = f"{docs.target_collection}/{docs.target_type}" if docs.target_collection else "/"
                    logger.info("Task-relative clients at index [%d-%d] will bulk index [%d] docs starting from line offset [%d] for [%s] "
                                "from corpus [%s].", start_client_index, end_client_index, num_docs, offset,
                                target, corpus.name)
                    readers.append(create_reader(corpus, docs, offset, num_lines, num_docs, batch_size, bulk_size, id_conflicts,
                                                 conflict_probability, on_conflict, recency))
                else:
                    logger.info("Task-relative clients at index [%d-%d] skip [%s] (no documents to read).",
                                start_client_index, end_client_index, corpus.name)
    return readers


def bounds(total_docs, start_client_index, end_client_index, num_clients, includes_action_and_meta_data):
    """

    Calculates the start offset and number of documents for a range of clients.

    :param total_docs: The total number of documents to index.
    :param start_client_index: The first client index.  Must be in the range [0, `num_clients').
    :param end_client_index: The last client index.  Must be in the range [0, `num_clients').
    :param num_clients: The total number of clients that will run bulk index operations.
    :param includes_action_and_meta_data: Whether the source file already includes the action and meta-data line.
    :return: A tuple containing: the start offset (in lines) for the document corpus, the number documents that the
             clients should index, and the number of lines that the clients should read.
    """
    source_lines_per_doc = 2 if includes_action_and_meta_data else 1

    docs_per_client = total_docs / num_clients

    start_offset_docs = round(docs_per_client * start_client_index)
    end_offset_docs = round(docs_per_client * (end_client_index + 1))

    offset_lines = start_offset_docs * source_lines_per_doc
    docs = end_offset_docs - start_offset_docs
    lines = docs * source_lines_per_doc

    return offset_lines, docs, lines


def bulk_generator(readers, pipeline, original_params):
    bulk_id = 0
    for index, type, batch in readers:
        # each batch can contain of one or more bulks
        for docs_in_bulk, bulk in batch:
            bulk_id += 1
            bulk_params = {
                "index": index,
                "type": type,
                # For our implementation it's always present. Either the original source file already contains this line or the generator
                # has added it.
                "action-metadata-present": True,
                "body": bulk,
                # This is not always equal to the bulk_size we get as parameter. The last bulk may be less than the bulk size.
                "bulk-size": docs_in_bulk,
                "unit": "docs"
            }
            if pipeline:
                bulk_params["pipeline"] = pipeline

            params = original_params.copy()
            params.update(bulk_params)
            yield params


def bulk_data_based(num_clients, start_client_index, end_client_index, corpora, batch_size, bulk_size, id_conflicts,
                    conflict_probability, on_conflict, recency, pipeline, original_params, create_reader=create_default_reader):
    """
    Calculates the necessary schedule for bulk operations.

    :param num_clients: The total number of clients that will run the bulk operation.
    :param start_client_index: The first client for which we calculated the schedule. Must be in the range [0, `num_clients').
    :param end_client_index: The last client for which we calculated the schedule. Must be in the range [0, `num_clients').
    :param corpora: Specification of affected document corpora.
    :param batch_size: The number of documents to read in one go.
    :param bulk_size: The size of bulk index operations (number of documents per bulk).
    :param id_conflicts: The type of id conflicts to simulate.
    :param conflict_probability: A number between (0.0, 100.0] that defines the probability that a document is replaced by another one.
    :param on_conflict: A string indicating which action should be taken on id conflicts (either "index" or "update").
    :param recency: A number between [0.0, 1.0] indicating whether to bias generation of conflicting ids towards more recent ones.
                    May be None.
    :param pipeline: Name of the ingest pipeline to use. May be None.
    :param original_params: A dict of original parameters that were passed
    from the workload. They will be merged into the returned parameters.
    :param create_reader: A function to create the index reader. By default a file based index reader will be created.
                      This parameter is
                      intended for testing only.
    :return: A generator for the bulk operations of the given client.
    """
    readers = create_readers(num_clients, start_client_index, end_client_index, corpora, batch_size, bulk_size,
                             id_conflicts, conflict_probability, on_conflict, recency, create_reader)
    return bulk_generator(chain(*readers), pipeline, original_params)


class GenerateActionMetaData:
    RECENCY_SLOPE = 30

    def __init__(self, index_name, type_name, conflicting_ids=None, conflict_probability=None, on_conflict=None, recency=None,
                 rand=random.random, randint=random.randint, randexp=random.expovariate, use_create=False):
        if type_name:
            self.meta_data_index_with_id = '{"index": {"_index": "%s", "_type": "%s", "_id": "%s"}}\n' % \
                                           (index_name, type_name, "%s")
            self.meta_data_update_with_id = '{"update": {"_index": "%s", "_type": "%s", "_id": "%s"}}\n' % \
                                            (index_name, type_name, "%s")
            self.meta_data_index_no_id = '{"index": {"_index": "%s", "_type": "%s"}}\n' % (index_name, type_name)
        else:
            self.meta_data_index_with_id = '{"index": {"_index": "%s", "_id": "%s"}}\n' % (index_name, "%s")
            self.meta_data_update_with_id = '{"update": {"_index": "%s", "_id": "%s"}}\n' % (index_name, "%s")
            self.meta_data_index_no_id = '{"index": {"_index": "%s"}}\n' % index_name
            self.meta_data_create_no_id = '{"create": {"_index": "%s"}}\n' % index_name
        if use_create and conflicting_ids:
            raise exceptions.BenchmarkError("Index mode '_create' cannot be used with conflicting ids")
        self.conflicting_ids = conflicting_ids
        self.on_conflict = on_conflict
        self.use_create = use_create
        # random() produces numbers between 0 and 1 and the user denotes the probability in percentage between 0 and 100
        self.conflict_probability = conflict_probability / 100.0 if conflict_probability is not None else 0
        self.recency = recency if recency is not None else 0

        self.rand = rand
        self.randint = randint
        self.randexp = randexp
        self.id_up_to = 0

    @property
    def is_constant(self):
        """
        :return: True iff the iterator will always return the same value.
        """
        return self.conflicting_ids is None

    def __iter__(self):
        return self

    def __next__(self):
        if self.conflicting_ids is not None:
            if self.conflict_probability and self.id_up_to > 0 and self.rand() <= self.conflict_probability:
                # a recency of zero means that we don't care about recency and just take a random number
                # within the whole interval.
                if self.recency == 0:
                    idx = self.randint(0, self.id_up_to - 1)
                else:
                    # A recency > 0 biases id selection towards more recent ids. The recency parameter decides
                    # by how much we bias. See docs for the resulting curve.
                    #
                    # idx_range is in the interval [0, 1].
                    idx_range = min(self.randexp(GenerateActionMetaData.RECENCY_SLOPE * self.recency), 1)
                    # the resulting index is in the range [0, self.id_up_to). Note that a smaller idx_range
                    # biases towards more recently used ids (higher indexes).
                    idx = round((self.id_up_to - 1) * (1 - idx_range))

                doc_id = self.conflicting_ids[idx]
                action = self.on_conflict
            else:
                if self.id_up_to >= len(self.conflicting_ids):
                    raise StopIteration()
                doc_id = self.conflicting_ids[self.id_up_to]
                self.id_up_to += 1
                action = "index"

            if action == "index":
                return "index", self.meta_data_index_with_id % doc_id
            elif action == "update":
                return "update", self.meta_data_update_with_id % doc_id
            else:
                raise exceptions.BenchmarkAssertionError("Unknown action [{}]".format(action))
        else:
            if self.use_create:
                return "create", self.meta_data_create_no_id
            return "index", self.meta_data_index_no_id


class Slice:
    def __init__(self, source_class, offset, number_of_lines, corpus, docs):
        self.source_class = source_class
        self.source = None
        self.offset = offset
        self.number_of_lines = number_of_lines
        self.current_line = 0
        self.bulk_size = None
        self.logger = logging.getLogger(__name__)
        self.fh = None
        self.streaming_ingestion = corpus.streaming_ingestion
        self.producer = None
        if self.streaming_ingestion == "aws":
            Slice.data_dir = docs.data_dir
            Slice.base_url = docs.base_url
            Slice.document_file = docs.document_file
            with IngestionManager.lock:
                if IngestionManager.producer_started.value == 0:
                    IngestionManager.producer_started.value = 1
                    self.producer = Slice._start_producer()

    @staticmethod
    def _start_producer():
        client_options_obj = IngestionManager.config.opts("client", "options")
        client_options = getattr(client_options_obj, "all_client_options", {})
        # pylint: disable = import-outside-toplevel
        from osbenchmark.utils.s3_data_producer import S3DataProducer
        bucket = re.sub('^s3://', "", Slice.base_url)
        keys = Slice.document_file
        producer = S3DataProducer(bucket, keys, client_options, Slice.data_dir)
        p = multiprocessing.Process(target=producer.generate_chunked_data)
        p.start()
        return p

    def open(self, file_name, mode, bulk_size):
        self.mode = mode
        self.bulk_size = bulk_size
        if self.streaming_ingestion:
            with IngestionManager.load_empty:
                IngestionManager.load_empty.wait()
                self._open_next()
        else:
            self.source = self.source_class(file_name, mode).open()
            self.logger.info("Will read [%d] lines from [%s] starting from line [%d] with bulk size [%d].",
                             self.number_of_lines, file_name, self.offset, self.bulk_size)
            start = time.perf_counter()
            io.skip_lines(file_name, self.source, self.offset)
            end = time.perf_counter()
            self.logger.debug("Skipping [%d] lines took [%f] s.", self.offset, end - start)
        return self

    def close(self):
        if self.streaming_ingestion:
            if self.producer:
                self.producer.join()
        else:
            self.source.close()
            self.source = None

    def __iter__(self):
        return self

    def _open_next(self):
        with IngestionManager.load_empty:
            while IngestionManager.rd_index.value == IngestionManager.wr_count.value:
                IngestionManager.load_empty.wait()
            if os.path.getsize(os.path.join(self.data_dir, f"chunk-{IngestionManager.rd_index.value:05d}")) == 0:
                return False
            self.rd_idx = IngestionManager.rd_index.value
            IngestionManager.rd_index.value += 1
            if IngestionManager.wr_count.value - self.rd_idx < IngestionManager.ballast:
                with IngestionManager.load_full:
                    IngestionManager.load_full.notify()
        self.fh = self.source_class(os.path.join(self.data_dir, f"chunk-{self.rd_idx:05d}"), self.mode).open()
        return True

    def _fill_bulk(self):
        if not self.fh:
            raise StopIteration()
        want = self.bulk_size
        rsl = list()
        while want > 0:
            lines = self.fh.readlines(want)
            rsl.extend(lines)
            n = len(lines)
            if n < want:
                os.remove(os.path.join(self.data_dir, f"chunk-{self.rd_idx:05d}"))
                self.fh = None
                if not self._open_next():
                    if n == 0:
                        raise StopIteration()
                    else:
                        return rsl
            want -= n
        return rsl

    def __next__(self):
        if self.streaming_ingestion:
            return self._fill_bulk()

        if self.current_line >= self.number_of_lines:
            raise StopIteration()
        else:
            # ensure we don't read past the allowed number of lines.
            lines = self.source.readlines(min(self.bulk_size, self.number_of_lines - self.current_line))
            self.current_line += len(lines)
            if len(lines) == 0:
                raise StopIteration()
            return lines

    def __str__(self):
        return "%s[%d;%d]" % (self.source, self.offset, self.offset + self.number_of_lines)


class IndexDataReader:
    """
    Reads a file in bulks into an array and also adds a meta-data line before each document if necessary.

    This implementation also supports batching. This means that you can specify batch_size = N * bulk_size, where N
    is any natural number >= 1. This makes file reading more efficient for small bulk sizes.
    """

    def __init__(self, data_file, batch_size, bulk_size, file_source, index_name, type_name):
        self.data_file = data_file
        self.batch_size = batch_size
        self.bulk_size = bulk_size
        self.file_source = file_source
        self.index_name = index_name
        self.type_name = type_name

    def __enter__(self):
        self.file_source.open(self.data_file, "rt", self.bulk_size)
        return self

    def __iter__(self):
        return self

    def __next__(self):
        """
        Returns lines for N bulk requests (where N is bulk_size / batch_size)
        """
        batch = []
        try:
            docs_in_batch = 0
            while docs_in_batch < self.batch_size:
                try:
                    docs_in_bulk, bulk = self.read_bulk()
                except StopIteration:
                    break
                if docs_in_bulk == 0:
                    break
                docs_in_batch += docs_in_bulk
                batch.append((docs_in_bulk, b"".join(bulk)))
            if docs_in_batch == 0:
                raise StopIteration()
            return self.index_name, self.type_name, batch
        except IOError:
            logging.getLogger(__name__).exception("Could not read [%s]", self.data_file)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file_source.close()
        return False


class MetadataIndexDataReader(IndexDataReader):
    def __init__(self, data_file, batch_size, bulk_size, file_source, action_metadata, index_name, type_name):
        super().__init__(data_file, batch_size, bulk_size, file_source, index_name, type_name)
        self.action_metadata = action_metadata
        self.action_metadata_line = None

    def __enter__(self):
        super().__enter__()
        if self.action_metadata.is_constant:
            _, self.action_metadata_line = next(self.action_metadata)
            self.read_bulk = self._read_bulk_fast
        else:
            self.read_bulk = self._read_bulk_regular
        return self

    def _read_bulk_fast(self):
        """
        Special-case implementation for bulk data files where the action and meta-data line is always identical.
        """
        current_bulk = []
        # hoist
        action_metadata_line = self.action_metadata_line.encode("utf-8")
        docs = next(self.file_source)

        for doc in docs:
            current_bulk.append(action_metadata_line)
            current_bulk.append(doc)
        return len(docs), current_bulk

    def _read_bulk_regular(self):
        """
        General case implementation for bulk files. This implementation can cover all cases but is slower when the
        action and meta-data line is always identical.
        """
        current_bulk = []
        docs = next(self.file_source)
        for doc in docs:
            action_metadata_item = next(self.action_metadata)
            if action_metadata_item:
                action_type, action_metadata_line = action_metadata_item
                current_bulk.append(action_metadata_line.encode("utf-8"))
                if action_type == "update":
                    # remove the trailing "\n" as the doc needs to fit on one line
                    doc = doc.strip()
                    current_bulk.append(b"{\"doc\":%s}\n" % doc)
                else:
                    current_bulk.append(doc)
            else:
                current_bulk.append(doc)
        return len(docs), current_bulk


class SourceOnlyIndexDataReader(IndexDataReader):
    def __init__(self, data_file, batch_size, bulk_size, file_source, index_name, type_name):
        # keep batch size as it only considers documents read, not lines read but increase the bulk size as
        # documents are only on every other line.
        super().__init__(data_file, batch_size, bulk_size * 2, file_source, index_name, type_name)

    def read_bulk(self):
        bulk_items = next(self.file_source)
        return len(bulk_items) // 2, bulk_items


register_param_source_for_operation(workload.OperationType.Bulk, BulkIndexParamSource)
register_param_source_for_operation(workload.OperationType.Search, SearchParamSource)
register_param_source_for_operation(workload.OperationType.Sleep, SleepParamSource)

# Also register by name, so users can use it too
register_param_source_for_name("file-reader", BulkIndexParamSource)

# Solr collection param sources — registered by op-type string directly
# (avoids adding CreateCollection/DeleteCollection to the OperationType enum)
__PARAM_SOURCES_BY_OP["create-collection"] = CreateCollectionParamSource
__PARAM_SOURCES_BY_OP["delete-collection"] = DeleteCollectionParamSource


# ---------------------------------------------------------------------------
# Solr-specific param sources
# ---------------------------------------------------------------------------

class SolrSearchParamSource(ParamSource):
    """
    Param source for Solr search operations.

    Supports two modes:

    Mode 1 — Classic Solr params (default when no ``body`` key is present):
      ``q``, ``fl``, ``rows``, ``fq``, ``sort``, ``request-params``

    Mode 2 — JSON Query DSL (when ``body`` key is present):
      Pass the query body dict directly; it is forwarded as-is to
      ``POST /solr/{collection}/query``.

    Common params:
      - ``collection`` — target Solr collection (resolved via get_target() if not explicit)
      - ``host``, ``port``, ``username``, ``password``, ``tls``, ``timeout``
      - ``cache``      — ignored for Solr (kept for API compatibility)
    """

    def __init__(self, workload, params, **kwargs):
        super().__init__(workload, params, **kwargs)
        collection = params.get("collection") or get_target(workload, params)
        if not collection:
            raise exceptions.InvalidSyntax(
                f"'collection' is mandatory and is missing for operation '{kwargs.get('operation_name')}'"
            )

        self.query_params = {
            "collection": collection,
            "host": params.get("host", "localhost"),
            "port": params.get("port", 8983),
            "tls": params.get("tls", False),
            "timeout": params.get("timeout", 30),
        }
        if params.get("username"):
            self.query_params["username"] = params["username"]
        if params.get("password"):
            self.query_params["password"] = params["password"]

        if "body" in params:
            # Mode 2: JSON Query DSL
            self.query_params["body"] = params["body"]
        else:
            # Mode 1: Classic Solr params
            for key in ("q", "fl", "rows", "fq", "sort"):
                if key in params:
                    self.query_params[key] = params[key]
            if "request-params" in params:
                self.query_params["request-params"] = params["request-params"]

    def params(self):
        return self.query_params


class SolrBulkIndexParamSource(BulkIndexParamSource):
    """
    Extends BulkIndexParamSource to inject a default ``collection`` from the workload
    when the operation does not specify one explicitly.

    This mirrors ASB's own get_target() mechanism used by SearchParamSource, ensuring
    that bulk-index operations work without an explicit ``collection`` param as long as
    the workload has exactly one collection defined.
    """

    def __init__(self, workload, params, **kwargs):
        if not params.get("collection") and not params.get("index"):
            target = get_target(workload, params)
            if target:
                params = dict(params)
                params["collection"] = target
        super().__init__(workload, params, **kwargs)


class SolrOptimizeParamSource(ParamSource):
    """
    Param source for Solr optimize operations.

    Resolves the target collection via get_target() when not explicitly specified,
    mirroring ASB's default-index mechanism.
    """

    def __init__(self, workload, params, **kwargs):
        super().__init__(workload, params, **kwargs)
        collection = params.get("collection") or get_target(workload, params)
        self._resolved_params = dict(params)
        if collection:
            self._resolved_params["collection"] = collection

    def params(self):
        return self._resolved_params


register_param_source_for_name("solr-search", SolrSearchParamSource)
register_param_source_for_name("bulk-index", SolrBulkIndexParamSource)
register_param_source_for_name("optimize", SolrOptimizeParamSource)
