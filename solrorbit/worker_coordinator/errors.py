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

import re


def parse_error(error_metadata):
    error = error_metadata["error"]
    status_code = None
    description = "error occured, check logs for details"
    operation = UnknownOperationError(description, None)

    if "status" in error_metadata:
        status_code = error_metadata["status"]

    if "reason" in error:
        description = error["reason"]
        matches = re.findall(r"\[([^]]*)\]", description)
        for match in matches:
            if match == "indices:admin/create":
                operation = IndexOperationError(description, "index-create", status_code)
            elif match == "indices:admin/delete":
                operation = IndexOperationError(description, "index-delete", status_code)
            elif match == "indices:data/write/bulk":
                operation = IndexOperationError(description, "index-append", status_code)
            elif match == "indices:admin/refresh":
                operation = IndexOperationError(description, "refresh-after-index", status_code)
            elif match == "indices:admin/forcemerge":
                operation = IndexOperationError(description, "force-merge", status_code)
            elif match == "indices:data/read/search":
                operation = SearchOperationError(description, "search", status_code)

    return operation


class BenchmarkOperationError:
    def __init__(self, description, operation=None, status_code=None):
        self.description = description
        self.operation = operation
        self.status_code = status_code


class UnknownOperationError(BenchmarkOperationError):
    def get_error_message(self):
        return self.description


class IndexOperationError(BenchmarkOperationError):
    def get_error_message(self):
        if self.status_code == 403:
            return f"permission denied for {self.operation}. check logs for details"
        elif self.status_code == 500:
            return f"internal server error for {self.operation}. check logs for details"
        else:
            return self.description


class SearchOperationError(BenchmarkOperationError):
    def get_error_message(self):
        if self.status_code == 403:
            return f"permission denied for {self.operation}. check logs for details"
        elif self.status_code == 500:
            return f"internal server error for {self.operation} index. check logs for details"
        else:
            return self.description
