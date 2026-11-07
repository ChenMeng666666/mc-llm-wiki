"""Source-grounded CLI fixtures; graph expectations do not use production traversal."""
import importlib.util
import json
import random
import sys
import unittest

import test_wiki as fixtures

CLI = fixtures.CLI


class EvidenceTest(unittest.TestCase):
    setUp = fixtures.WikiTest.setUp
    run_cli = fixtures.WikiTest.run_cli
    init = fixtures.WikiTest.init
    page = fixtures.WikiTest.page
    apply = fixtures.WikiTest.apply

    def register(self, name, parents=(), kind=None, **options):
        path = self.base / (name + '.txt')
        path.write_text(name, encoding='utf-8')
        args = ['add-source', path, '--title', name]
        if kind:
            args += ['--kind', kind]
        for parent in parents:
            args += ['--derived-from', parent]
        for key, value in options.items():
            args += ['--' + key, value]
        return self.run_cli(*args)['data']['id']

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def write_claim(self, sid, name, evidence=None):
        meta = json.loads(self.page(sid, page_id=name).split('---\n')[1])
        if evidence is not None:
            meta['claims'][0]['evidence'] = [{'source': s, 'locator': 'line 1'} for s in evidence]
            meta['sources'] = evidence
        self.apply([{'path': f'wiki/entities/{name}.md', 'expected_sha256': None,
                     'content': '---\n' + json.dumps(meta) + '\n---\n'}])

    def corrupt_registry(self, edit):
        path = self.root / 'state/sources.json'
        sources = json.loads(path.read_text())
        edit(sources)
        path.write_text(json.dumps(sources))

    def test_shared_roots_and_impact_are_read_only(self):
        self.init()
        a, b = self.register('original'), self.register('separate observation')
        c = self.register('summary', [a], 'derived')
        d = self.register('session retelling', [c], 'session')
        e = self.register('combined report', [a, b], 'derived')
        self.write_claim(a, 'direct')
        self.write_claim(d, 'retold')
        self.write_claim(e, 'mixed', [c, d, e])
        self.write_claim(b, 'unrelated')
        before = self.snapshot()
        claim = self.run_cli('evidence', '--claim', 'mixed-db')['data']
        self.assertEqual({r['id'] for r in claim['roots']['items']}, {a, b})
        self.assertEqual(claim['citation_count'], 3)
        self.assertEqual(claim['roots']['total'], 2)
        self.assertTrue(claim['lineage_complete'])
        self.assertEqual(claim['semantic_support'], 'not_checked')
        self.assertEqual(claim['independence'], 'not_checked')
        impact = self.run_cli('evidence', '--source', a)['data']
        affected = {x['id']: x for x in impact['affected_claims']['items']}
        self.assertEqual(set(affected), {'direct-db', 'retold-db', 'mixed-db'})
        self.assertEqual(affected['retold-db']['via']['items'], [d])
        self.assertEqual(affected['mixed-db']['other_roots']['items'], [b])
        self.assertEqual(set(impact['descendants']['items']), {c, d, e})
        # Flagging a retelling must not erase the unaffected original citation.
        branch = self.run_cli('evidence', '--source', c)['data']
        affected = {x['id']: x for x in branch['affected_claims']['items']}
        self.assertEqual(set(affected['mixed-db']['other_roots']['items']), {a, b})
        self.assertEqual(affected['retold-db']['other_roots']['items'], [])
        self.assertEqual(before, self.snapshot())

    def test_missing_ancestry_is_not_an_original_root(self):
        self.init()
        sid = self.register('legacy summary', kind='derived')
        self.write_claim(sid, 'legacy')
        data = self.run_cli('evidence', '--claim', 'legacy-db')['data']
        self.assertFalse(data['lineage_complete'])
        self.assertEqual(data['roots']['items'], [])
        self.assertEqual(data['unresolved_sources']['items'], [sid])
        warnings = self.run_cli('lint')['data']['warnings']
        self.assertIn('incomplete_lineage', {w['code'] for w in warnings})

    def test_partial_ancestry_and_empty_evidence_remain_explicit_gaps(self):
        self.init()
        a = self.register('original')
        unknown = self.register('summary without parents', kind='derived')
        mixed = self.register('mixed', [a, unknown], 'derived')
        self.write_claim(mixed, 'mixed')
        data = self.run_cli('evidence', '--claim', 'mixed-db')['data']
        self.assertEqual([r['id'] for r in data['roots']['items']], [a])
        self.assertEqual(data['unresolved_sources']['items'], [unknown])
        self.assertFalse(data['lineage_complete'])
        meta = {'id': 'unknown', 'title': 'Unknown', 'type': 'question', 'status': 'draft',
                'sources': [], 'claims': [{'id': 'unanswered', 'text': 'Unknown', 'status': 'unverified'}]}
        self.apply([{'path': 'wiki/questions/unknown.md', 'expected_sha256': None,
                     'content': '---\n' + json.dumps(meta) + '\n---\n'}])
        data = self.run_cli('evidence', '--claim', 'unanswered')['data']
        self.assertFalse(data['lineage_complete'])
        self.assertEqual(data['citation_count'], 0)

    def test_bad_pages_cannot_silently_disappear_from_impact(self):
        self.init()
        sid = self.register('original')
        self.write_claim(sid, 'atlas')
        (self.root / 'wiki/entities/broken.md').write_text('not a managed page')
        out = self.run_cli('evidence', '--source', sid, ok=False)
        self.assertEqual(out['error']['code'], 'validation_failed')

    def test_lineage_cycles_missing_parents_and_wrong_types_fail_closed(self):
        self.init()
        a = self.register('one')
        b = self.register('two', [a], 'derived')
        valid = self.snapshot()['state/sources.json']
        cases = [([a], 'source_cycle'), ([b], 'source_cycle'),
                 (['src-absent'], 'unknown_source'), ('not-a-list', 'invalid_source_lineage'),
                 ([{}], 'invalid_source_lineage'), ([b, b], 'invalid_source_lineage')]
        for parents, code in cases:
            with self.subTest(parents=parents):
                (self.root / 'state/sources.json').write_bytes(valid)
                self.corrupt_registry(lambda sources: sources[a].update(derived_from=parents))
                out = self.run_cli('lint', ok=False)
                self.assertIn(code, {e['code'] for e in out['data']['errors']})
                out = self.run_cli('evidence', '--source', a, ok=False)
                self.assertEqual(out['error']['code'], code)
                before = self.snapshot()
                self.apply([{'path': 'wiki/entities/rejected.md', 'expected_sha256': None,
                             'content': self.page(a)}], ok=False)
                self.assertEqual(before, self.snapshot())

    def test_explicit_metadata_conflicts_do_not_write(self):
        self.init()
        a = self.register('a', scope='private')
        b = self.register('b')
        for args in [('--kind', 'trace'), ('--scope', 'public'), ('--derived-from', b)]:
            with self.subTest(args=args):
                before = self.snapshot()
                out = self.run_cli('add-source', self.base / 'a.txt', '--title', 'new title',
                                   '--url', 'https://example.org/alias', *args, ok=False)
                self.assertEqual(out['error']['code'], 'source_metadata_conflict')
                self.assertEqual(before, self.snapshot())
        # Omitted metadata must not conflict with the original source's explicit metadata.
        path = self.base / 'trace.txt'
        path.write_text('trace')
        sid = self.run_cli('add-source', path, '--title', 'trace', '--kind', 'trace',
                           '--scope', 'public', '--derived-from', a)['data']['id']
        self.assertEqual(self.run_cli('add-source', path, '--title', 'alias')['data']['id'], sid)

    def test_same_metadata_and_reordered_parents_preserve_url_aliasing(self):
        self.init()
        a, b = self.register('a'), self.register('b')
        sid = self.register('report', [a, b], 'derived')
        self.run_cli('add-source', self.base / 'report.txt', '--title', 'alias', '--kind', 'derived',
                     '--derived-from', b, '--derived-from', a, '--url', 'https://example.org/report')
        entry = json.loads((self.root / 'state/sources.json').read_text())[sid]
        self.assertEqual(entry['urls'], ['https://example.org/report'])
        self.assertEqual(entry['derived_from'], [a, b])

    def test_rejected_new_parent_leaves_no_raw_or_transaction(self):
        self.init()
        sid = self.register('existing')
        source = self.base / 'bad.txt'
        source.write_text('not yet registered')
        for parents in [('missing',), (sid, sid)]:
            with self.subTest(parents=parents):
                before = self.snapshot()
                args = ['add-source', source, '--title', 'bad']
                for parent in parents:
                    args += ['--derived-from', parent]
                self.run_cli(*args, ok=False)
                self.assertEqual(before, self.snapshot())

    def test_corrupted_raw_is_reported_while_impact_remains_inspectable(self):
        self.init()
        sid = self.register('observed')
        self.write_claim(sid, 'atlas')
        entry = json.loads((self.root / 'state/sources.json').read_text())[sid]
        raw = self.root / entry['path']
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    raw.unlink()
                else:
                    raw.write_text('altered')
                before = self.snapshot()
                data = self.run_cli('evidence', '--source', sid)['data']
                self.assertFalse(data['vault_integrity_ok'])
                self.assertEqual(data['affected_claims']['items'][0]['id'], 'atlas-db')
                self.assertIn('missing_source' if missing else 'source_hash_mismatch',
                              {e['code'] for e in data['integrity_errors']['items']})
                self.assertEqual(before, self.snapshot())

    def test_unknown_ids_and_pending_batches_are_errors(self):
        self.init()
        for flag, identifier, code in [('--source', 'absent', 'unknown_source'),
                                       ('--claim', 'absent', 'unknown_claim')]:
            out = self.run_cli('evidence', flag, identifier, ok=False)
            self.assertEqual(out['error']['code'], code)
        sid = self.register('pending')
        (self.root / 'state/transactions/pending.json').write_text(json.dumps(
            {'id': 'pending', 'status': 'pending', 'reason': 'interrupted', 'changes': []}))
        out = self.run_cli('evidence', '--source', sid, ok=False)
        self.assertEqual(out['error']['code'], 'recovery_required')

    def test_limit_marks_truncation_without_changing_totals(self):
        self.init()
        a, b = self.register('a'), self.register('b')
        c = self.register('combined', [a, b], 'derived')
        self.write_claim(c, 'one')
        self.write_claim(c, 'two')
        data = self.run_cli('evidence', '--source', c, '--limit', '1')['data']
        self.assertEqual(data['affected_claims']['total'], 2)
        self.assertTrue(data['affected_claims']['truncated'])
        data = self.run_cli('evidence', '--claim', 'one-db', '--limit', '1')['data']
        self.assertEqual(data['roots']['total'], 2)
        self.assertTrue(data['roots']['truncated'])
        self.run_cli('evidence', '--source', c, '--limit', '0', ok=False)


class GraphOracleTest(unittest.TestCase):
    @staticmethod
    def graph_class():
        sys.path.insert(0, str(CLI.parent))
        spec = importlib.util.spec_from_file_location('lineage_under_test', CLI.parent / 'lineage.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.SourceGraph

    def test_generated_dags_match_fixed_point_oracle(self):
        graph_class = self.graph_class()
        for seed in range(20):
            rng = random.Random(seed)
            parents = {str(i): rng.sample([str(j) for j in range(i)], rng.randrange(min(i, 4) + 1))
                       for i in range(30)}
            sources = {sid: {'kind': 'document', 'derived_from': ps} for sid, ps in parents.items()}
            graph = graph_class(sources)
            # Fixed-point transitive closure, intentionally different from production traversal.
            closure = {sid: {sid} | set(ps) for sid, ps in parents.items()}
            while True:
                updated = {sid: reached | set().union(*(closure[x] for x in reached))
                           for sid, reached in closure.items()}
                if closure == updated:
                    break
                closure = updated
            terminals = {sid for sid, ps in parents.items() if not ps}
            for sid in parents:
                roots, unresolved = graph.roots(sid)
                self.assertEqual(roots, closure[sid] & terminals)
                self.assertEqual(unresolved, set())
                self.assertEqual(graph.descendants(sid), {x for x in parents if sid in closure[x]} - {sid})
            excluded = {str(seed % len(parents))}
            pruned = {sid: ({sid} | set(ps)) - excluded for sid, ps in parents.items() if sid not in excluded}
            while True:
                updated = {sid: reached | set().union(*(pruned[x] for x in reached))
                           for sid, reached in pruned.items()}
                if updated == pruned:
                    break
                pruned = updated
            for sid in parents:
                self.assertEqual(graph.roots(sid, exclude=excluded),
                                 (pruned.get(sid, set()) & terminals, set()))

    def test_deep_lineage_does_not_depend_on_python_recursion_limit(self):
        size = 1500
        sources = {str(i): {'kind': 'document', 'derived_from': [str(i-1)] if i else []}
                   for i in range(size)}
        graph = self.graph_class()(sources)
        self.assertEqual(graph.roots(str(size-1)), ({'0'}, set()))
        self.assertEqual(len(graph.descendants('0')), size-1)


if __name__ == '__main__':
    unittest.main()
