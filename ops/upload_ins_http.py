#!/usr/bin/env python3
"""Bounded-memory HTTP client for the verified INS bag; resumes an existing session."""
import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def call(url, method="GET", body=None, headers=None):
    if method == "PUT":
        command = ["curl", "--noproxy", "*", "--fail-with-body", "--silent", "--show-error",
                   "--request", "PUT", url, "--data-binary", "@-"]
        for name, value in (headers or {}).items():
            command.extend(["--header", f"{name}: {value}"])
        completed = subprocess.run(command, input=body, capture_output=True)
        if completed.returncode:
            raise urllib.error.URLError(completed.stderr.decode(errors="replace")[-300:])
        return json.loads(completed.stdout)
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bag", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api")
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    profile = call(args.api + "/uploads/profiles")[0]
    if args.bag.stat().st_size != profile["size_bytes"]:
        raise SystemExit("Bag size does not match controlled profile")
    args.state.parent.mkdir(parents=True, exist_ok=True)
    if args.state.exists():
        upload_id = json.loads(args.state.read_text())["upload_id"]
        state = call(args.api + "/uploads/" + upload_id)
    else:
        state = call(args.api + "/uploads", "POST", json.dumps({
            "filename": args.bag.name, "size_bytes": args.bag.stat().st_size,
            "profile_id": profile["id"],
        }).encode(), {"Content-Type": "application/json"})
        upload_id = state["upload_id"]
        args.state.write_text(json.dumps({"upload_id": upload_id, "source": str(args.bag)}) + "\n")
    with args.bag.open("rb") as source:
        while state["offset"] < profile["size_bytes"]:
            offset = state["offset"]
            source.seek(offset)
            data = source.read(min(state["max_chunk_bytes"], profile["size_bytes"] - offset))
            digest = hashlib.sha256(data).hexdigest()
            for attempt in range(3):
                try:
                    call(args.api + "/uploads/" + upload_id + "/chunk", "PUT", data,
                         {"X-Offset": str(offset), "X-Chunk-Sha256": digest,
                          "Content-Type": "application/octet-stream"})
                    break
                except (urllib.error.URLError, TimeoutError):
                    state = call(args.api + "/uploads/" + upload_id)
                    if state["offset"] > offset:
                        break
                    if attempt == 2:
                        raise
                    time.sleep(2)
            state = call(args.api + "/uploads/" + upload_id)
            print(f"{state['offset']}/{profile['size_bytes']} ({100 * state['offset'] / profile['size_bytes']:.2f}%)", flush=True)
    result = call(args.api + "/uploads/" + upload_id + "/finalize", "POST", b"")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
