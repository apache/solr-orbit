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

import datetime
import glob
import logging
import os
import re
import shutil
import urllib.error

from solrorbit import exceptions, paths, PROGRAM_NAME
from solrorbit.exceptions import BuildError, SystemSetupError
from solrorbit.utils import git, io, process, net, jvm, convert

# e.g. my-plugin:current - we cannot simply use String#split(":") as this would not work for timestamp-based revisions
REVISION_PATTERN = r"(\w.*?):(.*)"


def create(cfg, sources, cluster_config):
    logger = logging.getLogger(__name__)
    caching_enabled = cfg.opts("source", "cache", mandatory=False, default_value=True)
    revisions = _extract_revisions(cfg.opts("builder", "source.revision", mandatory=sources))
    distribution_version = cfg.opts("builder", "distribution.version", mandatory=False)
    supply_requirements = _supply_requirements(sources, revisions, distribution_version)
    build_needed = any([build for _, _, build in supply_requirements.values()])
    os_supplier_type, os_version, _ = supply_requirements["solr"]
    src_config = cfg.all_opts("source")
    suppliers = []

    template_renderer = TemplateRenderer(version=os_version)

    if build_needed:
        raw_build_jdk = cluster_config.mandatory_var("build.jdk")
        try:
            build_jdk = int(raw_build_jdk)
        except ValueError:
            raise exceptions.SystemSetupError(f"ClusterConfigInstance config key [build.jdk] is invalid: [{raw_build_jdk}] (must be int)")

        os_src_dir = os.path.join(_src_dir(cfg), _config_value(src_config, "src.subdir"))
        builder = Builder(os_src_dir, build_jdk, paths.logs())
    else:
        builder = None

    distributions_root = os.path.join(cfg.opts("node", "root.dir"), cfg.opts("source", "distribution.dir"))
    dist_cfg = {}
    dist_cfg.update(cluster_config.variables)
    dist_cfg.update(cfg.all_opts("distributions"))

    if caching_enabled:
        logger.info("Enabling source artifact caching.")
        max_age_days = int(cfg.opts("source", "cache.days", mandatory=False, default_value=7))
        if max_age_days <= 0:
            raise exceptions.SystemSetupError(f"cache.days must be a positive number but is {max_age_days}")

        source_distributions_root = os.path.join(distributions_root, "src")
        _prune(source_distributions_root, max_age_days)
    else:
        logger.info("Disabling source artifact caching.")
        source_distributions_root = None

    if os_supplier_type == "source":
        os_src_dir = os.path.join(_src_dir(cfg), _config_value(src_config, "src.subdir"))

        source_supplier = SourceSupplier(os_version,
                                                      os_src_dir,
                                                      remote_url=cfg.opts("source", "remote.repo.url"),
                                                      cluster_config=cluster_config,
                                                      builder=builder,
                                                      template_renderer=template_renderer)

        if caching_enabled:
            os_file_resolver = FileNameResolver(dist_cfg, template_renderer)
            source_supplier = CachedSourceSupplier(source_distributions_root,
                                                   source_supplier,
                                                   os_file_resolver)

        suppliers.append(source_supplier)
    else:
        repo = DistributionRepository(name=cfg.opts("builder", "distribution.repository"),
                                      distribution_config=dist_cfg,
                                      template_renderer=template_renderer)
        suppliers.append(DistributionSupplier(repo, os_version, distributions_root))

    return CompositeSupplier(suppliers)


def _required_version(version):
    if not version or version.strip() == "":
        raise exceptions.SystemSetupError("Could not determine version. Please specify the Solr distribution "
                                          "to download with the command line parameter --distribution-version.")
    else:
        return version


def _required_revision(revisions, key, name=None):
    try:
        return revisions[key]
    except KeyError:
        n = name if name is not None else key
        raise exceptions.SystemSetupError("No revision specified for %s" % n)


def _supply_requirements(sources, revisions, distribution_version):
    # * key: artifact
    # * value: ("source" | "distribution", distribution_version | revision, build = True | False)
    supply_requirements = {}

    # can only build Solr with source-related pipelines -> ignore revision in that case
    if "solr" in revisions and sources:
        supply_requirements["solr"] = ("source", _required_revision(revisions, "solr", "Solr"), True)
    else:
        # no revision given or explicitly specified that it's from a distribution -> must use a distribution
        supply_requirements["solr"] = ("distribution", _required_version(distribution_version), False)

    # Solr does not support plugin installation via the benchmark tool
    return supply_requirements


def _src_dir(cfg, mandatory=True):
    # Don't let this spread across the whole module
    try:
        return cfg.opts("node", "src.root.dir", mandatory=mandatory)
    except exceptions.ConfigError:
        raise exceptions.SystemSetupError("You cannot benchmark Solr from sources. Did you install Gradle? Please install"
                                          " all prerequisites and reconfigure with %s configure" % PROGRAM_NAME)


def _prune(root_path, max_age_days):
    """
    Removes files that are older than ``max_age_days`` from ``root_path``. Subdirectories are not traversed.

    :param root_path: A directory which should be checked.
    :param max_age_days: Files that have been created more than ``max_age_days`` ago are deleted.
    """
    logger = logging.getLogger(__name__)
    if not os.path.exists(root_path):
        logger.info("[%s] does not exist. Skipping pruning.", root_path)
        return

    for f in os.listdir(root_path):
        artifact = os.path.join(root_path, f)
        if os.path.isfile(artifact):
            max_age = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
            try:
                created_at = datetime.datetime.fromtimestamp(os.lstat(artifact).st_ctime)
                if created_at < max_age:
                    logger.info("Deleting [%s] from artifact cache (reached max age).", f)
                    os.remove(artifact)
                else:
                    logger.debug("Keeping [%s] (max age not yet reached)", f)
            except OSError:
                logger.exception("Could not check whether [%s] needs to be deleted from artifact cache.", artifact)
        else:
            logger.info("Skipping [%s] (not a file).", artifact)

class TemplateRenderer:
    def __init__(self, version):
        self.version = version

    def render(self, template):
        return template.replace("{{VERSION}}", str(self.version))


class CompositeSupplier:
    def __init__(self, suppliers):
        self.suppliers = suppliers
        self.logger = logging.getLogger(__name__)
        self.logger.info("Suppliers: %s", self.suppliers)

    def __call__(self, *args, **kwargs):
        binaries = {}
        for supplier in self.suppliers:
            supplier.fetch()
        for supplier in self.suppliers:
            supplier.prepare()
        for supplier in self.suppliers:
            supplier.add(binaries)
        return binaries


class FileNameResolver:
    def __init__(self, distribution_config, template_renderer):
        self.cfg = distribution_config
        self.template_renderer = template_renderer

    @property
    def revision(self):
        return self.template_renderer.version

    @revision.setter
    def revision(self, revision):
        self.template_renderer.version = revision

    @property
    def file_name(self):
        # Solr distributions never include a JDK, so we always use release_url
        url_key = "release_url"
        url = self.template_renderer.render(self.cfg[url_key])
        return url[url.rfind("/") + 1:]

    @property
    def artifact_key(self):
        return "solr"

    def to_artifact_path(self, file_system_path):
        return file_system_path

    def to_file_system_path(self, artifact_path):
        return artifact_path


class CachedSourceSupplier:
    def __init__(self, distributions_root, source_supplier, file_resolver):
        self.distributions_root = distributions_root
        self.source_supplier = source_supplier
        self.file_resolver = file_resolver
        self.cached_path = None
        self.logger = logging.getLogger(__name__)

    @property
    def file_name(self):
        return self.file_resolver.file_name

    @property
    def cached(self):
        return self.cached_path is not None and os.path.exists(self.cached_path)

    def fetch(self):
        # Can we already resolve the artifact without fetching the source tree at all? This is the case when a specific
        # revision (instead of a meta-revision like "current") is provided and the artifact is already cached. This is
        # also needed if an external process pushes artifacts to OSB's cache which might have been built from a
        # fork. In that case the provided commit hash would not be present in any case in the main OS repo.
        maybe_an_artifact = os.path.join(self.distributions_root, self.file_name)
        if os.path.exists(maybe_an_artifact):
            self.cached_path = maybe_an_artifact
        else:
            resolved_revision = self.source_supplier.fetch()
            if resolved_revision:
                # ensure we use the resolved revision for rendering the artifact
                self.file_resolver.revision = resolved_revision
                self.cached_path = os.path.join(self.distributions_root, self.file_name)

    def prepare(self):
        if not self.cached:
            self.source_supplier.prepare()

    def add(self, binaries):
        if self.cached:
            self.logger.info("Using cached artifact in [%s]", self.cached_path)
            binaries[self.file_resolver.artifact_key] = self.file_resolver.to_artifact_path(self.cached_path)
        else:
            self.source_supplier.add(binaries)
            original_path = self.file_resolver.to_file_system_path(binaries[self.file_resolver.artifact_key])
            # this can be None if the OpenSearch does not reside in a git repo and the user has only
            # copied all source files. In that case, we cannot resolve a revision hash and thus we cannot cache.
            if self.cached_path:
                try:
                    io.ensure_dir(io.dirname(self.cached_path))
                    shutil.copy(original_path, self.cached_path)
                    self.logger.info("Caching artifact in [%s]", self.cached_path)
                    binaries[self.file_resolver.artifact_key] = self.file_resolver.to_artifact_path(self.cached_path)
                except OSError:
                    self.logger.exception("Not caching [%s].", original_path)
            else:
                self.logger.info("Not caching [%s] (no revision info).", original_path)


class SourceSupplier:
    def __init__(self, revision, os_src_dir, remote_url, cluster_config, builder, template_renderer):
        self.revision = revision
        self.src_dir = os_src_dir
        self.remote_url = remote_url
        self.cluster_config = cluster_config
        self.builder = builder
        self.template_renderer = template_renderer

    def fetch(self):
        return SourceRepository("Solr", self.remote_url, self.src_dir).fetch(self.revision)

    def prepare(self):
        if self.builder:
            self.builder.build([
                self.template_renderer.render(self.cluster_config.mandatory_var("clean_command")),
                self.template_renderer.render(self.cluster_config.mandatory_var("system.build_command"))
            ])

    def add(self, binaries):
        binaries["solr"] = self.resolve_binary()

    def resolve_binary(self):
        try:
            path = os.path.join(self.src_dir,
                                self.template_renderer.render(self.cluster_config.mandatory_var("system.artifact_path_pattern")))
            return glob.glob(path)[0]
        except IndexError:
            raise SystemSetupError("Couldn't find a tar.gz distribution. Please run Solr Orbit with the pipeline 'from-sources'.")




class DistributionSupplier:
    def __init__(self, repo, version, distributions_root):
        self.repo = repo
        self.version = version
        self.distributions_root = distributions_root
        # will be defined in the prepare phase
        self.distribution_path = None
        self.logger = logging.getLogger(__name__)

    def fetch(self):
        io.ensure_dir(self.distributions_root)
        download_url = self.repo.download_url
        distribution_path = os.path.join(self.distributions_root, self.repo.file_name)
        self.logger.info("Resolved download URL [%s] for version [%s]", download_url, self.version)
        if not os.path.isfile(distribution_path) or not self.repo.cache:
            try:
                self.logger.info("Starting download of Solr [%s]", self.version)
                progress = net.Progress("[INFO] Downloading Solr %s" % self.version)
                net.download(download_url, distribution_path, progress_indicator=progress)
                progress.finish()
                self.logger.info("Successfully downloaded Solr [%s].", self.version)
            except urllib.error.HTTPError:
                self.logger.exception("Cannot download Solr distribution for version [%s] from [%s].", self.version, download_url)
                raise exceptions.SystemSetupError("Cannot download Solr distribution from [%s]. Please check that the specified "
                                                  "version [%s] is correct." % (download_url, self.version))
        else:
            self.logger.info("Skipping download for version [%s]. Found an existing binary at [%s].", self.version, distribution_path)

        self.distribution_path = distribution_path

    def prepare(self):
        pass

    def add(self, binaries):
        binaries["solr"] = self.distribution_path



def _config_value(src_config, key):
    try:
        return src_config[key]
    except KeyError:
        raise exceptions.SystemSetupError("Mandatory config key [%s] is undefined. Please add it in the [source] section of the "
                                          "config file." % key)


def _extract_revisions(revision):
    revisions = revision.split(",") if revision else []
    if len(revisions) == 1:
        r = revisions[0]
        if r.startswith("solr:"):
            r = r[len("solr:"):]
        # may as well be just a single plugin
        m = re.match(REVISION_PATTERN, r)
        if m:
            return {
                m.group(1): m.group(2)
            }
        else:
            return {
                "solr": r,
                # use a catch-all value
                "all": r
            }
    else:
        results = {}
        for r in revisions:
            m = re.match(REVISION_PATTERN, r)
            if m:
                results[m.group(1)] = m.group(2)
            else:
                raise exceptions.SystemSetupError("Revision [%s] does not match expected format [name:revision]." % r)
        return results


class SourceRepository:
    """
    Supplier fetches the benchmark candidate source tree from the remote repository.
    """

    def __init__(self, name, remote_url, src_dir):
        self.name = name
        self.remote_url = remote_url
        self.src_dir = src_dir
        self.logger = logging.getLogger(__name__)

    def fetch(self, revision):
        # if and only if we want to benchmark the current revision, OSB may skip repo initialization (if it is already present)
        self._try_init(may_skip_init=revision == "current")
        return self._update(revision)

    def has_remote(self):
        return self.remote_url is not None

    def _try_init(self, may_skip_init=False):
        if not git.is_working_copy(self.src_dir):
            if self.has_remote():
                self.logger.info("Downloading sources for %s from %s to %s.", self.name, self.remote_url, self.src_dir)
                git.clone(self.src_dir, self.remote_url)
            elif os.path.isdir(self.src_dir) and may_skip_init:
                self.logger.info("Skipping repository initialization for %s.", self.name)
            else:
                exceptions.SystemSetupError("A remote repository URL is mandatory for %s" % self.name)

    def _update(self, revision):
        if self.has_remote() and revision == "latest":
            self.logger.info("Fetching latest sources for %s from origin.", self.name)
            git.pull(self.src_dir)
        elif revision == "current":
            self.logger.info("Skip fetching sources for %s.", self.name)
        elif self.has_remote() and revision.startswith("@"):
            # convert timestamp annotated for OSB to something git understands -> we strip leading and trailing " and the @.
            git_ts_revision = revision[1:]
            self.logger.info("Fetching from remote and checking out revision with timestamp [%s] for %s.", git_ts_revision, self.name)
            git.pull_ts(self.src_dir, git_ts_revision)
        elif self.has_remote():  # assume a git commit hash
            self.logger.info("Fetching from remote and checking out revision [%s] for %s.", revision, self.name)
            git.pull_revision(self.src_dir, revision)
        else:
            self.logger.info("Checking out local revision [%s] for %s.", revision, self.name)
            git.checkout(self.src_dir, revision)

        if git.is_working_copy(self.src_dir):
            git_revision = git.head_revision(self.src_dir)
            self.logger.info("User-specified revision [%s] for [%s] results in git revision [%s]", revision, self.name, git_revision)
            return git_revision
        else:
            self.logger.info("Skipping git revision resolution for %s (%s is not a git repository).", self.name, self.src_dir)
            return None

    @classmethod
    def is_commit_hash(cls, revision):
        return revision != "latest" and revision != "current" and not revision.startswith("@")


class Builder:
    """
    A builder is responsible for creating an installable binary from the source files.

    It is not intended to be used directly but should be triggered by its builder.
    """

    def __init__(self, src_dir, build_jdk=None, log_dir=None):
        self.src_dir = src_dir
        self.build_jdk = build_jdk
        self._java_home = None
        self.log_dir = log_dir
        self.logger = logging.getLogger(__name__)

    @property
    def java_home(self):
        if not self._java_home:
            _, self._java_home = jvm.resolve_path(self.build_jdk)
        return self._java_home

    def build(self, commands, override_src_dir=None):
        for command in commands:
            self.run(command, override_src_dir)

    def run(self, command, override_src_dir=None):
        src_dir = self.src_dir if override_src_dir is None else override_src_dir

        io.ensure_dir(self.log_dir)
        log_file = os.path.join(self.log_dir, "build.log")

        # we capture all output to a dedicated build log file
        build_cmd = "export JAVA_HOME={}; cd {}; {} < /dev/null > {} 2>&1".format(self.java_home, src_dir, command, log_file)
        self.logger.info("Running build command [%s]", build_cmd)

        if process.run_subprocess(build_cmd):
            msg = "Executing '{}' failed. The last 20 lines in the build log file are:\n".format(command)
            msg += "=========================================================================================================\n"
            with open(log_file, "r", encoding="utf-8") as f:
                msg += "\t"
                msg += "\t".join(f.readlines()[-20:])
            msg += "=========================================================================================================\n"
            msg += "The full build log is available at [{}].".format(log_file)

            raise BuildError(msg)


class DistributionRepository:
    def __init__(self, name, distribution_config, template_renderer):
        self.name = name
        self.cfg = distribution_config
        self.template_renderer = template_renderer
        self.logger = logging.getLogger(__name__)

    @property
    def download_url(self):
        # Solr distributions never include a JDK, so we always use simple key names
        default_key = "{}_url".format(self.name)
        # benchmark.ini
        override_key = "{}.url".format(self.name)
        self.logger.info("keys: [%s] and [%s]", override_key, default_key)
        return self._url_for(override_key, default_key)

    @property
    def file_name(self):
        url = self.download_url
        return url[url.rfind("/") + 1:]

    def plugin_download_url(self, plugin_name):
        # cluster_config repo
        default_key = "plugin_{}_{}_url".format(plugin_name, self.name)
        # benchmark.ini
        override_key = "plugin.{}.{}.url".format(plugin_name, self.name)
        return self._url_for(override_key, default_key, mandatory=False)

    def _url_for(self, user_defined_key, default_key, mandatory=True):
        try:
            if user_defined_key in self.cfg:
                url_template = self.cfg[user_defined_key]
            else:
                url_template = self.cfg[default_key]
        except KeyError:
            if mandatory:
                raise exceptions.SystemSetupError("Neither config key [{}] nor [{}] is defined.".format(user_defined_key, default_key))
            else:
                return None
        return self.template_renderer.render(url_template)

    @property
    def cache(self):
        k = "{}.cache".format(self.name)
        try:
            raw_value = self.cfg[k]
        except KeyError:
            raise exceptions.SystemSetupError("Mandatory config key [%s] is undefined." % k)
        try:
            return convert.to_bool(raw_value)
        except ValueError:
            raise exceptions.SystemSetupError("Value [%s] for config key [%s] is not a valid boolean value." % (raw_value, k))
