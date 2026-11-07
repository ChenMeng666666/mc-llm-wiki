#!/usr/bin/env python3
"""Fetch only commit-pinned public code; never install packages or send local data."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess

GUNTUR = "cc17aba9868122981e496380345e288d27bb8ac2"
HINDSIGHT = "047350acf96167534409e5d87a07b8b2ee1469f9"
FILES = [
    (f"https://raw.githubusercontent.com/guntur-d/dsh-memory/{GUNTUR}/src/index.ts", "guntur-d/src/index.ts", "9906a97dd1b4e603a74811ffc779f5a25782e487fa60a67e25bf85c4954f38e7"),
    (f"https://raw.githubusercontent.com/guntur-d/dsh-memory/{GUNTUR}/src/domain.ts", "guntur-d/src/domain.ts", "0edde35c2357a89091dc50a7480536439ac5a64d03b1a1839a59fb42b570f21e"),
    (f"https://raw.githubusercontent.com/guntur-d/dsh-memory/{GUNTUR}/src/types.ts", "guntur-d/src/types.ts", "471364de44d2c23ac87ae2cda03abbcff8fd2845fc6b3b372f8e5e0f9514bba6"),
    (f"https://raw.githubusercontent.com/guntur-d/dsh-memory/{GUNTUR}/package.json", "guntur-d/package.json", "b9b330128ecbaf96449806c1c6e487ebbf815b9eca95fd115830c54e854383fa"),
    (f"https://raw.githubusercontent.com/vectorize-io/hindsight/{HINDSIGHT}/hindsight-integrations/coding-agents/src/dsh.ts", "hindsight-dsh.ts", "f7ba2b6a18269cc7045b3ca8483d58530ff77ff0da8fec5fd93b5d971ec07715"),
    (f"https://raw.githubusercontent.com/vectorize-io/hindsight/{HINDSIGHT}/hindsight-integrations/coding-agents/package.json", "hindsight-coding-package.json", "499249af174088cddc6b19c055319e6943aea210c8912d92a7bf8e0e0e6b2f59"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    def fetch(item):
        url, name, expected = item
        path = args.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        run = subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error", "--max-time", "25", url, "-o", str(path)], capture_output=True, text=True)
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if run.returncode == 0 else None
        return {"url": url, "path": name, "curl_exit": run.returncode, "sha256": actual, "expected_sha256": expected, "verified": actual == expected}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, FILES))
    (args.out / "public-lock.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"verified": sum(r["verified"] for r in results), "total": len(results), "out": str(args.out)}))
    if not all(r["verified"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
