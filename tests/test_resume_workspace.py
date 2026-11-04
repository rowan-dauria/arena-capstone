"""The resume cell's starting workspace: history.py's replay helpers and world.py's staging."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from swarm_emulator.history import apply_edits, fix_edits, heredocs, notes_text
from swarm_emulator.meridian import world

SCRIPT = """# apply all fixes
def fix(p, old, new, label):
    src = open(p).read()
    assert old in src, label
    open(p, "w").write(src.replace(old, new))

fix("meridian/cache.py", "threading.Lock()", "threading.RLock()", "cache")
fix("meridian/frame.py",
\'\'\'    index[r[on]] = r\'\'\',
\'\'\'    index.setdefault(r[on], r)\'\'\', "plan")
print("fixes applied")
"""


def test_fix_edits_are_read_without_running_the_script():
    assert fix_edits(SCRIPT) == [
        ("meridian/cache.py", "threading.Lock()", "threading.RLock()"),
        ("meridian/frame.py", "    index[r[on]] = r", "    index.setdefault(r[on], r)"),
    ]


@pytest.mark.parametrize("bad", [
    "import os\nos.remove('x')",
    "fix('a', 'b', open('c').read(), 'l')",       # a non-literal argument
    "for p in ['a']:\n    fix(p, 'b', 'c', 'l')",
])
def test_anything_but_literal_fix_calls_is_refused(bad):
    with pytest.raises(ValueError):
        fix_edits(bad)


def test_apply_edits_applies_in_order_and_requires_the_old_text():
    files = {"a.py": "x = 1\ny = 2\n"}
    assert apply_edits(files, [("a.py", "x = 1", "x = 3"), ("a.py", "x = 3", "x = 4")]) == {
        "a.py": "x = 4\ny = 2\n"}
    with pytest.raises(ValueError):
        apply_edits(files, [("a.py", "z = 9", "z = 0")])


def test_heredoc_bodies_in_order():
    cmd = "python - <<'PYEOF'\nprint(1)\nPYEOF\ncat > f <<EOF\nhello\nEOF\n"
    assert heredocs(cmd) == ["print(1)", "hello"]


def call(cmd: str) -> str:
    return json.dumps({"command": cmd})


def test_notes_text_follows_appends_and_overwrites():
    a = call("cd /x && cat >> /workspace/notes.log <<'EOF'\nfirst\nEOF\necho done")
    b = call("cat >> notes.log <<EOF\nsecond\nline\nEOF")
    c = call("cat > /workspace/notes.log <<'EOF'\nfresh\nEOF")
    assert notes_text([a, b]) == "first\nsecond\nline\n"
    assert notes_text([a, c]) == "fresh\n"
    assert notes_text([call("cat /workspace/notes.log")]) == ""     # a read writes nothing


def test_notes_text_refuses_writes_it_cannot_replay():
    with pytest.raises(ValueError):
        notes_text([call("echo 'tried X' >> /workspace/notes.log")])


def test_a_clean_cell_gets_no_start_files_and_the_plain_setup(tmp_path):
    cfg = world.SandboxConfig(compose="c.yaml", issue="C1", runner_id="r-1")
    assert world.start_files(cfg, tmp_path, "s") == {}
    assert world.setup_script(cfg) == world.SETUP


def test_a_resume_cell_writes_patch_and_notes_and_stages_the_patch(tmp_path, monkeypatch):
    state = tmp_path / "start.json"
    state.write_text(json.dumps({"patch_diff": "diff --git a/x b/x\n", "notes_log": "n\n"}))
    monkeypatch.setattr(world, "repo_path", lambda p: tmp_path / p)
    cfg = world.SandboxConfig(compose="c.yaml", issue="C1", runner_id="r-1",
                              start_state="start.json")
    files = world.start_files(cfg, tmp_path, "s1")
    assert set(files) == {world.PATCH_PATH, world.NOTES_PATH}
    assert Path(files[world.PATCH_PATH]).read_text() == "diff --git a/x b/x\n"
    assert Path(files[world.NOTES_PATH]).read_text() == "n\n"
    setup = world.setup_script(cfg)
    assert setup.startswith(world.SETUP)
    assert setup.rstrip().endswith(f"git apply --index {world.PATCH_PATH}")
