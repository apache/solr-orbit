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
import numbers
import re
from enum import Enum, unique, auto

from osbenchmark import exceptions



class Collection:
    """
    Defines a Solr collection (Solr-native equivalent of Index).

    Attributes:
        name:               Collection name.
        configset:          Configset name registered on the cluster.
        configset_path:     Local path to the configset directory (containing conf/).
        num_shards:         Number of shards (default: 1).
        replication_factor: NRT replicas per shard — alias for ``nrtReplicas`` in Solr V2 API (default: 1).
        pull_replicas:      Pull (read-only) replicas per shard (default: 0).
        tlog_replicas:      TLOG replicas per shard (default: 0).
    """

    def __init__(self, name: str, configset: str = None,
                 configset_path: str = None,
                 num_shards: int = 1, replication_factor: int = 1,
                 pull_replicas: int = 0, tlog_replicas: int = 0):
        self.name = name
        self.configset = configset or name
        self.configset_path = configset_path
        self.num_shards = num_shards
        self.replication_factor = replication_factor
        self.pull_replicas = pull_replicas
        self.tlog_replicas = tlog_replicas

    def matches(self, pattern):
        if pattern is None:
            return True
        elif pattern in ["_all", "*"]:
            return True
        elif self.name == pattern:
            return True
        else:
            return False

    def __str__(self):
        return self.name

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return self.name == other.name



class Documents:
    SOURCE_FORMAT_BULK = "bulk"
    SOURCE_FORMAT_HDF5 = "hdf5"
    SOURCE_FORMAT_BIG_ANN = "big-ann"
    SUPPORTED_SOURCE_FORMAT = [SOURCE_FORMAT_BULK, SOURCE_FORMAT_HDF5, SOURCE_FORMAT_BIG_ANN]

    def __init__(self, source_format, document_file=None, document_file_parts=None, document_archive=None, base_url=None, source_url=None,
                 includes_action_and_meta_data=False,
                 number_of_documents=0, compressed_size_in_bytes=0, uncompressed_size_in_bytes=0, target_collection=None,
                 target_type=None, meta_data=None):
        """

        :param source_format: The format of these documents. Mandatory.
        :param document_file: The file name of benchmark documents after decompression. Optional (e.g. for percolation we
        just need a mapping but no documents)
        :param document_file_parts: If the document file is provided as parts, a list of dicts, each holding the filename and file size.
        :param document_archive: The file name of the compressed benchmark document name on the remote server. Optional (e.g. for
        percolation we just need a mapping but no documents)
        :param base_url: The URL from which to load data if they are not available locally. Excludes the file or object name. Optional.
        :param source_url: The full URL to the file or object from which to load data if not available locally. Optional.
        :param includes_action_and_meta_data: True, if the source file already includes the action and meta-data line. False, if it only
        contains documents.
        :param number_of_documents: The number of documents
        in the benchmark document. Needed for proper progress reporting. Only needed if
         a document_archive is given.
        :param compressed_size_in_bytes: The compressed size in bytes of
        the benchmark document. Needed for verification of the download and
         user reporting. Only useful if a document_archive is given (optional but recommended to be set).
        :param uncompressed_size_in_bytes: The size in bytes of the benchmark document after decompressing it.
        Only useful if a document_archive is given (optional but recommended to be set).
        :param target_collection: The Solr collection to target for bulk operations. May be ``None`` if
                                  ``includes_action_and_meta_data`` is ``False``.
        :param target_type: The document type to target for bulk operations. May be ``None`` if ``includes_action_and_meta_data``
                            is ``False``.
        :param meta_data: A dict containing key-value pairs with additional meta-data describing documents. Optional.
        """

        self.source_format = source_format
        self.document_file = document_file
        self.document_file_parts = document_file_parts
        self.document_archive = document_archive
        self.base_url = base_url
        self.source_url = source_url
        self.includes_action_and_meta_data = includes_action_and_meta_data
        self._number_of_documents = number_of_documents
        self._compressed_size_in_bytes = compressed_size_in_bytes
        self._uncompressed_size_in_bytes = uncompressed_size_in_bytes
        self.target_collection = target_collection
        self.target_type = target_type
        self.meta_data = meta_data or {}

    def has_compressed_corpus(self):
        return self.document_archive is not None

    def has_uncompressed_corpus(self):
        return self.document_file is not None

    @property
    def number_of_documents(self):
        return self._number_of_documents

    @number_of_documents.setter
    def number_of_documents(self, value):
        self._number_of_documents = value

    @property
    def uncompressed_size_in_bytes(self):
        return self._uncompressed_size_in_bytes

    @uncompressed_size_in_bytes.setter
    def uncompressed_size_in_bytes(self, value):
        self._uncompressed_size_in_bytes = value

    @property
    def compressed_size_in_bytes(self):
        return self._compressed_size_in_bytes

    @compressed_size_in_bytes.setter
    def compressed_size_in_bytes(self, value):
        self._compressed_size_in_bytes = value

    @property
    def number_of_lines(self):
        if self.includes_action_and_meta_data:
            return self.number_of_documents * 2
        else:
            return self.number_of_documents

    @property
    def is_bulk(self):
        return self.source_format == Documents.SOURCE_FORMAT_BULK

    @property
    def support_file_offset_table(self):
        # Will support create file offset table only for bulk source formats. In future we can move it to
        # a list instead of checking bulk directly
        return self.source_format == Documents.SOURCE_FORMAT_BULK

    @property
    def is_supported_source_format(self):
        return self.source_format in Documents.SUPPORTED_SOURCE_FORMAT

    def __str__(self):
        return "%s documents from %s" % (self.source_format, self.document_file)

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)

    def __hash__(self):
        return hash(self.source_format) ^ hash(self.document_file) ^ hash(self.document_archive) ^ hash(self.base_url) ^ \
               hash(self.source_url) ^ hash(self.includes_action_and_meta_data) ^ hash(self.number_of_documents) ^ \
               hash(self.compressed_size_in_bytes) ^ hash(self.uncompressed_size_in_bytes) ^ hash(self.target_collection) ^ \
               hash(self.target_type) ^ hash(frozenset(self.meta_data.items()))

    def __eq__(self, othr):
        return (isinstance(othr, type(self)) and
                (self.source_format, self.document_file, self.document_archive, self.base_url, self.source_url,
                 self.includes_action_and_meta_data, self.number_of_documents, self.compressed_size_in_bytes,
                 self.uncompressed_size_in_bytes, self.target_collection, self.target_type, self.meta_data) ==
                (othr.source_format, othr.document_file, othr.document_archive, othr.base_url, othr.source_url,
                 othr.includes_action_and_meta_data, othr.number_of_documents, othr.compressed_size_in_bytes,
                 othr.uncompressed_size_in_bytes, othr.target_collection, othr.target_type, othr.meta_data))


class DocumentCorpus:
    def __init__(self, name, documents=None, streaming_ingestion=False, meta_data=None):
        """

        :param name: The name of this document corpus. Mandatory.
        :param documents: A list of ``Documents`` instances that belong to this corpus.
        :param meta_data: A dict containing key-value pairs with additional meta-data describing this corpus. Optional.
        """
        self.name = name
        self.documents = documents or []
        self.streaming_ingestion = streaming_ingestion
        self.meta_data = meta_data or {}

    def number_of_documents(self, source_format):
        num = 0
        for doc in self.documents:
            if doc.source_format == source_format:
                num += doc.number_of_documents
        return num

    def compressed_size_in_bytes(self, source_format):
        num = 0
        for doc in self.documents:
            if doc.source_format == source_format and doc.compressed_size_in_bytes is not None:
                num += doc.compressed_size_in_bytes
            else:
                return None
        return num

    def uncompressed_size_in_bytes(self, source_format):
        num = 0
        for doc in self.documents:
            if doc.source_format == source_format and doc.uncompressed_size_in_bytes is not None:
                num += doc.uncompressed_size_in_bytes
            else:
                return None
        return num

    def filter(self, source_format=None, target_collections=None):
        filtered = []
        for d in self.documents:
            # skip if source format or target collection does not match
            if source_format and d.source_format != source_format:
                continue
            if target_collections and d.target_collection not in target_collections:
                continue

            filtered.append(d)
        return DocumentCorpus(self.name, filtered, streaming_ingestion=self.streaming_ingestion,
                              meta_data=dict(self.meta_data))

    def union(self, other):
        """
        Creates a new corpus based on the current and the provided other corpus. This is not meant as a generic union
        of two arbitrary corpora but rather to unify the documents referenced by two instances of the same corpus. This
        is useful when two tasks reference different subsets of a corpus and a unified view (e.g. for downloading the
        appropriate document files) is required.

        :param other: The other corpus to unify with this one. Must have the same name and meta-data.
        :return: A document corpus instance with the same and meta-data but with documents from both corpora.
        """
        if self.name != other.name:
            raise exceptions.BenchmarkAssertionError(f"Corpora names differ: [{self.name}] and [{other.name}].")
        if self.meta_data != other.meta_data:
            raise exceptions.BenchmarkAssertionError(f"Corpora meta-data differ: [{self.meta_data}] and [{other.meta_data}].")
        if self is other:
            return self
        else:
            return DocumentCorpus(name=self.name,
                                  documents=list(set(self.documents).union(other.documents)),
                                  streaming_ingestion=self.streaming_ingestion,
                                  meta_data=dict(self.meta_data))

    def __str__(self):
        return self.name

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)

    def __hash__(self):
        return hash(self.name) ^ hash(self.documents) ^ hash(frozenset(self.meta_data.items()))

    def __eq__(self, othr):
        return (isinstance(othr, type(self)) and
                (self.name, self.documents, self.meta_data) ==
                (othr.name, othr.documents, othr.meta_data))


class Workload:
    """
    A workload defines the data set that is used. It corresponds loosely to a use case (e.g. logging, event processing, analytics, ...)
    """

    def __init__(self, name, description=None, meta_data=None, test_procedures=None,
                 corpora=None, has_plugins=False, collections=None):
        """

        Creates a new workload.

        :param name: A short, descriptive name for this workload. As per convention, this name should be in lower-case without spaces.
        :param description: A description for this workload (should be less than 80 characters).
        :param meta_data: An optional dict of meta-data elements to attach to each metrics record. Default: {}.
        :param test_procedures: A list of one or more test_procedures to use.
        Precondition: If the list is non-empty it contains exactly one element
        with its ``default`` property set to ``True``.
        :param corpora: A list of document corpus definitions for this workload. May be None.
        :param has_plugins: True iff the workload also defines plugins (e.g. custom runners or parameter sources).
        :param collections: A list of Solr collections for this workload. May be None.
        """
        self.name = name
        self.meta_data = meta_data if meta_data else {}
        self.description = description if description is not None else ""
        self.test_procedures = test_procedures if test_procedures else []
        self.collections = collections if collections else []
        self.corpora = corpora if corpora else []
        self.has_plugins = has_plugins

    @property
    def default_test_procedure(self):
        for test_procedure in self.test_procedures:
            if test_procedure.default:
                return test_procedure
        # This should only happen if we don't have any test_procedures
        return None

    @property
    def selected_test_procedure(self):
        for test_procedure in self.test_procedures:
            if test_procedure.selected:
                return test_procedure
        return None

    @property
    def selected_test_procedure_or_default(self):
        selected = self.selected_test_procedure
        return selected if selected else self.default_test_procedure

    def find_test_procedure_or_default(self, name):
        """
        :param name: The name of the test_procedure to find.
        :return: The test_procedure with the given name. The default test_procedure, if the name is "" or ``None``.
        """
        if name in [None, ""]:
            return self.default_test_procedure
        else:
            return self.find_test_procedure(name)

    def find_test_procedure(self, name):
        for test_procedure in self.test_procedures:
            if test_procedure.name == name:
                return test_procedure
        raise exceptions.InvalidName("Unknown test_procedure [%s] for workload [%s]" % (name, self.name))

    @property
    def number_of_documents(self):
        num_docs = 0
        for corpus in self.corpora:
            # TODO #341: Improve API to let users define what they want (everything, just specific types, ...)
            num_docs += corpus.number_of_documents(Documents.SOURCE_FORMAT_BULK)
        return num_docs

    @property
    def compressed_size_in_bytes(self):
        size = 0
        for corpus in self.corpora:
            # TODO #341: Improve API to let users define what they want (everything, just specific types, ...)
            curr_size = corpus.compressed_size_in_bytes(Documents.SOURCE_FORMAT_BULK)
            if curr_size is not None:
                size += curr_size
            else:
                return None
        return size

    @property
    def uncompressed_size_in_bytes(self):
        size = 0
        for corpus in self.corpora:
            # TODO #341: Improve API to let users define what they want (everything, just specific types, ...)
            curr_size = corpus.uncompressed_size_in_bytes(Documents.SOURCE_FORMAT_BULK)
            if curr_size is not None:
                size += curr_size
            else:
                return None
        return size

    def __str__(self):
        return self.name

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)

    def __hash__(self):
        return hash(self.name) ^ hash(self.meta_data) ^ hash(self.description) ^ hash(self.test_procedures) ^ \
               hash(self.corpora)

    def __eq__(self, othr):
        return (isinstance(othr, type(self)) and
                (self.name, self.meta_data, self.description, self.test_procedures, self.collections, self.corpora) ==
                (othr.name, othr.meta_data, othr.description, othr.test_procedures, othr.collections, othr.corpora))


class TestProcedure:
    """
    A test procedure defines the concrete operations that will be done.
    """
    #Pytest throws a collection warning if the following line is removed
    __test__ = False
    def __init__(self,
                 name,
                 description=None,
                 user_info=None,
                 default=False,
                 selected=False,
                 auto_generated=False,
                 parameters=None,
                 meta_data=None,
                 schedule=None):
        self.name = name
        self.parameters = parameters if parameters else {}
        self.meta_data = meta_data if meta_data else {}
        self.description = description
        self.user_info = user_info
        self.default = default
        self.selected = selected
        self.auto_generated = auto_generated
        self.schedule = schedule if schedule else []

    def prepend_tasks(self, tasks):
        self.schedule = tasks + self.schedule

    def remove_task(self, task):
        self.schedule.remove(task)

    def __str__(self):
        return self.name

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)

    def __hash__(self):
        return hash(self.name) ^ hash(self.description) ^ hash(self.default) ^ \
               hash(self.selected) ^ hash(self.auto_generated) ^ hash(self.parameters) ^ hash(self.meta_data) ^ \
               hash(self.schedule)

    def __eq__(self, othr):
        return (isinstance(othr, type(self)) and
                (self.name, self.description, self.default, self.selected, self.auto_generated,
                 self.parameters, self.meta_data, self.schedule) ==
                (othr.name, othr.description, othr.default, othr.selected, othr.auto_generated,
                 othr.parameters, othr.meta_data, othr.schedule))

@unique
class AdminStatus(Enum):
    # We can't use True/False as they are keywords
    Yes = auto()
    No = auto()


@unique
class OperationType(Enum):
    # for the time being we are not considering this action as administrative
    Search = (3, AdminStatus.No)
    Bulk = (4, AdminStatus.No)
    RawRequest = (5, AdminStatus.No)
    WaitForBackupCreate = (7, AdminStatus.No)
    Composite = (8, AdminStatus.No)

    # administrative actions
    Sleep = (32, AdminStatus.Yes)
    DeleteBackupRepository = (33, AdminStatus.Yes)
    CreateBackupRepository = (34, AdminStatus.Yes)
    CreateBackup = (35, AdminStatus.Yes)
    RestoreBackup = (36, AdminStatus.Yes)

    def __init__(self, op_id: int, admin_status: AdminStatus):
        self.op_id = op_id
        self.admin_status = admin_status

    @property
    def admin_op(self):
        # pylint: disable=comparison-with-callable
        return self.admin_status == AdminStatus.Yes

    def to_hyphenated_string(self):
        """
        Turns enum constants into hyphenated names, e.g. ``WaitForTransform`` becomes ``wait-for-transform``.
        """
        # Pylint complains that self.name is not iterable
        # pylint: disable=not-an-iterable
        return "".join(["-" + c.lower() if c.isupper() else c for c in self.name]).lstrip("-")

    # pylint: disable=too-many-return-statements
    @classmethod
    def from_hyphenated_string(cls, v):
        if v == "search":
            return OperationType.Search
        elif v == "bulk":
            return OperationType.Bulk
        elif v == "raw-request":
            return OperationType.RawRequest
        elif v == "sleep":
            return OperationType.Sleep
        elif v == "delete-backup-repository":
            return OperationType.DeleteBackupRepository
        elif v == "create-backup-repository":
            return OperationType.CreateBackupRepository
        elif v == "create-backup":
            return OperationType.CreateBackup
        elif v == "wait-for-backup-create":
            return OperationType.WaitForBackupCreate
        elif v == "restore-backup":
            return OperationType.RestoreBackup
        elif v == "composite":
            return OperationType.Composite
        else:
            raise KeyError(f"No enum value for [{v}]")

class TaskNameFilter:
    def __init__(self, name):
        self.name = name

    def matches(self, task):
        return self.name == task.name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.name == other.name

    def __str__(self, *args, **kwargs):
        return f"filter for task name [{self.name}]"


class TaskOpTypeFilter:
    def __init__(self, op_type_name):
        self.op_type = op_type_name

    def matches(self, task):
        return self.op_type == task.operation.type

    def __hash__(self):
        return hash(self.op_type)

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.op_type == other.op_type

    def __str__(self, *args, **kwargs):
        return f"filter for operation type [{self.op_type}]"


class TaskTagFilter:
    def __init__(self, tag_name):
        self.tag_name = tag_name

    def matches(self, task):
        return self.tag_name in task.tags

    def __hash__(self):
        return hash(self.tag_name)

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.tag_name == other.tag_name

    def __str__(self, *args, **kwargs):
        return f"filter for tasks tagged [{self.tag_name}]"


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


# Schedule elements
class Parallel:
    def __init__(self, tasks, clients=None):
        self.tasks = tasks
        self._clients = clients
        self.nested = True

    @property
    def clients(self):
        if self._clients is not None:
            return self._clients
        else:
            num_clients = 0
            for task in self.tasks:
                num_clients += task.clients
            return num_clients

    def matches(self, task_filter):
        # a parallel element matches if any of its elements match
        for task in self.tasks:
            if task.matches(task_filter):
                return True
        return False

    def remove_task(self, task):
        self.tasks.remove(task)

    def __iter__(self):
        return iter(self.tasks)

    def __str__(self, *args, **kwargs):
        return "%d parallel tasks" % len(self.tasks)

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)

    def __hash__(self):
        return hash(self.tasks)

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.tasks == other.tasks


Throughput = collections.namedtuple("Throughput", ["value", "unit"])


class Task:
    THROUGHPUT_PATTERN = re.compile(r"(?P<value>(\d*\.)?\d+)\s(?P<unit>\w+/s)")
    IGNORE_RESPONSE_ERROR_LEVEL_WHITELIST = ["non-fatal"]

    def __init__(self, name, operation, tags=None, meta_data=None, warmup_iterations=None, iterations=None,
                 warmup_time_period=None, time_period=None, ramp_up_time_period=None, ramp_down_time_period=None,
                 clients=1, completes_parent=False,
                 schedule=None, params=None):
        self.name = name
        self.operation = operation
        if isinstance(tags, str):
            self.tags = [tags]
        elif tags:
            self.tags = tags
        else:
            self.tags = []
        self.meta_data = meta_data if meta_data else {}
        self.warmup_iterations = warmup_iterations
        self.iterations = iterations
        self.warmup_time_period = warmup_time_period
        self.time_period = time_period
        self.ramp_up_time_period = ramp_up_time_period
        self.ramp_down_time_period = ramp_down_time_period
        self.clients = clients
        self.completes_parent = completes_parent
        self.schedule = schedule
        self.params = params if params else {}
        self.nested = False

    def matches(self, task_filter):
        return task_filter.matches(self)

    @property
    def target_throughput(self):
        def numeric(v):
            # While booleans can be converted to a number (False -> 0, True -> 1), we don't want to allow that here
            return isinstance(v, numbers.Number) and not isinstance(v, bool)

        target_throughput = self.params.get("target-throughput")
        target_interval = self.params.get("target-interval")

        if target_interval is not None and target_throughput is not None:
            raise exceptions.InvalidSyntax(f"Task [{self}] specifies target-interval [{target_interval}] and "
                                           f"target-throughput [{target_throughput}] but only one of them is allowed.")

        value = None
        unit = "ops/s"

        if target_interval:
            if not numeric(target_interval):
                raise exceptions.InvalidSyntax(f"Target interval [{target_interval}] for task [{self}] must be numeric.")
            value = 1 / float(target_interval)
        elif target_throughput:
            if isinstance(target_throughput, str):
                matches = re.match(Task.THROUGHPUT_PATTERN, target_throughput)
                if matches:
                    value = float(matches.group("value"))
                    unit = matches.group("unit")
                else:
                    raise exceptions.InvalidSyntax(f"Task [{self}] specifies invalid target throughput [{target_throughput}].")
            elif numeric(target_throughput):
                value = float(target_throughput)
            else:
                raise exceptions.InvalidSyntax(f"Target throughput [{target_throughput}] for task [{self}] "
                                               f"must be string or numeric.")

        if value:
            return Throughput(value, unit)
        else:
            return None

    @property
    def ignore_response_error_level(self):
        ignore_response_error_level = self.params.get("ignore-response-error-level")

        if ignore_response_error_level and \
                ignore_response_error_level not in Task.IGNORE_RESPONSE_ERROR_LEVEL_WHITELIST:
            raise exceptions.InvalidSyntax(
                f"Task [{self}] specifies ignore-response-error-level to [{ignore_response_error_level}] but "
                f"the only allowed values are [{','.join(Task.IGNORE_RESPONSE_ERROR_LEVEL_WHITELIST)}].")

        return ignore_response_error_level

    def error_behavior(self, default_error_behavior):
        """
        Returns the desired behavior when encountering errors during task execution.

        :param default_error_behavior: (str) the default error behavior for the benchmark
        :return: (str) prescribing error handling when a non-fatal error occurs:
            "abort": will fail when any error gets encountered
            "continue": will continue for non fatal errors
        """

        behavior = "continue"
        if default_error_behavior == "abort":
            if self.ignore_response_error_level != "non-fatal":
                behavior = "abort"

        return behavior

    def __hash__(self):
        # Note that we do not include `params` in __hash__ and __eq__ (the other attributes suffice to uniquely define a task)
        return hash(self.name) ^ hash(self.operation) ^ hash(self.warmup_iterations) ^ hash(self.iterations) ^ \
               hash(self.warmup_time_period) ^ hash(self.time_period) ^ hash(self.ramp_up_time_period) ^ \
               hash(self.ramp_down_time_period) ^ hash(self.clients) ^ hash(self.schedule) ^ hash(self.completes_parent)

    def __eq__(self, other):
        # Note that we do not include `params` in __hash__ and __eq__ (the other attributes suffice to uniquely define a task)
        return isinstance(other, type(self)) and (self.name, self.operation, self.warmup_iterations, self.iterations,
                                                  self.warmup_time_period, self.time_period, self.ramp_up_time_period,
                                                  self.ramp_down_time_period, self.clients, self.schedule,
                                                  self.completes_parent) == (other.name, other.operation, other.warmup_iterations,
                                                                             other.iterations, other.warmup_time_period, other.time_period,
                                                                             other.ramp_up_time_period, other.ramp_down_time_period,
                                                                             other.clients, other.schedule,
                                                                             other.completes_parent)

    def __iter__(self):
        return iter([self])

    def __str__(self, *args, **kwargs):
        return self.name

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)


class Operation:
    def __init__(self, name, operation_type, meta_data=None, params=None, param_source=None):
        if params is None:
            params = {}
        self.name = name
        self.meta_data = meta_data if meta_data else {}
        self.type = operation_type
        self.params = params
        self.param_source = param_source

    @property
    def include_in_reporting(self):
        return self.params.get("include-in-reporting", True)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, type(self)) and self.name == other.name

    def __str__(self, *args, **kwargs):
        return self.name

    def __repr__(self):
        r = []
        for prop, value in vars(self).items():
            r.append("%s = [%s]" % (prop, repr(value)))
        return ", ".join(r)
