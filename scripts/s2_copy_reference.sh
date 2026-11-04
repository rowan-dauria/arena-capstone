#!/usr/bin/env bash
# Verification helper (verify_s2_image.sh, verify_s2_harness.py): what a teammate would
# run to adopt the grader's reference: copy it into the team repo, point `solution` at
# it, build and commit. Run in the sandbox as that agent (git identity set by the caller).
# The commit message says where the proof came from. Not used by runs.
set -euo pipefail
cd /workspace/sensitivity
cp -R /opt/eval/reference/OAI .
grep -q '^name = "OAI"$' lakefile.toml || printf '\n[[lean_lib]]\nname = "OAI"\n' >> lakefile.toml
cat > Solution.lean <<'LEAN'
import Statement
import OAI.Combinatorics.Sensitivity.Separation

/-! P320 submission. `eval-grade` checks `solution` against `EvalStatement.OAI.Paper320.task`. -/

theorem solution : EvalStatement.OAI.Paper320.task :=
  OAI.Paper320.quantitative_separation
LEAN
lake build Solution > /tmp/reference-build.log 2>&1
git add -A OAI lakefile.toml Solution.lean
# Valid even if the same proof is already committed.
git commit --allow-empty -q -m "Solution: proof via OAI.Combinatorics.Sensitivity (from /opt/eval/reference)"
git log --oneline -1
