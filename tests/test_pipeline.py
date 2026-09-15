import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills/training-data-qa'
spec = importlib.util.spec_from_file_location('qa', ROOT / 'scripts/dataset_qa.py')
qa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qa)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inp = Path(self.tmp.name) / 'input'
        self.out = Path(self.tmp.name) / 'out'
        shutil.copytree(ROOT / 'assets/example', self.inp)
        self.assertEqual(qa.build(self.inp, self.out)['status'], 'machine_pass')

    def rows(self):
        return qa.lines(self.out / 'dataset.jsonl')

    def check_rows(self, rows):
        qa.jsonl(self.out / 'dataset.jsonl', rows)
        report = qa.check(self.inp, self.out)
        return report, {x['code'] for x in qa.lines(self.out / 'issues.jsonl')}

    def approve_fixture(self):
        # Test-only simulated approvals; never used for real dataset delivery.
        reviews = qa.read(self.out / 'reviews.json')
        for value in reviews.values():
            value.update(decision='approve', reviewer='TEST_FIXTURE', notes='simulated test')
        qa.write(self.out / 'reviews.json', reviews)

    def test_examples_and_release_hashes(self):
        self.assertEqual(len(self.rows()), 16)
        qa.review(self.inp, self.out)
        self.approve_fixture()
        result = qa.seal(self.inp, self.out, 'test-v1')
        dest = Path(result['path'])
        manifest = qa.read(dest / 'manifest.json')
        for name, expected in manifest['files'].items():
            self.assertEqual(qa.digest((dest / name).read_bytes()), expected)
        with self.assertRaises(FileExistsError):
            qa.seal(self.inp, self.out, 'test-v1')

    def test_no_expert_approval_blocks_seal(self):
        qa.review(self.inp, self.out)
        with self.assertRaisesRegex(ValueError, 'approval missing'):
            qa.seal(self.inp, self.out, 'v1')

    def test_cross_split_source_leak(self):
        rows = self.rows()
        rows[0]['split'] = next(s for s in qa.SPLITS if s != rows[0]['split'])
        _, codes = self.check_rows(rows)
        self.assertIn('CROSS_SPLIT_LEAKAGE', codes)
        self.assertIn('SPLIT_ASSIGNMENT', codes)

    def test_bad_json_and_schema(self):
        with (self.out / 'dataset.jsonl').open('a') as f:
            f.write('{broken\n{}\n')
        report = qa.check(self.inp, self.out)
        self.assertEqual(report['status'], 'blocked')
        codes = {x['code'] for x in qa.lines(self.out / 'issues.jsonl')}
        self.assertTrue({'INVALID_JSON', 'SCHEMA'} <= codes)

    def test_duplicate_and_unsupported_fact(self):
        rows = self.rows()
        rows.append(dict(rows[0], id='duplicate'))
        rows[1]['answer'] = '没有来源依据的答案'
        _, codes = self.check_rows(rows)
        self.assertTrue({'EXACT_DUPLICATE', 'EVIDENCE'} <= codes)

    def test_heldout_augmentation_blocked(self):
        rows = self.rows()
        parent = next(x for x in rows if x['split'] == 'test')
        rows.append(dict(parent, id='synthetic', kind='augmented', parent_id=parent['id'], prompt='请仔细阅读。' + parent['prompt'], generator=dict(model_version='test', prompt_hash='a'*64, seed=1, transform='paraphrase')))
        _, codes = self.check_rows(rows)
        self.assertIn('LINEAGE_LEAKAGE', codes)

    def test_changed_inputs_invalidate_reviews(self):
        qa.review(self.inp, self.out)
        self.approve_fixture()
        rules = qa.read(self.inp / 'rules.json')
        rules['version'] = 'v2'
        qa.write(self.inp / 'rules.json', rules)
        with self.assertRaisesRegex(ValueError, 'stale'):
            qa.seal(self.inp, self.out, 'v1')

    def test_changed_tasks_cannot_reduce_review(self):
        qa.review(self.inp, self.out)
        self.approve_fixture()
        qa.jsonl(self.out / 'annotation_tasks.jsonl', [])
        with self.assertRaisesRegex(ValueError, 'stale'):
            qa.seal(self.inp, self.out, 'v1')

    def test_incomplete_near_scan_blocked(self):
        template = qa.read(self.inp / 'template.json')
        template['near_duplicate_limit'] = 1
        qa.write(self.inp / 'template.json', template)
        report = qa.check(self.inp, self.out)
        self.assertEqual(report['status'], 'blocked')
        self.assertFalse(report['near_scan_complete'])

    def test_distribution_and_governance(self):
        rows = self.rows()
        rows = [x for x in rows if x['label'] != '资格']
        _, codes = self.check_rows(rows)
        self.assertIn('DISTRIBUTION', codes)
        sources = qa.lines(self.inp / 'sources.jsonl')
        sources[0]['licensed'] = False
        qa.jsonl(self.inp / 'sources.jsonl', sources)
        qa.check(self.inp, self.out)
        self.assertIn('GOVERNANCE', {x['code'] for x in qa.lines(self.out / 'issues.jsonl')})


if __name__ == '__main__':
    unittest.main()
