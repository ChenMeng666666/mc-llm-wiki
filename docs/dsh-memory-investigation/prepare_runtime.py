#!/usr/bin/env python3
"""Extract a declared dependency closure from the installed ASAR for local probes."""
import argparse
import hashlib
import json
from pathlib import Path
from collect import asar_files, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--asar", type=Path, default=Path("/Applications/DeepSeek Harness.app/Contents/Resources/app.asar"))
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    base, files = asar_files(args.asar)
    roots = ["@deepseek-ai/cordis", "@deepseek-ai/dsh-system-prompt", "@deepseek-ai/dsh-storage", "@deepseek-ai/dsh-storage-json", "@deepseek-ai/dsh-storage-domain", "@deepseek-ai/dsh-tools", "zod"]
    pending, seen, missing = roots[:], set(), []
    manifest = []
    with args.asar.open("rb") as stream:
        def read(name):
            entry = files[name]
            if entry.get("unpacked"):
                return Path(str(args.asar) + ".unpacked", name).read_bytes()
            stream.seek(base + int(entry["offset"]))
            return stream.read(entry["size"])
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            prefix = "dsh/node_modules/" + name + "/"
            pkg = prefix + "package.json"
            if pkg not in files:
                missing.append(name)
                continue
            spec = json.loads(read(pkg))
            # Include peer identities because their imports may be conditional.
            pending.extend(set(spec.get("dependencies", {})) | set(spec.get("peerDependencies", {})))
            for member in files:
                if not member.startswith(prefix) or "/node_modules/" in member[len(prefix):]:
                    continue
                data = read(member)
                target = args.out / "node_modules" / name / member[len(prefix):]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            manifest.append({"name": name, "version": spec.get("version"), "package_sha256": hashlib.sha256(read(pkg)).hexdigest()})
    write_json(args.out / "runtime-manifest.json", {"roots": roots, "packages": sorted(manifest, key=lambda x:x['name']), "unavailable_optional_or_peer_packages": sorted(missing)})
    print(json.dumps({"packages": len(manifest), "missing": missing, "out": str(args.out)}))


if __name__ == "__main__":
    main()
