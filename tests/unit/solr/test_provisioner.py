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

"""Unit tests for solrorbit/builder/solr_provisioner.py"""

import socket
import unittest
from unittest.mock import MagicMock, patch

from solrorbit import exceptions
from solrorbit.builder.solr_provisioner import SolrProvisioner, SolrDockerLauncher, _assert_port_free


def _make_cluster_config(variables: dict):
    """Create a minimal cluster_config mock with the given variables dict."""
    cc = MagicMock()
    cc.variables = variables
    return cc


class TestSolrProvisionerBuildEnv(unittest.TestCase):
    """Tests for SolrProvisioner._build_env() — cluster_config → env var translation."""

    def test_no_cluster_config_returns_plain_environ(self):
        """With cluster_config=None, _build_env() returns a copy of os.environ."""
        provisioner = SolrProvisioner(cluster_config=None)
        env = provisioner._build_env()
        # Should be a dict with at least PATH in it
        self.assertIsInstance(env, dict)
        self.assertIn("PATH", env)

    def test_heap_size_sets_solr_heap(self):
        """heap_size variable should map to SOLR_HEAP env var."""
        cc = _make_cluster_config({"heap_size": "4g"})
        provisioner = SolrProvisioner(cluster_config=cc)
        env = provisioner._build_env()
        self.assertEqual("4g", env.get("SOLR_HEAP"))

    def test_gc_tune_sets_gc_tune_env(self):
        """gc_tune variable should map to GC_TUNE env var."""
        cc = _make_cluster_config({"gc_tune": "-XX:+UseG1GC -XX:+UseStringDeduplication"})
        provisioner = SolrProvisioner(cluster_config=cc)
        env = provisioner._build_env()
        self.assertEqual("-XX:+UseG1GC -XX:+UseStringDeduplication", env.get("GC_TUNE"))

    def test_solr_opts_sets_solr_opts_env(self):
        """solr_opts variable should map to SOLR_OPTS env var."""
        cc = _make_cluster_config({"solr_opts": "-XX:+PrintGCDetails"})
        provisioner = SolrProvisioner(cluster_config=cc)
        env = provisioner._build_env()
        self.assertEqual("-XX:+PrintGCDetails", env.get("SOLR_OPTS"))

    def test_multiple_variables_all_applied(self):
        """All known variables should be applied in a single call."""
        cc = _make_cluster_config({
            "heap_size": "8g",
            "gc_tune": "-XX:+UseParallelGC",
            "solr_opts": "-verbose:gc",
        })
        provisioner = SolrProvisioner(cluster_config=cc)
        env = provisioner._build_env()
        self.assertEqual("8g", env["SOLR_HEAP"])
        self.assertEqual("-XX:+UseParallelGC", env["GC_TUNE"])
        self.assertEqual("-verbose:gc", env["SOLR_OPTS"])

    def test_missing_variable_key_not_set(self):
        """Variables absent from the INI should NOT be added to the env."""
        cc = _make_cluster_config({"heap_size": "2g"})  # no gc_tune, no solr_opts
        provisioner = SolrProvisioner(cluster_config=cc)
        env = provisioner._build_env()
        self.assertNotIn("GC_TUNE", env)
        self.assertNotIn("SOLR_OPTS", env)

    def test_solr_modules_sets_solr_modules_env(self):
        """solr_modules parameter should set SOLR_MODULES env var."""
        provisioner = SolrProvisioner(solr_modules="analytics,extraction")
        env = provisioner._build_env()
        self.assertEqual("analytics,extraction", env.get("SOLR_MODULES"))

    def test_empty_solr_modules_not_in_env(self):
        """Empty solr_modules should not add SOLR_MODULES to env."""
        provisioner = SolrProvisioner(solr_modules="")
        env = provisioner._build_env()
        self.assertNotIn("SOLR_MODULES", env)


class TestSolrDockerLauncherEnvFlags(unittest.TestCase):
    """Tests for SolrDockerLauncher._cluster_config_env_flags()."""

    def test_no_cluster_config_returns_empty_list(self):
        """With cluster_config=None, no -e flags are produced."""
        launcher = SolrDockerLauncher(cluster_config=None)
        self.assertEqual([], launcher._cluster_config_env_flags())

    def test_heap_size_produces_e_flag(self):
        """heap_size should produce ['-e', 'SOLR_HEAP=4g']."""
        cc = _make_cluster_config({"heap_size": "4g"})
        launcher = SolrDockerLauncher(cluster_config=cc)
        flags = launcher._cluster_config_env_flags()
        self.assertIn("-e", flags)
        self.assertIn("SOLR_HEAP=4g", flags)

    def test_gc_tune_produces_e_flag(self):
        """gc_tune should produce ['-e', 'GC_TUNE=...']."""
        cc = _make_cluster_config({"gc_tune": "-XX:+UseG1GC"})
        launcher = SolrDockerLauncher(cluster_config=cc)
        flags = launcher._cluster_config_env_flags()
        self.assertIn("GC_TUNE=-XX:+UseG1GC", flags)

    def test_multiple_variables_produce_multiple_flags(self):
        """Each variable should produce its own -e KEY=VALUE pair."""
        cc = _make_cluster_config({"heap_size": "4g", "gc_tune": "-XX:+UseParallelGC"})
        launcher = SolrDockerLauncher(cluster_config=cc)
        flags = launcher._cluster_config_env_flags()
        self.assertIn("SOLR_HEAP=4g", flags)
        self.assertIn("GC_TUNE=-XX:+UseParallelGC", flags)
        # Each value should be preceded by '-e'
        heap_idx = flags.index("SOLR_HEAP=4g")
        self.assertEqual("-e", flags[heap_idx - 1])

    def test_absent_variable_not_in_flags(self):
        """Variables not in the INI should produce no -e flags."""
        cc = _make_cluster_config({"heap_size": "1g"})
        launcher = SolrDockerLauncher(cluster_config=cc)
        flags = launcher._cluster_config_env_flags()
        combined = " ".join(flags)
        self.assertNotIn("GC_TUNE", combined)
        self.assertNotIn("SOLR_OPTS", combined)

    def test_solr_modules_produces_e_flag(self):
        """solr_modules should produce ['-e', 'SOLR_MODULES=ltr']."""
        launcher = SolrDockerLauncher(solr_modules="ltr")
        flags = launcher._cluster_config_env_flags()
        self.assertIn("-e", flags)
        self.assertIn("SOLR_MODULES=ltr", flags)
        module_idx = flags.index("SOLR_MODULES=ltr")
        self.assertEqual("-e", flags[module_idx - 1])

    def test_empty_solr_modules_not_in_flags(self):
        """Empty solr_modules should produce no SOLR_MODULES flag."""
        launcher = SolrDockerLauncher(solr_modules="")
        flags = launcher._cluster_config_env_flags()
        self.assertNotIn("SOLR_MODULES", " ".join(flags))


class TestAssertPortFree(unittest.TestCase):
    """Tests for the _assert_port_free() helper."""

    def test_raises_when_port_in_use(self):
        """Should raise SystemSetupError when something is already listening."""
        # Open a real listening socket so the port is genuinely in use.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("localhost", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            with self.assertRaises(exceptions.SystemSetupError) as ctx:
                _assert_port_free(port)
            self.assertIn(str(port), str(ctx.exception))

    def test_no_raise_when_port_free(self):
        """Should not raise when nothing is listening on the port."""
        # Find a free port by binding briefly, then release it.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            free_port = s.getsockname()[1]
        # Port is now released — _assert_port_free should pass silently.
        _assert_port_free(free_port)  # must not raise

    def test_provisioner_start_raises_on_busy_port(self):
        """SolrProvisioner.start() should abort early if the port is busy."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("localhost", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            p = SolrProvisioner(port=port)
            with self.assertRaises(exceptions.SystemSetupError):
                p.start("/tmp/fake-solr-root")

    def test_docker_launcher_start_raises_on_busy_port(self):
        """SolrDockerLauncher.start() should abort early if the port is busy."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("localhost", 0))
            srv.listen(1)
            port = srv.getsockname()[1]
            launcher = SolrDockerLauncher(port=port)
            # docker rm -f runs first; mock it out so we don't need Docker installed.
            with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                with self.assertRaises(exceptions.SystemSetupError):
                    launcher.start(version_tag="9")


if __name__ == "__main__":
    unittest.main()
