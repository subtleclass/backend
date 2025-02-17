import json
import os
import unittest
from configparser import ConfigParser

from opensearchpy import OpenSearch

from api.cache.api_cache import cache
from api.views.yang_search.grep_search import GrepSearch
from api.yangcatalog_api import app  # noqa: F401
from opensearch_indexing.models.opensearch_indices import OpenSearchIndices
from opensearch_indexing.opensearch_manager import OpenSearchManager
from utility.create_config import create_config


class TestGrepSearchClass(unittest.TestCase):
    resources_path: str
    opensearch: OpenSearch
    opensearch_manager: OpenSearchManager
    opensearch_index: OpenSearchIndices

    @classmethod
    def setUpClass(cls):
        cls.config = create_config()
        cls.resources_path = os.path.join(os.environ['BACKEND'], 'tests', 'resources')
        cls._configure_es(cls.config)

    @classmethod
    def _configure_es(cls, config: ConfigParser):
        opensearch_host_config = {
            'host': config.get('DB-Section', 'opensearch-host', fallback='localhost'),
            'port': config.get('DB-Section', 'opensearch-port', fallback='9200'),
        }
        cls.opensearch = OpenSearch(hosts=[opensearch_host_config])
        cls.opensearch_manager = OpenSearchManager(cls.opensearch)
        cls.opensearch_index = OpenSearchIndices.TEST_SEARCH
        with open(os.path.join(cls.resources_path, 'test_search/search_test_data.json'), 'r') as reader:
            es_test_data = json.load(reader)
        index_json_name = f'initialize_{cls.opensearch_index.value}_index.json'
        index_json_path = os.path.join(os.environ['BACKEND'], 'opensearch_indexing', 'json', index_json_name)
        with open(index_json_path, encoding='utf-8') as reader:
            index_config = json.load(reader)
        cls.opensearch.indices.create(index=cls.opensearch_index.value, body=index_config, ignore=400)
        all_modules = es_test_data['all_modules']
        for module in all_modules:
            cls.opensearch.index(index=cls.opensearch_index.value, body=module, refresh='true')

    @classmethod
    def tearDownClass(cls):
        cls.opensearch.indices.delete(index=cls.opensearch_index.value, ignore=[400, 404])

    def setUp(self):
        with app.app_context():
            cache.clear()
        self.grep_search = GrepSearch(
            config=self.config,
            opensearch_manager=self.opensearch_manager,
            modules_es_index=self.opensearch_index,
        )

    def tearDown(self):
        with app.app_context():
            cache.clear()

    def test_simple_grep_search(self):
        organizations = []
        simple_search = 'typedef minutes64 {\n.*type uint64;'
        simple_search_result = self.grep_search.search(organizations, simple_search)
        self.assertNotEqual(simple_search_result, [])

    def test_complicated_grep_search(self):
        organizations = []
        complicated_search = (
            'identity restconf {\n.*base protocol;|typedef email-address {\n.*type string {|'
            'typedef email-address {\n.*type string {\n.*pattern "'
        )
        complicated_search_result = self.grep_search.search(organizations, complicated_search)
        self.assertNotEqual(complicated_search_result, [])
        modules_from_complicated_search_result = [
            f'{module_data["module-name"]}@{module_data["revision"]}' for module_data in complicated_search_result
        ]
        self.assertIn('yang-catalog@2017-09-26', modules_from_complicated_search_result)
        self.assertIn('yang-catalog@2018-04-03', modules_from_complicated_search_result)

    def test_organization_based_grep_search(self):
        organizations = ['ietf']
        search = 'typedef dscp {\n.*type uint8 {\n.*range "0..63";\n.*}'
        search_result = self.grep_search.search(organizations, search)
        self.assertNotEqual(search_result, [])
        self.assertEqual(len(search_result), 1)
        modules_from_search_result = [
            f'{module_data["module-name"]}@{module_data["revision"]}' for module_data in search_result
        ]
        self.assertIn('ietf-inet-types@2020-07-06', modules_from_search_result)

    def test_empty_grep_search(self):
        organizations = []
        search = 'non_existent_search_term1|non_existent_search_term2|non_existent_search_term3'
        search_result = self.grep_search.search(organizations, search)
        self.assertEqual(search_result, [])

    def test_simple_inverted_grep_search(self):
        organizations = ['cisco']
        simple_search = 'organization'
        simple_search_result = self.grep_search.search(organizations, simple_search, inverted_search=True)
        self.assertEqual(simple_search_result, [])

    def test_complicated_inverted_grep_search(self):
        organizations = ['ietf']
        complicated_search = (
            'identity restconf {\n.*base protocol;|typedef email-address {\n.*type string {|'
            'typedef email-address {\n.*type string {\n.*pattern "'
        )
        complicated_search_result = self.grep_search.search(organizations, complicated_search, inverted_search=True)
        self.assertNotEqual(complicated_search_result, [])
        modules_from_complicated_search_result = [
            f'{module_data["module-name"]}@{module_data["revision"]}' for module_data in complicated_search_result
        ]
        self.assertNotIn('yang-catalog@2017-09-26', modules_from_complicated_search_result)
        self.assertNotIn('yang-catalog@2018-04-03', modules_from_complicated_search_result)
        self.assertIn('semver-test@2020-03-01', modules_from_complicated_search_result)
        self.assertIn('sdo-module@2022-08-05', modules_from_complicated_search_result)

    def test_empty_inverted_grep_search(self):
        organizations = []
        search = 'namespace'
        search_result = self.grep_search.search(organizations, search, inverted_search=True)
        self.assertEqual(search_result, [])

    def test_inverted_search_returns_all_files(self):
        organizations = []
        search = 'non_existing_string'
        search_result = self.grep_search._get_matching_module_names(
            search,
            inverted_search=True,
            case_sensitive=False,
            organizations=organizations,
        )
        self.assertNotEqual(search_result, [])
        self.assertEqual(sorted(search_result), sorted(self.grep_search._get_all_modules_with_filename_extension()))

    def test_empty_case_sensitive_grep_search(self):
        organizations = []
        search = 'Namespace ".*";'
        search_result = self.grep_search.search(organizations, search, case_sensitive=True)
        self.assertEqual(search_result, [])

    def test_get_cached_results(self):
        organizations = []
        search = 'organization'
        search_result = self.grep_search._get_matching_module_names(
            search,
            inverted_search=False,
            case_sensitive=False,
            organizations=organizations,
        )
        self.assertNotEqual(search_result, [])
        cache_key = f'{search}{False}{False}{str(sorted(organizations)) if organizations else ""}'
        self.assertEqual(sorted(search_result), sorted(self.grep_search._search_in_cache(cache_key)))

    def test_finishing_cursor(self):
        organizations = []
        search = 'organization'
        self.grep_search.search(organizations, search)
        finishing_cursor_valid_value = min(
            self.grep_search.results_per_page,
            len(self.grep_search._get_all_modules_with_filename_extension()),
        )
        self.assertEqual(self.grep_search.finishing_cursor, finishing_cursor_valid_value)
