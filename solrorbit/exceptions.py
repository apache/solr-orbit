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


class BenchmarkError(Exception):
    """
    Base class for all Solr Orbit exceptions
    """

    def __init__(self, message, cause=None):
        super().__init__(message, cause)
        self.message = message
        self.cause = cause

    def __repr__(self):
        return self.message

    def __str__(self):
        return self.message


class LaunchError(BenchmarkError):
    """
    Thrown whenever there was a problem launching the benchmark candidate
    """

class InstallError(BenchmarkError):
    """
    Thrown whenever there was a problem installing the benchmark candidate
    """


class ExecutorError(BenchmarkError):
    """
    Thrown whenever there was a problem executing a builder command
    """


class SystemSetupError(BenchmarkError):
    """
    Thrown when a user did something wrong, e.g. the metrics store is not started or required software is not installed
    """


class BenchmarkAssertionError(BenchmarkError):
    """
    Thrown when a (precondition) check has been violated.
    """


class BenchmarkTaskAssertionError(BenchmarkAssertionError):
    """
    Thrown when an assertion on a task has been violated.
    """


class ConfigError(BenchmarkError):
    pass


class DataError(BenchmarkError):
    """
    Thrown when something is wrong with the benchmark data
    """


class SupplyError(BenchmarkError):
    pass


class BuildError(BenchmarkError):
    pass


class InvalidSyntax(BenchmarkError):
    pass


class InvalidName(BenchmarkError):
    pass


class WorkloadConfigError(BenchmarkError):
    """
    Thrown when something is wrong with the workload config e.g. user supplied a workload-param
    that can't be set
    """


class NotFound(BenchmarkError):
    pass


class InvalidExtensionException(BenchmarkError):
    """
    Thrown when invalid or unsupported file extension is passed in config
    """


class ConfigurationError(BenchmarkError):
    """Exception raised for errors configuration.

    Attributes:
        message -- explanation of the error
    """


class DataStreamingError(BenchmarkError):
    """Exception raised for errors in the data streaming module.

    Attributes:
        message -- explanation of the error
    """


class MappingsError(BenchmarkError):
    """Exception raised for errors in index mappings / schema provided.

    Attributes:
        message -- explanation of the error
    """


# ---------------------------------------------------------------------------
# Abstract network / transport exceptions
#
# Backend-agnostic transport error hierarchy. All benchmark runners should
# raise these so that worker_coordinator can record uniform error metadata.
# ---------------------------------------------------------------------------

class BenchmarkTransportError(BenchmarkError):
    """HTTP/transport-level error from any benchmark target.

    Attributes:
        status_code -- integer HTTP status code, or None
        error       -- short error string / type
        info        -- additional detail (response body, exception message, …)
    """

    def __init__(self, message="", cause=None, status_code=None, error=None, info=None):
        super().__init__(message, cause)
        self.status_code = status_code
        self.error = error
        self.info = info


class BenchmarkConnectionError(BenchmarkTransportError):
    """Connection refused or target unreachable (fatal — node may be down)."""


class BenchmarkConnectionTimeout(BenchmarkTransportError):
    """Connection or request timed out."""


class BenchmarkNotFoundError(BenchmarkTransportError):
    """The requested resource was not found (HTTP 404)."""

    def __init__(self, message="", cause=None):
        super().__init__(message, cause=cause, status_code=404)
