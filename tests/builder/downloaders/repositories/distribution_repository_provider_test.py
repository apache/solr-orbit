from unittest import TestCase, mock
from unittest.mock import Mock

from osbenchmark.builder.downloaders.repositories.distribution_repository_provider import \
    DistributionRepositoryProvider
from osbenchmark.builder.cluster_config import ClusterConfigInstance


class DistributionRepositoryProviderTest(TestCase):
    def setUp(self):
        self.host = None
        self.cluster_config = ClusterConfigInstance(names=None, config_paths=None, root_path=None, variables={
            "distribution": {
                "repository": "release",
                "release": {
                    "cache": True
                }
            }
        })
        self.repository_url_provider = Mock()
        self.os_distro_repo_provider = DistributionRepositoryProvider(self.cluster_config,
                                                                                self.repository_url_provider)

    def test_get_download_url(self):
        self.os_distro_repo_provider.get_download_url(self.host)
        self.os_distro_repo_provider.repository_url_provider.render_url_for_key.assert_has_calls([
            mock.call(None, self.cluster_config.variables, "distribution.release_url")
        ])

    def test_get_file_name(self):
        file_name = self.os_distro_repo_provider.get_file_name_from_download_url(
            "https://archive.apache.org/dist/solr/solr/9.10.1/solr-9.10.1.tgz")

        self.assertEqual(file_name, "solr-9.10.1.tgz")

    def test_is_cache_enabled_true(self):
        is_cache_enabled = self.os_distro_repo_provider.is_cache_enabled()
        self.assertEqual(is_cache_enabled, True)

    def test_is_cache_enabled_false(self):
        self.cluster_config.variables["distribution"]["release"]["cache"] = False
        is_cache_enabled = self.os_distro_repo_provider.is_cache_enabled()
        self.assertEqual(is_cache_enabled, False)
