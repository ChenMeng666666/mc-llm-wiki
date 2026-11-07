#!/usr/bin/env python3
"""Collect bounded, secret-free DSH evidence and exact shipped JS snapshots.

Does not execute extracted code, read credentials, or modify the DSH profile.
Private traces remain at their original paths; only whitelisted facts are saved.
"""
import argparse
import collections
import hashlib
import json
import pathlib
import plistlib
import re
import struct


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def asar_files(path):
    with path.open("rb") as stream:
        _, header_size, _, json_size = struct.unpack("<4I", stream.read(16))
        header = json.loads(stream.read(json_size))
    def walk(obj, prefix=""):
        for name, entry in obj.get("files", {}).items():
            name = prefix + name
            if "files" in entry:
                yield from walk(entry, name + "/")
            else:
                yield name, entry
    return 8 + header_size, dict(walk(header))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=pathlib.Path, default=pathlib.Path("/Applications/DeepSeek Harness.app"))
    parser.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home() / ".dsh")
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = args.app / "Contents/Resources/app.asar"
    info = plistlib.loads((args.app / "Contents/Info.plist").read_bytes())
    base, files = asar_files(app)
    selected = []
    # Exact installed modules relevant to lifecycle, prompt assembly and storage.
    names = ("dsh-agent", "dsh-system-prompt", "dsh-session", "dsh-storage", "dsh-storage-domain", "dsh-storage-json", "dsh-tool-subagent", "dsh-base", "dsh-web-app", "dsh-agent-loop", "dsh-agent-context", "dsh-tool", "dsh-tools", "dsh-agent-compress", "dsh-context-compress", "dsh-plugin", "dsh-plugin-manager", "dsh-cli")
    for name in names:
        prefix = "dsh/node_modules/@deepseek-ai/" + name + "/"
        selected.extend(p for p in files if p.startswith(prefix) and (p.endswith(".js") or p.endswith("package.json") or p.endswith("README.md") or p.endswith("cordis.patch.yml")))
    # Discover additional relevant package identities without interpreting absent names.
    packages = sorted({p.split("/")[3] for p in files if p.startswith("dsh/node_modules/@deepseek-ai/") and p.endswith("/package.json") and p.count("/") == 4})
    for name in packages:
        if any(s in name for s in ("compact", "compress", "context", "loop", "retry", "subagent", "request", "runtime-context")):
            prefix = "dsh/node_modules/@deepseek-ai/" + name + "/"
            selected.extend(p for p in files if p.startswith(prefix) and (p.endswith(".js") or p.endswith("package.json") or p.endswith("README.md")))
    selected.extend(["package.json", "dsh/package.json"])
    snapshots = []
    with app.open("rb") as stream:
        for member in sorted(set(selected)):
            entry = files[member]
            if entry.get("unpacked"):
                data = pathlib.Path(str(app) + ".unpacked", member).read_bytes()
            else:
                stream.seek(base + int(entry["offset"]))
                data = stream.read(entry["size"])
            target = args.out / "shipped" / member
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            snapshots.append({"member": member, "bytes": len(data), "sha256": sha(data)})
    profile = args.home / "profiles/desktop/package.json"
    profile_data = json.loads(profile.read_text()) if profile.exists() else {}
    observed = {
        "app_version": info.get("CFBundleShortVersionString"),
        "app_sha256": sha(app.read_bytes()),
        "profile": "desktop",
        "profile_package_sha256": sha(profile.read_bytes()) if profile.exists() else None,
        "profile_bundles": profile_data.get("dsh", {}).get("profile", {}).get("bundles", []),
        "profile_dependencies": profile_data.get("dependencies", {}),
        "installed_package_names": packages,
        "snapshots": snapshots,
        "session_inventory": [],
        "live_files": [],
        "privacy": "No credentials, cookie values, tool command bodies, provider request bodies or IM messages were exported. Raw traces are not copied."
    }
    monitored = [profile, args.home / "profiles/desktop/cordis.patch.yml", args.home / "profiles/desktop/cordis.yml"]
    try:
        from compression import zstd
    except ImportError:
        observed["trace_gap"] = "Python 3.14 compression.zstd is required to inspect the compressed trace."
        zstd = None
    for path in sorted((args.home / "sessions").glob("**/session.v4.jsonl.zstd")):
        raw = path.read_bytes()
        monitored.append(path)
        if zstd is None:
            continue
        rows = [json.loads(line) for line in zstd.decompress(raw).splitlines()]
        types = collections.Counter(row["type"] for row in rows)
        users, tools, retries, context_events, result_signals = [], [], [], [], []
        turns = {}
        for line, row in enumerate(rows, 1):
            data = row.get("data", {})
            if row["type"] in ("turn/start", "turn/end"):
                turn = turns.setdefault(str(data["turn"]), {})
                turn[row["type"]] = {"seq": row["seq"], "line": line, "time": row.get("time")}
            if row["type"] in ("step/start", "tool/call"):
                turn = turns.setdefault(str(data["turn"]), {})
                turn[row["type"]] = turn.get(row["type"], 0) + 1
            if row["type"] == "user/message" and data.get("source", {}).get("kind") == "user":
                # Only the two known installation requests are whitelisted.
                texts = [p.get("text", "") for p in data.get("content", []) if p.get("type") == "text"]
                allowed = [t for t in texts if t == "安装插件市场" or t == "安装这个插件 dsh plugin --profile web add github:ebony-vinyl/dsh-our-free-model"]
                users.append({"seq": row["seq"], "line": line, "time": row.get("time"), "whitelisted_text": allowed, "other_text_omitted": len(allowed) != len(texts)})
            elif row["type"] == "tool/call":
                command = data.get("arguments", {})
                if isinstance(command, str):
                    try:
                        command = json.loads(command)
                    except ValueError:
                        command = {}
                # Export no text at all; predicates allow reproducible classification.
                body = command.get("command", "") if isinstance(command, dict) else ""
                tools.append({"seq": row["seq"], "line": line, "turn": data.get("turn"), "name": data.get("name"), "profile_desktop": "--profile desktop" in body, "profile_web": "--profile web" in body, "pnpm_install": " plugin " in body and " add " in body, "github_install": "github:ebony-vinyl/dsh-our-free-model" in body, "git_https_install": "git+https://github.com/ebony-vinyl/dsh-our-free-model" in body, "local_install": "file:.packages/dsh-our-free-model" in body, "source_read": "app.asar" in str(command), "path_lookup": "which dsh" in body or "command -v dsh" in body})
            elif row["type"] == "llm/retry":
                retries.append({"seq": row["seq"], "line": line, "turn": data.get("turn"), "step": data.get("step"), "retry": data.get("retry"), "maxRetries": data.get("maxRetries"), "delayMs": data.get("delayMs")})
            elif row["type"] == "request/context":
                context_events.append({"seq": row["seq"], "line": line, "provider": data.get("provider"), "model": data.get("model"), "contextWindow": data.get("contextWindow")})
            elif row["type"] == "tool/result":
                text = "\n".join(part.get("text", "") for part in data.get("message", {}).get("content", []) if part.get("type") == "text")
                signals = []
                if "Not a directory" in text and "app.asar" in text:
                    signals.append("normal_os_fs_cannot_traverse_asar")
                if "dsh: command not found" in text:
                    signals.append("dsh_not_on_path")
                if "(no new output)" in text and "status: running" in text:
                    signals.append("background_job_no_new_output")
                if "requested cancellation of job" in text:
                    signals.append("background_job_cancel_requested")
                if "DONE 266 fails 0" in text:
                    signals.append("selected_file_fetch_completed")
                if "Done in" in text:
                    signals.append("package_manager_reported_completion")
                # Record presence of sensitive data, never its value.
                if re.search(r"dsh-auth-|Cookie:|Authorization:", text, re.I):
                    signals.append("authentication_material_present_not_exported")
                if signals:
                    result_signals.append({"seq": row["seq"], "line": line, "turn": data.get("turn"), "step": data.get("step"), "signals": signals})
        observed["session_inventory"].append({"path": str(path), "sha256": sha(raw), "bytes": len(raw), "events": len(rows), "event_types": dict(types), "user_requests": users, "tools": tools, "retries": retries, "request_context": context_events, "turns": turns, "result_signals": result_signals})
    for path in monitored:
        if path.exists():
            observed["live_files"].append({"path": str(path), "sha256": sha(path.read_bytes())})
    write_json(args.out / "observations.json", observed)
    print(json.dumps({"version": observed["app_version"], "sessions": len(observed["session_inventory"]), "selected_source_files": len(snapshots), "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
