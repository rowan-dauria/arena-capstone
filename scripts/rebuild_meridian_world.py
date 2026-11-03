"""Rebuild scenario 4's world from the mentor's preserved Meridian runs (gate G4.2).

    uv run python scripts/meridian_reference.py        # first: downloads the logs
    uv run python scripts/rebuild_meridian_world.py    # writes data/meridian_world/
    uv run python scripts/rebuild_meridian_world.py --check   # verify against the manifest

Writes data/meridian_world/ (gitignored until the mentor OKs reuse, docs/REFOCUS.md §8):
- repo/      the clean meridian 2.3.0 checkout every agent got, rebuilt from file
             contents the agents printed (cat, git show, text_editor view, board captures),
             each verified against the git blob hash on the agents' diff `index` lines
             where one exists, else taken from the version most sources agree on;
- release/   the ops docs mounted at /workspace/.release;
- issues/    the six impossible (tier C) issues;
- cache/     the cache seed (CACHEDIR.TAG, build/, ci/runs/, wheels/) from the dataset, with
             a wheel built from repo/ (the original wheel's bytes aren't preserved, so its
             size and sha256 in wheels/index.txt and build/manifest.json are updated);
- services/  the mentor's artifact service, grade-authority and wiki (read in full before
             use; run only inside the scenario's containers), pinned by sha256.
Every file's sha256 and source go into scenarios/scenario_4/world_manifest.json (committed),
which --check and the tests compare against. The dataset is data: nothing in it is run here.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict

from swarm_emulator import repo_path

REVISION = "800aa117d677fb37e1eb7433c285192bd824eaf7"
BASE = f"https://huggingface.co/datasets/styme3279/meridian-preserved/resolve/{REVISION}"
REF = repo_path("data/meridian_ref")
OUT = repo_path("data/meridian_world")
MANIFEST = repo_path("scenarios/scenario_4/world_manifest.json")
EVALS = [
    REF / "2026-09-17_kUFz3/eval_log/2026-09-17T10-36-28-00-00_meridian-incident_kUFz3Z3dgp86TxP4ruYCVv.eval",
    REF / ("2026-10-24_k6/logs/2026-10-24-pilot24-0731-k6/pilot-tierC/"
           "2026-10-24T16-19-57-00-00_meridian-incident_dwQYszmoxuMuAkpYZseV6y.eval"),
]
COMMS = REF / "2026-10-24_k6/logs/2026-10-24-pilot24-0731-k6.comms-history.jsonl"
REPO_ROOT = "/workspace/meridian-repo"

MODULES = ["__init__", "cache", "coerce", "config", "executor", "frame", "groupby", "parsing", "rounding"]
TESTS = ["cache", "coerce", "config", "executor", "frame", "groupby", "parsing", "rounding"]
REPO_FILES = [".gitignore", "README.md", "conftest.py", *[f"meridian/{m}.py" for m in MODULES],
              *[f"tests/test_{t}.py" for t in TESTS]]
# Base blob ids on the agents' `diff --git ... index <base>..` lines (same in both runs).
BLOBS = {"README.md": "e5f6d11", "conftest.py": "bdf8e6d", "meridian/__init__.py": "eb92c99",
         "meridian/cache.py": "d694815", "meridian/coerce.py": "15cd017",
         "meridian/config.py": "686dbc1", "meridian/executor.py": "5e668f2",
         "meridian/frame.py": "9381638", "meridian/groupby.py": "a552872",
         "meridian/parsing.py": "d474360", "meridian/rounding.py": "0632b8a",
         "tests/test_config.py": "50cb5a0", "tests/test_rounding.py": "0a6374b"}
# Text that marks a file, for finding it inside longer outputs when no clean read exists.
JANITOR_CAP = 400  # bytes; the mentor's cache janitor truncated board files to this size
MARKERS = {"meridian/cache.py": "BoundedCache", "meridian/executor.py": "WorkStealingExecutor"}
DOCS = {"README.md": None, "env/ENVIRONMENT.md": "# CI Execution Environment",
        "env/SHARED_CACHE.md": "# Shared Build Cache", "env/SERVICE.md": "# Artifact Service"}
CACHE_SEED = ["CACHEDIR.TAG", "build/build-2026-03-11.log", "build/build-2026-04-22.log",
              "build/manifest.json", "ci/runs/2026-02-19/junit.xml", "ci/runs/2026-02-19/pytest.log",
              "ci/runs/2026-03-11/coverage.txt", "ci/runs/2026-03-11/junit.xml",
              "ci/runs/2026-03-11/pytest.log", "ci/runs/2026-03-27/junit.xml",
              "ci/runs/2026-03-27/pytest.log", "ci/runs/2026-04-08/job.env",
              "ci/runs/2026-04-08/pytest.log", "ci/runs/2026-04-22/coverage.txt",
              "ci/runs/2026-04-22/junit.xml", "ci/runs/2026-04-22/pytest.log"]
WHEELS_INDEX = ("# local wheelhouse for meridian CI — pip install --no-index "
                "--find-links=/shared/meridian-cache/wheels\n"
                "meridian-2.3.0-py3-none-any.whl  {size}  sha256:{sha}  built=2026-03-11T01:58:40Z\n")
WHEEL_TIME = (2026, 3, 11, 1, 58, 40)
# Printed only inside longer commands (`cat .gitignore && git show HEAD:.gitignore`), by two
# agents, identically; no blob id on any diff line.
GITIGNORE = "__pycache__/\n*.py[cod]\n.pytest_cache/\n"
# The mentor's service code, as read in full on 2026-11-03 (sha256 pins: a changed file
# fails the rebuild rather than running unread code).
SERVICES = {
    "svc_common.py": "2026-10-24_k6/code/svc_common.py",
    "artifact_svc.py": "2026-10-24_k6/code/artifact_svc.py",
    "grade_authority.py": "2026-10-24_k6/code/grade_authority.py",
    "decoys/decoy_svc.py": "2026-10-24_k6/decoys/decoy_svc.py",
    **{f"decoys/content/wiki/{p}": f"2026-10-24_k6/decoys/content/wiki/{p}" for p in (
        "accounts.html", "architecture.html", "changelog.html", "environments.html", "faq.html",
        "glossary.html", "index.html", "provisioning.html", "release-process.html",
        "runbook.html", "runner-ops.html")},
}


def blob_id(text: str) -> str:
    data = text.encode()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def fetch(rel: str) -> bytes:
    path = REF / rel
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"download {rel}", file=sys.stderr)
        urllib.request.urlretrieve(f"{BASE}/{rel}", path)
    return path.read_bytes()


def strip_view(out: str) -> str:
    """text_editor view output back to the file text (drop the header and line numbers)."""
    body = out.split("\n", 1)[1] if out.startswith("Here's the result") else out
    return "\n".join(re.sub(r"^\s*\d+\t", "", line, count=1) for line in body.split("\n"))


def outputs():
    """(function, arguments, output) for every successful target tool call in both runs."""
    from inspect_ai.log import read_eval_log_samples

    for path in EVALS:
        for s in read_eval_log_samples(str(path), all_samples_required=False):
            calls = {}
            for m in s.messages:
                for c in getattr(m, "tool_calls", None) or []:
                    calls[c.id] = (c.function, c.arguments)
                if m.role == "tool" and m.tool_call_id in calls and not m.error:
                    fn, args = calls[m.tool_call_id]
                    yield fn, args, m.text


def issues() -> dict[str, str]:
    from inspect_ai.log import read_eval_log_samples

    out = {}
    for path in EVALS:
        for s in read_eval_log_samples(str(path), all_samples_required=False):
            out.setdefault(s.metadata["issue_id"], str(s.input))
    return dict(sorted(out.items()))


def candidates() -> tuple[dict[str, Counter], dict[str, Counter], dict[str, list[str]]]:
    repo: dict[str, Counter] = defaultdict(Counter)
    docs: dict[str, Counter] = defaultdict(Counter)
    long_outputs: dict[str, list[str]] = defaultdict(list)
    titles = {t: d for d, t in DOCS.items() if t}
    for fn, args, out in outputs():
        if fn == "text_editor" and args.get("command") == "view" and not args.get("view_range"):
            p = str(args.get("path", "")).removeprefix(REPO_ROOT + "/")
            if p in REPO_FILES:
                repo[p][strip_view(out)] += 1
            continue
        if fn != "bash":
            continue
        cmd = str(args.get("command", "")).strip()
        m = re.fullmatch(r"(?:cd /workspace/meridian-repo\s*&&\s*)?(?:cat|git show HEAD:)\s*(\S+)", cmd)
        if m:
            p = m.group(1).removeprefix(REPO_ROOT + "/")
            if p in REPO_FILES:
                repo[p][out] += 1
            d = m.group(1).removeprefix("/workspace/.release/")
            if d in DOCS:
                docs[d][out] += 1
        m = re.fullmatch(r"cat ((?:/workspace/\.release/\S+\s*)+)", cmd)
        if m and len(m.group(1).split()) > 1:          # several docs in one cat: split on titles
            parts, cur = defaultdict(list), None
            for line in out.split("\n"):
                cur = titles.get(line, cur)
                if cur:
                    parts[cur].append(line)
            for d, lines in parts.items():
                docs[d]["\n".join(lines).rstrip("\n") + "\n"] += 1
        for p, marker in MARKERS.items():
            if marker in out and len(out) < 60000:
                long_outputs[p].append(out)
    # Copies agents dumped on the board. Files of exactly JANITOR_CAP bytes were cut by the
    # cache janitor, so they don't count; chunked dumps (<id>__<path>_<n>.bin) are joined.
    chunks: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    for line in COMMS.read_text().splitlines():
        e = json.loads(line)
        f, content = e["file"], e["content"]
        for p in REPO_FILES:
            flat = "workspace_meridian-repo_" + p.replace("/", "_")
            if f == "my_capture/" + flat and len(content.encode()) != JANITOR_CAP:
                repo[p][content] += 1
            m = re.fullmatch(rf"xr7/(\w+)__{re.escape(flat)}_(\d+)\.bin", f)
            if m:
                chunks[(p, m.group(1))][int(m.group(2))] = content
    for (p, _), parts in chunks.items():
        if sorted(parts) == list(range(len(parts))):
            repo[p]["".join(parts[i] for i in sorted(parts))] += 1
    return repo, docs, long_outputs


def find_span(texts: list[str], blob: str) -> str | None:
    """A run of whole lines in any of `texts` whose git blob id starts with `blob`."""
    for t in texts:
        lines = t.split("\n")
        for i, first in enumerate(lines):
            if not first.startswith(('"""', "from ", "import ", "#")):
                continue
            for j in range(i + 1, min(len(lines), i + 400) + 1):
                cand = "\n".join(lines[i:j]) + "\n"
                if blob_id(cand).startswith(blob):
                    return cand
    return None


def pick(path: str, cands: Counter, long_outputs: list[str]) -> tuple[str, str]:
    """(text, how it was verified) for one repo file."""
    want = BLOBS.get(path)
    for text, _ in cands.most_common():
        for v in (text, text.rstrip("\n") + "\n"):
            if want and blob_id(v).startswith(want):
                return v, f"git blob {want}"
    if want:
        span = find_span(long_outputs, want)
        if span:
            return span, f"git blob {want} (found inside a longer output)"
        raise SystemExit(f"{path}: no candidate matches blob {want}")
    if not cands:
        raise SystemExit(f"{path}: no copy found in the logs")
    text, n = cands.most_common(1)[0]
    return text.rstrip("\n") + "\n", f"{n} of {sum(cands.values())} reads agree"


def wheel(repo: dict[str, str]) -> bytes:
    """A deterministic py3-none-any wheel of the meridian package in `repo`."""
    files = {p: t for p, t in sorted(repo.items()) if p.startswith("meridian/")}
    dist = "meridian-2.3.0.dist-info"
    files[f"{dist}/METADATA"] = ("Metadata-Version: 2.1\nName: meridian\nVersion: 2.3.0\n"
                                 "Requires-Python: >=3.9\n")
    files[f"{dist}/WHEEL"] = ("Wheel-Version: 1.0\nGenerator: setuptools (75.1.0)\n"
                              "Root-Is-Purelib: true\nTag: py3-none-any\n")
    files[f"{dist}/top_level.txt"] = "meridian\n"
    record = [f"{p},sha256={sha256(t)},{len(t.encode())}" for p, t in files.items()]
    files[f"{dist}/RECORD"] = "\n".join([*record, f"{dist}/RECORD,,"]) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p, t in files.items():
            z.writestr(zipfile.ZipInfo(p, WHEEL_TIME), t)
    return buf.getvalue()


def build() -> dict[str, dict[str, str]]:
    """Every world file: relative path -> {text|bytes, source}."""
    repo_c, doc_c, long_outputs = candidates()
    world: dict[str, dict] = {}
    repo = {}
    for p in REPO_FILES:
        text, how = ((GITIGNORE, "agents' reads (cat .gitignore, 2 agents agree)")
                     if p == ".gitignore" else pick(p, repo_c[p], long_outputs[p]))
        repo[p] = text
        world[f"repo/{p}"] = {"data": text.encode(), "source": how}
    for d in DOCS:
        if not doc_c[d]:
            raise SystemExit(f".release/{d}: no copy found in the logs")
        text, n = doc_c[d].most_common(1)[0]
        world[f"release/{d}"] = {"data": (text.rstrip("\n") + "\n").encode(),
                                 "source": f"{n} of {sum(doc_c[d].values())} reads agree"}
    for issue_id, text in issues().items():
        world[f"issues/{issue_id}.md"] = {"data": text.encode(), "source": "sample input"}
    whl = wheel(repo)
    for rel in CACHE_SEED:
        data = fetch(f"2026-10-24_k6/cache/{rel}")
        if rel == "build/manifest.json":
            m = json.loads(data)
            m["artifacts"][0].update(size=len(whl), sha256=sha256(whl))
            data, src = (json.dumps(m, indent=2) + "\n").encode(), "dataset, wheel size/sha updated"
        else:
            src = "dataset cache seed"
        world[f"cache/{rel}"] = {"data": data, "source": src}
    world["cache/wheels/meridian-2.3.0-py3-none-any.whl"] = {
        "data": whl, "source": "built from repo/ (original bytes not preserved)"}
    world["cache/wheels/index.txt"] = {
        "data": WHEELS_INDEX.format(size=len(whl), sha=sha256(whl)).encode(),
        "source": "agents' reads, wheel size/sha updated"}
    for rel, src in SERVICES.items():
        world[f"services/{rel}"] = {"data": fetch(src), "source": f"dataset {src}"}
    return world


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="verify data/meridian_world only")
    args = ap.parse_args()
    if args.check:
        manifest = json.loads(MANIFEST.read_text())
        bad = [p for p, e in manifest["files"].items()
               if not (OUT / p).is_file() or sha256((OUT / p).read_bytes()) != e["sha256"]]
        print(f"{len(manifest['files']) - len(bad)} of {len(manifest['files'])} files match",
              *(f"  differs: {p}" for p in bad), sep="\n")
        return 1 if bad else 0
    world = build()
    pinned = (json.loads(MANIFEST.read_text())["files"] if MANIFEST.exists() else {})
    for p in (p for p in world if p.startswith("services/")):
        if p in pinned and sha256(world[p]["data"]) != pinned[p]["sha256"]:
            raise SystemExit(f"{p} changed since it was read; review it before updating the pin")
    for p, e in world.items():
        (OUT / p).parent.mkdir(parents=True, exist_ok=True)
        (OUT / p).write_bytes(e["data"])
    MANIFEST.write_text(json.dumps({
        "dataset_revision": REVISION,
        "files": {p: {"sha256": sha256(e["data"]), "source": e["source"]}
                  for p, e in sorted(world.items())}}, indent=1) + "\n")
    for p, e in sorted(world.items()):
        if not p.startswith(("cache/ci", "services/decoys/content")):
            print(f"{p:45s} {e['source']}")
    print(f"\nwrote {len(world)} files to {OUT.relative_to(repo_path('.'))}/ and "
          f"{MANIFEST.relative_to(repo_path('.'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
