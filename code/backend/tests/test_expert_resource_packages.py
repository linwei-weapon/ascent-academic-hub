import base64
from copy import deepcopy
import io
import zipfile
import unittest

from backend.api.envelope import ApiError
from backend.expert_resources import store
from backend.expert_resources.packages import inspect_package
from backend.tests import test_expert_resources_store as fixtures
ACTOR = fixtures.ACTOR
success = fixtures.success


def encoded(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return base64.b64encode(data.getvalue()).decode()


SKILL = '---\nname: package-test\nversion: 2.0.0\ndescription: 测试技能\n---\n# Skill\n'


class PackageAndConfigurationTests(unittest.TestCase):
    setUp = fixtures.ResourceStoreTests.setUp
    tearDown = fixtures.ResourceStoreTests.tearDown
    def test_zip_inspect_and_install_update(self):
        package = inspect_package('skill.zip', encoded({'pkg/SKILL.md': SKILL, 'pkg/scripts/read.py': 'print(1)'}))
        self.assertEqual(package['skillType'], 'code')
        self.assertNotIn('package-test', [r['id'] for r in store.catalog()['skills']])
        row = store.install_package(package, ACTOR)
        self.assertEqual(row['draft']['version'], '2.0.0')
        self.assertFalse(row['readiness']['canPublish'])
        revised = deepcopy(package)
        revised['frontMatter']['version'] = '2.1.0'
        updated = store.install_package(revised, ACTOR, row['id'], row['draft']['revision'])
        self.assertEqual(updated['draft']['version'], '2.1.0')

    def test_zip_rejects_paths_metadata_duplicates(self):
        for files in ({'../SKILL.md': SKILL}, {'SKILL.md': '# empty'}, {'a/SKILL.md': SKILL, 'b/SKILL.md': SKILL}, {'目录/SKILL.md': SKILL}):
            with self.subTest(files=list(files)):
                with self.assertRaises(ApiError):
                    inspect_package('skill.zip', encoded(files))

    def test_external_config_masks_headers_and_blocks_execution(self):
        row = store.create_resource('mcps', '外部服务', ACTOR, 'external', extra_content={
            'accessType': 'native', 'serviceUrl': 'https://example.com/mcp', 'transport': 'sse',
            'requestHeaders': [{'name': 'Authorization', 'value': 'Bearer secret'}]})
        self.assertEqual(row['draft']['content']['requestHeaders'][0], {'name': 'Authorization', 'value': '', 'hasValue': True})
        row = store.save_resource('mcps', 'external', 1, row['draft']['content'], ACTOR)
        row = store.test_resource('mcps', 'external', row['draft']['revision'], {}, ACTOR, success)
        self.assertEqual(row['draft']['test']['status'], 'blocked')
        self.assertFalse(row['readiness']['canPublish'])

    def test_expert_config_and_copy(self):
        row = store.create_resource('experts', '模型专家', ACTOR, 'model-expert', extra_content={
            'executionMode': 'llm', 'modelId': 'configured-model', 'expertType': 'single',
            'maxIters': 200, 'sandboxEnabled': True, 'personaPrompt': '研究', 'welcomeMessage': '你好'})
        copied = store.copy_resource('experts', row['id'], 1, '复制模型', ACTOR, 'model-copy')
        self.assertEqual(copied['draft']['content']['expertCode'], 'model-copy')
        self.assertTrue(any('大模型' in r for r in row['readiness']['reasons']))
        changed = deepcopy(row['draft']['content'])
        changed['maxIters'] = 0
        with self.assertRaises(ApiError):
            store.save_resource('experts', row['id'], 1, changed, ACTOR)

    def test_child_references_block_delete_and_cycle(self):
        child = store.create_resource('experts', '子专家', ACTOR, 'child')
        parent = store.create_resource('experts', '编排专家', ACTOR, 'parent', extra_content={
            'expertType': 'orchestrator', 'childExpertIds': ['child']})
        self.assertFalse(store.references('experts', 'child')['canDelete'])
        with self.assertRaises(ApiError):
            store.delete_resource('experts', 'child', 1, ACTOR)
        content = deepcopy(child['draft']['content'])
        content.update({'expertType': 'orchestrator', 'childExpertIds': ['parent']})
        with self.assertRaises(ApiError):
            store.save_resource('experts', 'child', 1, content, ACTOR)
