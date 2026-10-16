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
"""Solr install methods.

``docker`` runs one container on this machine, ``docker-ssh`` runs a container
per remote node with an external ZooKeeper, and ``none`` benchmarks a cluster
launchr does not own.
"""

from solrorbit.tools.launchr.errors import ConfigError
from solrorbit.tools.launchr.install.base import SolrInstallMethod
from solrorbit.tools.launchr.install.docker import DockerInstall
from solrorbit.tools.launchr.install.docker_ssh import DockerSshInstall
from solrorbit.tools.launchr.install.none import NoOpInstall

REGISTRY: dict[str, type] = {
    DockerInstall.name: DockerInstall,
    DockerSshInstall.name: DockerSshInstall,
    NoOpInstall.name: NoOpInstall,
}

__all__ = [
    "SolrInstallMethod",
    "DockerInstall",
    "DockerSshInstall",
    "NoOpInstall",
    "REGISTRY",
    "get_install_method",
    "available",
]


def available() -> list[str]:
    """Names of every registered install method."""
    return sorted(REGISTRY)


def get_install_method(name: str, **kwargs) -> SolrInstallMethod:
    """Instantiate an install method by name.

    Unknown keyword arguments are dropped, so a method that does not care about
    the image registry does not have to accept it.
    """
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ConfigError(
            f"Unknown install method {name!r}. Available: {', '.join(available())}"
        ) from None
    import inspect

    accepted = inspect.signature(cls.__init__).parameters
    usable = {k: v for k, v in kwargs.items() if k in accepted}
    return cls(**usable)
