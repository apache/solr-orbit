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
"""launchr — the Solr Orbit benchmark orchestrator.

launchr drives :mod:`solrorbit` over a matrix of Solr versions x workloads x
provisioning profiles x cluster configs, enriches each resulting report with the
metadata a trend graph needs, and writes it to pluggable storage.

See ``README.md`` in this package for the user-facing documentation.
"""

__all__ = ["__version__"]

# launchr ships inside the solr-orbit distribution and shares its version.
from solrorbit.version import version as _orbit_version

__version__ = _orbit_version()
