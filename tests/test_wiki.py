"""Integration tests: real files, processes, hashes and recovery; no network."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / 'llm-wiki/scripts/wiki.py'


class WikiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'kb'

    def run_cli(self, *args, ok=True):
        proc = subprocess.run([sys.executable, str(CLI), '--root', str(self.root), *map(str, args)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode == 0, ok, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def init(self):
        self.run_cli('init')

    def source(self):
        p = self.base / 'source.txt'
        p.write_text('Atlas 正式迁移 PostgreSQL 17。', encoding='utf-8')
        return self.run_cli('add-source', p, '--title', '迁移公告', '--url', 'https://example.org/migration')['data']['id']

    def page(self, sid, text='Atlas 正式迁移 PostgreSQL 17。', page_id='atlas', **extra):
        meta = {'id': page_id, 'title': 'Atlas 数据库', 'type': 'entity', 'status': 'active',
                'sources': [sid], 'claims': [{'id': page_id + '-db', 'text': text, 'status': 'supported',
                'evidence': [{'source': sid, 'locator': 'line 1'}], 'scope': 'production',
                'valid_from': '2026-10-20', 'valid_to': None}]}
        meta.update(extra)
        return '---\n' + json.dumps(meta, ensure_ascii=False) + '\n---\n\n# Atlas 数据库\n\n' + text + '\n'

    def apply(self, changes, ok=True):
        p = self.base / 'change.json'
        p.write_text(json.dumps({'reason': 'test ingest', 'changes': changes}), encoding='utf-8')
        return self.run_cli('apply', p, ok=ok)

    def test_init_is_idempotent_and_preserves_existing_rules(self):
        self.root.mkdir()
        (self.root / 'AGENTS.md').write_text('Existing rules')
        self.init()
        (self.root / 'schema.md').write_text('User rules')
        self.init()
        self.assertEqual((self.root / 'AGENTS.md').read_text(), 'Existing rules')
        self.assertEqual((self.root / 'schema.md').read_text(), 'User rules')

    def test_content_dedup_and_immutable_raw_integrity(self):
        self.init()
        a, b = self.source(), self.source()
        self.assertEqual(a, b)
        registry = json.loads((self.root / 'state/sources.json').read_text())
        self.assertEqual(len(registry), 1)
        raw = self.root / registry[a]['path']
        self.assertEqual(raw.read_text(), 'Atlas 正式迁移 PostgreSQL 17。')
        raw.write_text('tampered')
        result = self.run_cli('lint', ok=False)
        self.assertIn('source_hash_mismatch', {e['code'] for e in result['data']['errors']})

    def test_apply_lint_search_and_optimistic_conflict(self):
        self.init()
        sid = self.source()
        body = self.page(sid)
        target = 'wiki/entities/atlas.md'
        self.apply([{'path': target, 'expected_sha256': None, 'content': body}])
        self.run_cli('lint')
        results = self.run_cli('search', '数据库')['data']['results']
        self.assertEqual(results[0]['path'], target)
        self.apply([{'path': target, 'expected_sha256': None, 'content': body + 'bad'}], ok=False)
        self.assertEqual((self.root / target).read_text(), body)
        sha = hashlib.sha256(body.encode()).hexdigest()
        self.apply([{'path': target, 'expected_sha256': sha, 'content': body + '\n更新说明\n'}])
        self.assertIn('更新说明', (self.root / target).read_text())

    def test_invalid_provenance_and_links_never_write(self):
        self.init()
        sid = self.source()
        body = self.page('src-missing') + '\n[[missing-page]]\n'
        out = self.apply([{'path': 'wiki/entities/bad.md', 'expected_sha256': None, 'content': body}], ok=False)
        self.assertEqual(out['error']['code'], 'validation_failed')
        self.assertFalse((self.root / 'wiki/entities/bad.md').exists())

    def test_path_escape_and_symlink_are_rejected(self):
        self.init()
        sid = self.source()
        for target in ['../escape.md', 'raw/evil.md', 'wiki/../../escape.md', 'wiki/entities/../escape.md']:
            with self.subTest(target=target):
                self.apply([{'path': target, 'expected_sha256': None, 'content': self.page(sid)}], ok=False)
        outside = self.base / 'outside'
        outside.mkdir()
        (self.root / 'wiki/entities/link').symlink_to(outside, target_is_directory=True)
        self.apply([{'path': 'wiki/entities/link/escape.md', 'expected_sha256': None,
                     'content': self.page(sid)}], ok=False)
        self.assertFalse((outside / 'escape.md').exists())

    def test_batch_preconditions_are_checked_before_any_write(self):
        self.init()
        sid = self.source()
        result = self.apply([{'path': 'wiki/entities/a.md', 'expected_sha256': None, 'content': self.page(sid)},
                    {'path': 'wiki/entities/b.md', 'expected_sha256': '0' * 64,
                     'content': self.page(sid, page_id='b')}], ok=False)
        self.assertEqual(result['error']['code'], 'version_conflict')
        self.assertFalse((self.root / 'wiki/entities/a.md').exists())

    def test_recovery_refuses_to_erase_later_manual_edit(self):
        self.init()
        target = self.root / 'wiki/entities/a.md'
        target.write_text('interrupted new')
        tx = {'id': 'interrupted', 'status': 'pending', 'reason': 'test', 'changes': [
            {'path': 'wiki/entities/a.md', 'before': None, 'after': 'interrupted new'}]}
        journal = self.root / 'state/transactions/interrupted.json'
        journal.write_text(json.dumps(tx))
        target.write_text('human intervened')
        self.run_cli('recover', ok=False)
        self.assertEqual(target.read_text(), 'human intervened')
        target.write_text('interrupted new')
        self.run_cli('recover')
        self.assertFalse(target.exists())
        self.assertEqual(json.loads(journal.read_text())['status'], 'rolled_back')

    def test_unknown_claim_status_and_missing_locator_are_errors(self):
        self.init()
        sid = self.source()
        body = self.page(sid).replace('"supported"', '"certain-forever"').replace('"line 1"', '""')
        self.apply([{'path': 'wiki/entities/a.md', 'expected_sha256': None, 'content': body}], ok=False)

    def test_index_rebuild_and_search_are_read_only_by_default(self):
        self.init()
        sid = self.source()
        self.apply([{'path': 'wiki/entities/atlas.md', 'expected_sha256': None, 'content': self.page(sid)}])
        self.run_cli('index')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.run_cli('search', 'PostgreSQL')
        self.run_cli('lint')
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_crlf_hash_is_the_actual_file_hash(self):
        self.init()
        sid = self.source()
        path = 'wiki/entities/atlas.md'
        original = self.page(sid).replace('\n', '\r\n').encode()
        (self.root / path).write_bytes(original)
        self.apply([{'path': path, 'expected_sha256': hashlib.sha256(original).hexdigest(),
                     'content': self.page(sid) + '\nReviewed\n'}])
        self.assertIn('Reviewed', (self.root / path).read_text())

    def test_search_refuses_a_pending_batch(self):
        self.init()
        sid = self.source()
        path = 'wiki/entities/atlas.md'
        (self.root / path).write_text(self.page(sid))
        tx = {'id': 'partial', 'status': 'pending', 'reason': 'partial batch', 'changes': [
            {'path': path, 'before': None, 'after': self.page(sid)}]}
        (self.root / 'state/transactions/partial.json').write_text(json.dumps(tx))
        result = self.run_cli('search', 'Atlas', ok=False)
        self.assertEqual(result['error']['code'], 'recovery_required')

    def test_portable_path_aliases_cannot_overwrite_in_one_batch(self):
        self.init()
        sid = self.source()
        for i, (first, second) in enumerate([('Atlas', 'atlas'), ('r\u00e9sum\u00e9', 're\u0301sume\u0301')]):
            with self.subTest(paths=(first, second)):
                self.apply([{'path': f'wiki/entities/{first}.md', 'expected_sha256': None,
                             'content': self.page(sid, page_id=f'first-{i}')},
                            {'path': f'wiki/entities/{second}.md', 'expected_sha256': None,
                             'content': self.page(sid, page_id=f'second-{i}')}], ok=False)
                self.assertFalse((self.root / f'wiki/entities/{first}.md').exists())

    def test_portable_path_alias_against_existing_page_is_rejected(self):
        self.init()
        sid = self.source()
        self.apply([{'path': 'wiki/entities/Atlas.md', 'expected_sha256': None,
                     'content': self.page(sid, page_id='first')}])
        self.apply([{'path': 'wiki/entities/atlas.md', 'expected_sha256': None,
                     'content': self.page(sid, page_id='second')}], ok=False)
        self.assertIn('"first"', (self.root / 'wiki/entities/Atlas.md').read_text())

    def test_file_parent_collision_does_not_poison_recovery(self):
        self.init()
        sid = self.source()
        self.apply([{'path': 'wiki/new.md', 'expected_sha256': None,
                     'content': self.page(sid, page_id='first')},
                    {'path': 'wiki/new.md/two.md', 'expected_sha256': None,
                     'content': self.page(sid, page_id='second')}], ok=False)
        self.assertFalse((self.root / 'wiki/new.md').exists())
        self.run_cli('recover')
        self.assertFalse(list((self.root / 'state/transactions').glob('*pending*')))
        self.run_cli('lint')

    def test_raw_disk_write_failure_leaves_no_poisoned_snapshot(self):
        self.init()
        source = self.base / 'long.txt'
        source.write_text('An acquired source longer than four bytes')
        code = '''import sys,resource,signal
sys.path.insert(0, sys.argv[1])
import wiki
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (4,4))
sys.argv = ["wiki.py", "--root", sys.argv[2], "add-source", sys.argv[3], "--title", "source"]
sys.exit(wiki.main())
'''
        proc = subprocess.run([sys.executable, '-c', code, str(CLI.parent), str(self.root), str(source)],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(list((self.root / 'raw').iterdir()), [])
        self.run_cli('add-source', source, '--title', 'source')
        self.run_cli('lint')

    def test_rebuilding_unchanged_index_is_idempotent(self):
        self.init()
        self.run_cli('index')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.run_cli('index')
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_case_alias_cannot_overwrite_generated_files(self):
        self.init()
        sid = self.source()
        for name in ('INDEX', 'LOG'):
            original_path = self.root / f'wiki/{name.lower()}.md'
            before = original_path.read_bytes()
            result = self.apply([{'path': f'wiki/{name}.md',
                                  'expected_sha256': hashlib.sha256(before).hexdigest(),
                                  'content': self.page(sid)}], ok=False)
            self.assertEqual(result['error']['code'], 'protected_path')
            self.assertEqual(original_path.read_bytes(), before)

    def test_index_groups_pages_and_uses_authored_summaries(self):
        self.init()
        sid = self.source()
        self.apply([
            {'path': 'wiki/entities/atlas.md', 'expected_sha256': None,
             'content': self.page(sid, summary='Atlas 生产数据库迁移与历史。')},
            {'path': 'wiki/concepts/transactions.md', 'expected_sha256': None,
             'content': self.page(sid, page_id='transactions', type='concept', title='数据库事务',
                                  summary='事务语义及其适用条件。')}])
        self.run_cli('index')
        content = (self.root / 'wiki/index.md').read_text()
        self.assertIn('Total pages: 2', content)
        entities = content.split('## Entities\n', 1)[1].split('## ', 1)[0]
        concepts = content.split('## Concepts\n', 1)[1].split('## ', 1)[0]
        self.assertIn('[Atlas 数据库](entities/atlas.md) — Atlas 生产数据库迁移与历史。', entities)
        self.assertIn('[数据库事务](concepts/transactions.md) — 事务语义及其适用条件。', concepts)

    def test_tags_are_registered_and_unknown_tags_never_write(self):
        self.init()
        sid = self.source()
        self.run_cli('tags', '--add', 'database', 'research')
        self.run_cli('tags', '--add', 'database')
        self.assertEqual(self.run_cli('tags')['data']['tags'], ['database', 'research'])
        out = self.apply([{'path': 'wiki/entities/bad.md', 'expected_sha256': None,
                           'content': self.page(sid, tags=['unregistered'])}], ok=False)
        self.assertIn('unknown_tag', {e['code'] for e in out['data']['errors']})
        self.assertFalse((self.root / 'wiki/entities/bad.md').exists())
        self.apply([{'path': 'wiki/entities/atlas.md', 'expected_sha256': None,
                     'content': self.page(sid, tags=['database'])}])
        self.run_cli('lint')

    def test_bad_navigation_metadata_is_rejected(self):
        self.init()
        sid = self.source()
        for i, value in enumerate(({'summary': ['not text']}, {'tags': 'database'}, {'tags': ['']},
                                   {'tags': ['x', 'x']})):
            with self.subTest(value=value):
                result = self.apply([{'path': f'wiki/entities/bad-{i}.md', 'expected_sha256': None,
                                     'content': self.page(sid, page_id=f'bad-{i}', **value)}], ok=False)
                self.assertEqual(result['error']['code'], 'validation_failed')

    def test_context_is_bounded_read_only_and_shows_latest_operation(self):
        self.init()
        sid = self.source()
        latest = self.apply([{'path': 'wiki/entities/atlas.md', 'expected_sha256': None,
                              'content': self.page(sid)}])['data']['transaction']
        self.run_cli('index')
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        out = self.run_cli('context', '--recent', '1', '--max-chars', '60')['data']
        self.assertLessEqual(len(out['schema']['content']), 60)
        self.assertLessEqual(len(out['index']['content']), 60)
        self.assertTrue(out['schema']['truncated'])
        self.assertEqual([e['id'] for e in out['recent']], [latest])
        self.assertNotIn('changes', out['recent'][0])
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_env_root_is_used_and_explicit_root_takes_precedence(self):
        env_root = self.base / 'global-wiki'
        environment = dict(os.environ, WIKI_PATH=str(env_root))
        proc = subprocess.run([sys.executable, str(CLI), 'init'], env=environment,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((env_root / 'state/sources.json').exists())
        proc = subprocess.run([sys.executable, str(CLI), '--root', str(self.root), 'init'],
                              env=environment, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['data']['root'], str(self.root.resolve()))

    def test_legacy_wiki_remains_readable_without_navigation_metadata(self):
        self.init()
        sid = self.source()
        taxonomy = self.root / 'state/taxonomy.json'
        taxonomy.unlink(missing_ok=True)
        self.apply([{'path': 'wiki/entities/atlas.md', 'expected_sha256': None,
                     'content': self.page(sid, tags=['legacy'])}])
        self.init()
        self.assertFalse(taxonomy.exists())
        self.run_cli('lint')
        self.run_cli('index')
        self.assertIn('Atlas 数据库', (self.root / 'wiki/index.md').read_text())

    def test_null_taxonomy_cannot_silently_disable_tag_governance(self):
        self.init()
        (self.root / 'state/taxonomy.json').write_text('null\n')
        result = self.run_cli('tags', ok=False)
        self.assertEqual(result['error']['code'], 'invalid_taxonomy')
        result = self.run_cli('lint', ok=False)
        self.assertEqual(result['error']['code'], 'invalid_taxonomy')

    def test_recent_order_survives_copy_and_changed_file_timestamps(self):
        self.init()
        self.run_cli('tags', '--add', 'first')
        newest = self.run_cli('tags', '--add', 'second')['data']['transaction']
        clone = self.base / 'copied-wiki'
        shutil.copytree(self.root, clone, copy_function=shutil.copyfile)
        for p in (clone / 'state/transactions').glob('*.json'):
            tx = json.loads(p.read_text())
            tx['at'] = '2026-10-22T00:00:00+00:00'
            p.write_text(json.dumps(tx))
            # Backup tools may change mtimes; they must not define logical sequence.
            stamp = 1 if tx['id'] == newest else 200
            os.utime(p, (stamp, stamp))
        proc = subprocess.run([sys.executable, str(CLI), '--root', str(clone), 'context', '--recent', '1'],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['data']['recent'][0]['id'], newest)

    def test_empty_env_root_is_rejected_without_writing_cwd(self):
        proc = subprocess.run([sys.executable, str(CLI), 'init'], cwd=self.base,
                              env=dict(os.environ, WIKI_PATH=''), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertFalse((self.base / 'state').exists())


if __name__ == '__main__':
    unittest.main()
