"""Verify evidence tests reject two isolated traversal faults; never edit live code."""
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import test_evidence as cases


def main():
    original = cases.CLI
    results = []
    mutations = [
        ('drop-parent-expansion', 'pending.extend(self.parents[current])', 'pass'),
        ('drop-descendants', 'return seen\n', 'return set()\n'),
    ]
    try:
        with tempfile.TemporaryDirectory() as temporary:
            for name, before, after in mutations:
                target = Path(temporary) / name
                shutil.copytree(original.parent, target)
                path = target / 'lineage.py'
                text = path.read_text(encoding='utf-8')
                if text.count(before) != 1:
                    raise RuntimeError('Mutation point changed; review the fault injection: ' + name)
                path.write_text(text.replace(before, after), encoding='utf-8')
                cases.CLI = cases.fixtures.CLI = target / 'wiki.py'
                suite = unittest.TestSuite([
                    cases.EvidenceTest('test_shared_roots_and_impact_are_read_only'),
                    cases.GraphOracleTest('test_generated_dags_match_fixed_point_oracle'),
                ])
                log = io.StringIO()
                result = unittest.TextTestRunner(stream=log).run(suite)
                detected = len(result.failures) == 2 and not result.errors
                results.append({'mutation': name, 'tests': result.testsRun,
                                'failures': len(result.failures), 'errors': len(result.errors),
                                'detected': detected})
                if not detected:
                    raise RuntimeError(log.getvalue())
    finally:
        cases.CLI = cases.fixtures.CLI = original
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
