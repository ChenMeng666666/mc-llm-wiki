"""Declared source ancestry only; reachability never establishes truth or independence."""
from collections import deque

from store import WikiError


class SourceGraph:
    def __init__(self, sources):
        self.parents = {}
        self.children = {sid: set() for sid in sources}
        self.unresolved = set()
        for sid, source in sources.items():
            if not isinstance(source, dict):
                raise WikiError('invalid_source_lineage', f'{sid}: source must be an object')
            parents = source.get('derived_from', [])
            if (not isinstance(parents, list)
                    or not all(isinstance(p, str) and p.strip() for p in parents)
                    or len(set(parents)) != len(parents)):
                raise WikiError('invalid_source_lineage', f'{sid}: derived_from must be unique source IDs')
            self.parents[sid] = set(parents)
            for parent in parents:
                if parent not in sources:
                    raise WikiError('unknown_source', f'{sid}: unknown parent {parent}')
                self.children[parent].add(sid)
            if not parents and source.get('kind') == 'derived':
                self.unresolved.add(sid)
        # Kahn's algorithm avoids a recursion-limit failure on long-lived vaults.
        remaining = {sid: len(ps) for sid, ps in self.parents.items()}
        ready = deque(sorted(sid for sid, count in remaining.items() if not count))
        visited = 0
        while ready:
            sid = ready.popleft()
            visited += 1
            for child in sorted(self.children[sid]):
                remaining[child] -= 1
                if not remaining[child]:
                    ready.append(child)
        if visited != len(sources):
            raise WikiError('source_cycle', 'Source ancestry contains a cycle; repair declared lineage')

    def roots(self, sid, exclude=None):
        if sid not in self.parents:
            raise WikiError('unknown_source', sid)
        roots, unresolved, seen = set(), set(), set()
        excluded = exclude or set()
        pending = [sid]
        while pending:
            current = pending.pop()
            if current in seen or current in excluded:
                continue
            seen.add(current)
            if current in self.unresolved:
                unresolved.add(current)
            elif not self.parents[current]:
                roots.add(current)
            pending.extend(self.parents[current])
        return roots, unresolved

    def descendants(self, sid):
        if sid not in self.parents:
            raise WikiError('unknown_source', sid)
        seen, pending = set(), [sid]
        while pending:
            current = pending.pop()
            for child in self.children[current] - seen:
                seen.add(child)
                pending.append(child)
        return seen
