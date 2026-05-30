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
# pylint: disable=protected-access

import collections
import datetime
import unittest.mock as mock
from unittest import TestCase

from solrorbit import exceptions, config
from solrorbit.builder import supplier, cluster_config


class RevisionExtractorTests(TestCase):
    def test_single_revision(self):
        self.assertDictEqual({"solr": "67c2f42", "all": "67c2f42"}, supplier._extract_revisions("67c2f42"))
        self.assertDictEqual({"solr": "current", "all": "current"}, supplier._extract_revisions("current"))
        self.assertDictEqual({"solr": "@2015-01-01-01:00:00", "all": "@2015-01-01-01:00:00"}, supplier._extract_revisions("@2015-01-01-01:00:00"))

    def test_multiple_revisions(self):
        self.assertDictEqual({"solr": "67c2f42", "some-plugin": "current"}, supplier._extract_revisions("solr:67c2f42,some-plugin:current"))

    def test_invalid_revisions(self):
        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            supplier._extract_revisions("solr 67c2f42,some-plugin:current")
        self.assertEqual("Revision [solr 67c2f42] does not match expected format [name:revision].", ctx.exception.args[0])


class SourceRepositoryTests(TestCase):
    @mock.patch("solrorbit.utils.git.head_revision", autospec=True)
    @mock.patch("solrorbit.utils.git.pull", autospec=True)
    @mock.patch("solrorbit.utils.git.clone", autospec=True)
    @mock.patch("solrorbit.utils.git.is_working_copy", autospec=True)
    def test_intial_checkout_latest(self, mock_is_working_copy, mock_clone, mock_pull, mock_head_revision):
        # before cloning, it is not a working copy, afterwards it is
        mock_is_working_copy.side_effect = [False, True]
        mock_head_revision.return_value = "HEAD"

        s = supplier.SourceRepository(name="Solr", remote_url="some-github-url", src_dir="/src")
        s.fetch("latest")

        mock_is_working_copy.assert_called_with("/src")
        mock_clone.assert_called_with("/src", "some-github-url")
        mock_pull.assert_called_with("/src")
        mock_head_revision.assert_called_with("/src")

    @mock.patch("solrorbit.utils.git.head_revision", autospec=True)
    @mock.patch("solrorbit.utils.git.pull")
    @mock.patch("solrorbit.utils.git.clone")
    @mock.patch("solrorbit.utils.git.is_working_copy", autospec=True)
    def test_checkout_current(self, mock_is_working_copy, mock_clone, mock_pull, mock_head_revision):
        mock_is_working_copy.return_value = True
        mock_head_revision.return_value = "HEAD"

        s = supplier.SourceRepository(name="Solr", remote_url="some-github-url", src_dir="/src")
        s.fetch("current")

        mock_is_working_copy.assert_called_with("/src")
        self.assertEqual(0, mock_clone.call_count)
        self.assertEqual(0, mock_pull.call_count)
        mock_head_revision.assert_called_with("/src")

    @mock.patch("solrorbit.utils.git.head_revision", autospec=True)
    @mock.patch("solrorbit.utils.git.checkout")
    @mock.patch("solrorbit.utils.git.pull")
    @mock.patch("solrorbit.utils.git.clone")
    @mock.patch("solrorbit.utils.git.is_working_copy", autospec=True)
    def test_checkout_revision_for_local_only_repo(self, mock_is_working_copy, mock_clone, mock_pull, mock_checkout, mock_head_revision):
        mock_is_working_copy.return_value = True
        mock_head_revision.return_value = "HEAD"

        # local only, we dont specify a remote
        s = supplier.SourceRepository(name="Solr", remote_url=None, src_dir="/src")
        s.fetch("67c2f42")

        mock_is_working_copy.assert_called_with("/src")
        self.assertEqual(0, mock_clone.call_count)
        self.assertEqual(0, mock_pull.call_count)
        mock_checkout.assert_called_with("/src", "67c2f42")
        mock_head_revision.assert_called_with("/src")

    @mock.patch("solrorbit.utils.git.head_revision", autospec=True)
    @mock.patch("solrorbit.utils.git.pull_ts", autospec=True)
    @mock.patch("solrorbit.utils.git.is_working_copy", autospec=True)
    def test_checkout_ts(self, mock_is_working_copy, mock_pull_ts, mock_head_revision):
        mock_is_working_copy.return_value = True
        mock_head_revision.return_value = "HEAD"

        s = supplier.SourceRepository(name="Solr", remote_url="some-github-url", src_dir="/src")
        s.fetch("@2015-01-01-01:00:00")

        mock_is_working_copy.assert_called_with("/src")
        mock_pull_ts.assert_called_with("/src", "2015-01-01-01:00:00")
        mock_head_revision.assert_called_with("/src")

    @mock.patch("solrorbit.utils.git.head_revision", autospec=True)
    @mock.patch("solrorbit.utils.git.pull_revision", autospec=True)
    @mock.patch("solrorbit.utils.git.is_working_copy", autospec=True)
    def test_checkout_revision(self, mock_is_working_copy, mock_pull_revision, mock_head_revision):
        mock_is_working_copy.return_value = True
        mock_head_revision.return_value = "HEAD"

        s = supplier.SourceRepository(name="Solr", remote_url="some-github-url", src_dir="/src")
        s.fetch("67c2f42")

        mock_is_working_copy.assert_called_with("/src")
        mock_pull_revision.assert_called_with("/src", "67c2f42")
        mock_head_revision.assert_called_with("/src")

    def test_is_commit_hash(self):
        self.assertTrue(supplier.SourceRepository.is_commit_hash("67c2f42"))

    def test_is_not_commit_hash(self):
        self.assertFalse(supplier.SourceRepository.is_commit_hash("latest"))
        self.assertFalse(supplier.SourceRepository.is_commit_hash("current"))
        self.assertFalse(supplier.SourceRepository.is_commit_hash("@2015-01-01-01:00:00"))


class BuilderTests(TestCase):
    @mock.patch("solrorbit.utils.process.run_subprocess")
    @mock.patch("solrorbit.utils.jvm.resolve_path")
    def test_build_on_jdk_8(self, jvm_resolve_path, mock_run_subprocess):
        jvm_resolve_path.return_value = (8, "/opt/jdk8")
        mock_run_subprocess.return_value = False

        b = supplier.Builder(src_dir="/src", build_jdk=8, log_dir="logs")
        b.build(["./gradlew clean", "./gradlew assemble"])

        calls = [
            # Actual call
            mock.call("export JAVA_HOME=/opt/jdk8; cd /src; ./gradlew clean < /dev/null > logs/build.log 2>&1"),
            # Return value check
            mock.call("export JAVA_HOME=/opt/jdk8; cd /src; ./gradlew assemble < /dev/null > logs/build.log 2>&1"),
        ]

        mock_run_subprocess.assert_has_calls(calls)

    @mock.patch("solrorbit.utils.process.run_subprocess")
    @mock.patch("solrorbit.utils.jvm.resolve_path")
    def test_build_on_jdk_10(self, jvm_resolve_path, mock_run_subprocess):
        jvm_resolve_path.return_value = (10, "/opt/jdk10")
        mock_run_subprocess.return_value = False

        b = supplier.Builder(src_dir="/src", build_jdk=8, log_dir="logs")
        b.build(["./gradlew clean", "./gradlew assemble"])

        calls = [
            # Actual call
            mock.call("export JAVA_HOME=/opt/jdk10; cd /src; ./gradlew clean < /dev/null > logs/build.log 2>&1"),
            # Return value check
            mock.call("export JAVA_HOME=/opt/jdk10; cd /src; ./gradlew assemble < /dev/null > logs/build.log 2>&1"),
        ]

        mock_run_subprocess.assert_has_calls(calls)


class TemplateRendererTests(TestCase):
    def test_substitutes_version(self):
        renderer = supplier.TemplateRenderer(version="9.10.1")
        self.assertEqual(
            "https://archive.apache.org/dist/solr/solr/9.10.1/solr-9.10.1.tgz",
            renderer.render("https://archive.apache.org/dist/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz"),
        )

    def test_leaves_non_version_placeholders_intact(self):
        renderer = supplier.TemplateRenderer(version="9.10.1")
        self.assertEqual("solr-9.10.1 on {{OSNAME}}", renderer.render("solr-{{VERSION}} on {{OSNAME}}"))


class CachedSolrSourceSupplierTests(TestCase):
    @mock.patch("solrorbit.utils.io.ensure_dir")
    @mock.patch("shutil.copy")
    @mock.patch("solrorbit.builder.supplier.SourceSupplier")
    def test_does_not_cache_when_no_revision(self, opensearch, copy, ensure_dir):
        def add_os_artifact(binaries):
            binaries["solr"] = "/path/to/artifact.tar.gz"

        opensearch.fetch.return_value = None
        opensearch.add.side_effect = add_os_artifact

        # no version / revision provided
        renderer = supplier.TemplateRenderer(version=None)

        dist_cfg = {"release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz"}
        file_resolver = supplier.FileNameResolver(distribution_config=dist_cfg, template_renderer=renderer)
        cached_supplier = supplier.CachedSourceSupplier(distributions_root="/tmp", source_supplier=opensearch, file_resolver=file_resolver)

        cached_supplier.fetch()
        cached_supplier.prepare()

        binaries = {}

        cached_supplier.add(binaries)

        self.assertEqual(0, copy.call_count)
        self.assertFalse(cached_supplier.cached)
        self.assertIn("solr", binaries)
        self.assertEqual("/path/to/artifact.tar.gz", binaries["solr"])

    @mock.patch("os.path.exists")
    @mock.patch("solrorbit.builder.supplier.SourceSupplier")
    def test_uses_already_cached_artifact(self, opensearch, path_exists):
        # assume that the artifact is already cached
        path_exists.return_value = True
        renderer = supplier.TemplateRenderer(version="abc123")

        dist_cfg = {"release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz"}
        file_resolver = supplier.FileNameResolver(distribution_config=dist_cfg, template_renderer=renderer)
        cached_supplier = supplier.CachedSourceSupplier(distributions_root="/tmp", source_supplier=opensearch, file_resolver=file_resolver)

        cached_supplier.fetch()
        cached_supplier.prepare()

        binaries = {}

        cached_supplier.add(binaries)

        self.assertEqual(0, opensearch.fetch.call_count)
        self.assertEqual(0, opensearch.prepare.call_count)
        self.assertEqual(0, opensearch.add.call_count)
        self.assertTrue(cached_supplier.cached)
        self.assertIn("solr", binaries)
        self.assertEqual("/tmp/solr-abc123.tgz", binaries["solr"])

    @mock.patch("solrorbit.utils.io.ensure_dir")
    @mock.patch("os.path.exists")
    @mock.patch("shutil.copy")
    @mock.patch("solrorbit.builder.supplier.SourceSupplier")
    def test_caches_artifact(self, opensearch, copy, path_exists, ensure_dir):
        def add_os_artifact(binaries):
            binaries["solr"] = "/path/to/artifact.tar.gz"

        path_exists.return_value = False

        opensearch.fetch.return_value = "abc123"
        opensearch.add.side_effect = add_os_artifact

        renderer = supplier.TemplateRenderer(version="abc123")

        dist_cfg = {"release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz"}

        cached_supplier = supplier.CachedSourceSupplier(
            distributions_root="/tmp", source_supplier=opensearch, file_resolver=supplier.FileNameResolver(distribution_config=dist_cfg, template_renderer=renderer)
        )
        cached_supplier.fetch()
        cached_supplier.prepare()

        binaries = {}

        cached_supplier.add(binaries)
        # path is cached now
        path_exists.return_value = True

        self.assertEqual(1, copy.call_count, "artifact has been copied")
        self.assertEqual(1, opensearch.add.call_count, "artifact has been added by internal supplier")
        self.assertTrue(cached_supplier.cached)
        self.assertIn("solr", binaries)

        # simulate a second attempt
        cached_supplier.fetch()
        cached_supplier.prepare()

        binaries = {}
        cached_supplier.add(binaries)

        self.assertEqual(1, copy.call_count, "artifact has not been copied twice")
        # the internal supplier did not get called again as we reuse the cached artifact
        self.assertEqual(1, opensearch.add.call_count, "internal supplier is not called again")
        self.assertTrue(cached_supplier.cached)

    @mock.patch("solrorbit.utils.io.ensure_dir")
    @mock.patch("os.path.exists")
    @mock.patch("shutil.copy")
    @mock.patch("solrorbit.builder.supplier.SourceSupplier")
    def test_does_not_cache_on_copy_error(self, opensearch, copy, path_exists, ensure_dir):
        def add_os_artifact(binaries):
            binaries["solr"] = "/path/to/artifact.tar.gz"

        path_exists.return_value = False

        opensearch.fetch.return_value = "abc123"
        opensearch.add.side_effect = add_os_artifact
        copy.side_effect = OSError("no space left on device")

        renderer = supplier.TemplateRenderer(version="abc123")

        dist_cfg = {"release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz"}

        cached_supplier = supplier.CachedSourceSupplier(
            distributions_root="/tmp", source_supplier=opensearch, file_resolver=supplier.FileNameResolver(distribution_config=dist_cfg, template_renderer=renderer)
        )
        cached_supplier.fetch()
        cached_supplier.prepare()

        binaries = {}

        cached_supplier.add(binaries)

        self.assertEqual(1, copy.call_count, "artifact has been copied")
        self.assertEqual(1, opensearch.add.call_count, "artifact has been added by internal supplier")
        self.assertFalse(cached_supplier.cached)
        self.assertIn("solr", binaries)
        # still the uncached artifact
        self.assertEqual("/path/to/artifact.tar.gz", binaries["solr"])


class SolrFileNameResolverTests(TestCase):
    def setUp(self):
        super().setUp()
        renderer = supplier.TemplateRenderer(version="9.10.1")

        dist_cfg = {"release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz"}

        self.resolver = supplier.FileNameResolver(distribution_config=dist_cfg, template_renderer=renderer)

    def test_resolve(self):
        self.resolver.revision = "9.10.1"
        self.assertEqual("solr-9.10.1.tgz", self.resolver.file_name)

    def test_artifact_key(self):
        self.assertEqual("solr", self.resolver.artifact_key)

    def test_to_artifact_path(self):
        file_system_path = "/tmp/test"
        self.assertEqual(file_system_path, self.resolver.to_artifact_path(file_system_path))

    def test_to_file_system_path(self):
        artifact_path = "/tmp/test"
        self.assertEqual(artifact_path, self.resolver.to_file_system_path(artifact_path))


class PruneTests(TestCase):
    LStat = collections.namedtuple("LStat", "st_ctime")

    @mock.patch("os.path.exists")
    @mock.patch("os.listdir")
    @mock.patch("os.path.isfile")
    @mock.patch("os.lstat")
    @mock.patch("os.remove")
    def test_does_not_touch_nonexisting_directory(self, rm, lstat, isfile, listdir, exists):
        exists.return_value = False

        supplier._prune(root_path="/tmp/test", max_age_days=7)

        self.assertEqual(0, listdir.call_count, "attempted to list a non-existing directory")

    @mock.patch("os.path.exists")
    @mock.patch("os.listdir")
    @mock.patch("os.path.isfile")
    @mock.patch("os.lstat")
    @mock.patch("os.remove")
    def test_prunes_old_files(self, rm, lstat, isfile, listdir, exists):
        exists.return_value = True
        listdir.return_value = ["opensearch-1.0.0.tar.gz", "some-subdir", "opensearch-7.3.0-darwin-x86_64.tar.gz"]
        isfile.side_effect = [True, False, True]

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        ten_days_ago = now - datetime.timedelta(days=10)
        one_day_ago = now - datetime.timedelta(days=1)

        lstat.side_effect = [
            # opensearch-1.0.0.tar.gz
            PruneTests.LStat(st_ctime=int(ten_days_ago.timestamp())),
            # opensearch-1.0.1-x64.tar.gz
            PruneTests.LStat(st_ctime=int(one_day_ago.timestamp())),
        ]

        supplier._prune(root_path="/tmp/test", max_age_days=7)

        rm.assert_called_with("/tmp/test/opensearch-1.0.0.tar.gz")


class SolrSourceSupplierTests(TestCase):
    def test_no_build(self):
        cluster_config_instance = cluster_config.ClusterConfigInstance(
            "default", root_path=None, config_paths=[], variables={"clean_command": "./gradlew clean", "system.build_command": "./gradlew assemble"}
        )
        renderer = supplier.TemplateRenderer(version=None)
        opensearch = supplier.SourceSupplier(revision="abc", os_src_dir="/src", remote_url="", cluster_config=cluster_config_instance, builder=None, template_renderer=renderer)
        opensearch.prepare()
        # nothing has happened (intentionally) because there is no builder

    def test_build(self):
        cluster_config_instance = cluster_config.ClusterConfigInstance(
            "default", root_path=None, config_paths=[], variables={"clean_command": "./gradlew clean", "system.build_command": "./gradlew assemble"}
        )
        builder = mock.create_autospec(supplier.Builder)
        renderer = supplier.TemplateRenderer(version="abc")
        opensearch = supplier.SourceSupplier(revision="abc", os_src_dir="/src", remote_url="", cluster_config=cluster_config_instance, builder=builder, template_renderer=renderer)
        opensearch.prepare()

        builder.build.assert_called_once_with(["./gradlew clean", "./gradlew assemble"])

    def test_raises_error_on_missing_cluster_config_variable(self):
        cluster_config_instance = cluster_config.ClusterConfigInstance(
            "default",
            root_path=None,
            config_paths=[],
            variables={
                "clean_command": "./gradlew clean",
                # system.build_command is not defined
            },
        )
        renderer = supplier.TemplateRenderer(version="abc")
        builder = mock.create_autospec(supplier.Builder)
        opensearch = supplier.SourceSupplier(revision="abc", os_src_dir="/src", remote_url="", cluster_config=cluster_config_instance, builder=builder, template_renderer=renderer)
        with self.assertRaisesRegex(exceptions.SystemSetupError, 'ClusterConfigInstance "default" requires config key "system.build_command"'):
            opensearch.prepare()

        self.assertEqual(0, builder.build.call_count)

    @mock.patch("glob.glob", lambda p: ["opensearch.tar.gz"])
    def test_add_opensearch_binary(self):
        cluster_config_instance = cluster_config.ClusterConfigInstance(
            "default",
            root_path=None,
            config_paths=[],
            variables={
                "clean_command": "./gradlew clean",
                "system.build_command": "./gradlew assemble",
                "system.artifact_path_pattern": "distribution/archives/tar/build/distributions/*.tar.gz",
            },
        )
        renderer = supplier.TemplateRenderer(version="abc")
        opensearch = supplier.SourceSupplier(revision="abc", os_src_dir="/src", remote_url="", cluster_config=cluster_config_instance, builder=None, template_renderer=renderer)
        binaries = {}
        opensearch.add(binaries=binaries)
        self.assertEqual(binaries, {"solr": "opensearch.tar.gz"})


class CreateSupplierTests(TestCase):
    def test_derive_supply_requirements_source_build(self):
        # corresponds to --revision="abc"
        requirements = supplier._supply_requirements(sources=True, revisions={"solr": "abc"}, distribution_version=None)
        self.assertDictEqual({"solr": ("source", "abc", True)}, requirements)

    def test_derive_supply_requirements_distribution(self):
        # corresponds to --distribution-version=1.0.0
        requirements = supplier._supply_requirements(sources=False, revisions={}, distribution_version="1.0.0")
        self.assertDictEqual({"solr": ("distribution", "1.0.0", False)}, requirements)

    def test_create_suppliers_for_os_only_config(self):
        cfg = config.Config()
        cfg.add(config.Scope.application, "builder", "distribution.version", "1.0.0")
        # default value from command line
        cfg.add(config.Scope.application, "builder", "source.revision", "current")
        cfg.add(config.Scope.application, "builder", "distribution.repository", "release")
        cfg.add(
            config.Scope.application,
            "distributions",
            "release.url",
            "https://artifacts.opensearch.org/releases/bundle/opensearch/{{VERSION}}/opensearch-{{VERSION}}-{{OSNAME}}-{{ARCH}}.tar.gz",
        )
        cfg.add(config.Scope.application, "distributions", "release.cache", True)
        cfg.add(config.Scope.application, "node", "root.dir", "/opt/benchmark")

        cluster_config_instance = cluster_config.ClusterConfigInstance("default", root_path=None, config_paths=[])

        composite_supplier = supplier.create(cfg, sources=False, cluster_config=cluster_config_instance)

        self.assertEqual(1, len(composite_supplier.suppliers))
        self.assertIsInstance(composite_supplier.suppliers[0], supplier.DistributionSupplier)


class DistributionRepositoryTests(TestCase):
    def test_release_repo_config_with_default_url(self):
        renderer = supplier.TemplateRenderer(version="9.10.1")
        repo = supplier.DistributionRepository(
            name="release",
            distribution_config={"release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz", "release.cache": "true"},
            template_renderer=renderer,
        )
        self.assertEqual("https://downloads.apache.org/solr/solr/9.10.1/solr-9.10.1.tgz", repo.download_url)
        self.assertEqual("solr-9.10.1.tgz", repo.file_name)
        self.assertTrue(repo.cache)

    def test_release_repo_config_with_user_url(self):
        renderer = supplier.TemplateRenderer(version="9.10.1")
        repo = supplier.DistributionRepository(
            name="release",
            distribution_config={
                "release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz",
                # user override
                "release.url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz",
                "release.cache": "false",
            },
            template_renderer=renderer,
        )
        self.assertEqual("https://downloads.apache.org/solr/solr/9.10.1/solr-9.10.1.tgz", repo.download_url)
        self.assertEqual("solr-9.10.1.tgz", repo.file_name)
        self.assertFalse(repo.cache)

    def test_missing_url(self):
        renderer = supplier.TemplateRenderer(version="9.10.1")
        repo = supplier.DistributionRepository(
            name="miss",
            distribution_config={"release_url": "https://downloads.apache.org/solr/solr/{{VERSION}}/solr-{{VERSION}}.tgz", "release.cache": "true"},
            template_renderer=renderer,
        )
        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            # pylint: disable=pointless-statement
            # noinspection PyStatementEffect
            repo.download_url
        self.assertEqual("Neither config key [miss.url] nor [miss_url] is defined.", ctx.exception.args[0])

    def test_missing_cache(self):
        renderer = supplier.TemplateRenderer(version="1.0.0")
        repo = supplier.DistributionRepository(
            name="release",
            distribution_config={
                "jdk.unbundled.release.url": "https://artifacts.opensearch\
                .org/releases/bundle/opensearch/{{VERSION}}/opensearch-{{VERSION}}-{{OSNAME}}-{{ARCH}}.tar.gz",
                "runtime.jdk.bundled": "false",
            },
            template_renderer=renderer,
        )
        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            # pylint: disable=pointless-statement
            # noinspection PyStatementEffect
            repo.cache
        self.assertEqual("Mandatory config key [release.cache] is undefined.", ctx.exception.args[0])

    def test_invalid_cache_value(self):
        renderer = supplier.TemplateRenderer(version="1.0.0")
        repo = supplier.DistributionRepository(
            name="release",
            distribution_config={
                "jdk.unbundled.release.url": "https://artifacts.opensearch\
                .org/releases/bundle/opensearch/{{VERSION}}/opensearch-{{VERSION}}-{{OSNAME}}-{{ARCH}}.tar.gz",
                "runtime.jdk.bundled": "false",
                "release.cache": "Invalid",
            },
            template_renderer=renderer,
        )
        with self.assertRaises(exceptions.SystemSetupError) as ctx:
            # pylint: disable=pointless-statement
            # noinspection PyStatementEffect
            repo.cache
        self.assertEqual("Value [Invalid] for config key [release.cache] is not a valid boolean value.", ctx.exception.args[0])

    def test_plugin_config_with_default_url(self):
        renderer = supplier.TemplateRenderer(version="5.5.0")
        repo = supplier.DistributionRepository(
            name="release",
            distribution_config={"runtime.jdk.bundled": "false", "plugin_example_release_url": "https://artifacts.example.org/downloads/plugins/example-{{VERSION}}.zip"},
            template_renderer=renderer,
        )
        self.assertEqual("https://artifacts.example.org/downloads/plugins/example-5.5.0.zip", repo.plugin_download_url("example"))

    def test_plugin_config_with_user_url(self):
        renderer = supplier.TemplateRenderer(version="5.5.0")
        repo = supplier.DistributionRepository(
            name="release",
            distribution_config={
                "runtime.jdk.bundled": "false",
                "plugin_example_release_url": "https://artifacts.example.org/downloads/plugins/example-{{VERSION}}.zip",
                # user override
                "plugin.example.release.url": "https://mirror.example.org/downloads/plugins/example-{{VERSION}}.zip",
            },
            template_renderer=renderer,
        )
        self.assertEqual("https://mirror.example.org/downloads/plugins/example-5.5.0.zip", repo.plugin_download_url("example"))

    def test_missing_plugin_config(self):
        renderer = supplier.TemplateRenderer(version="5.5.0")
        repo = supplier.DistributionRepository(
            name="release",
            distribution_config={
                "runtime.jdk.bundled": "false",
            },
            template_renderer=renderer,
        )
        self.assertIsNone(repo.plugin_download_url("not existing"))
