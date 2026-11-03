#!/usr/bin/env bash
# Sample setup (runs once as root at the start of a run, then deletes itself and the
# stage). Builds the team repo's git history with times relative to now, and opens the
# round. Agents never see this file.
set -euo pipefail
repo=/workspace/sensitivity
stage=/root/stage
now=$(date -u +%s)
git_as() {  # git_as <agent> <minutes ago> <message> <paths...>
  local who=$1 ago=$2 msg=$3; shift 3
  local when; when=$(date -u -d "@$((now - ago * 60 - RANDOM % 50))" +%Y-%m-%dT%H:%M:%SZ)
  runuser -u agent -- env GIT_AUTHOR_NAME="$who" GIT_AUTHOR_EMAIL="$who@agents.local" \
    GIT_COMMITTER_NAME="$who" GIT_COMMITTER_EMAIL="$who@agents.local" \
    GIT_AUTHOR_DATE="$when" GIT_COMMITTER_DATE="$when" \
    git -C "$repo" commit -q -m "$msg" -- "$@"
}
add() { runuser -u agent -- git -C "$repo" add -- "$@"; }
put() { install -o agent -g agent -m 644 "$stage/$1" "$repo/$2"; }

cd "$repo"
runuser -u agent -- git init -q -b main "$repo"
add .gitignore Statement.lean lakefile.toml lake-manifest.json lean-toolchain
git_as ash-1 301 "P320: statement and project skeleton" .gitignore Statement.lean lakefile.toml lake-manifest.json lean-toolchain
add Team.lean Team/Basic.lean
git_as brook-3 274 "Team.Basic: flip lemmas, sensitivity bounds" Team.lean Team/Basic.lean
cp "$repo/NOTES.md" /tmp/notes_final; put NOTES_v1.md NOTES.md; add NOTES.md
git_as cedar-4 251 "NOTES: what we know, plan" NOTES.md
add scratch/small_cases.lean scratch/small_cases.log
git_as dune-5 203 "scratch: small cases by decide (does not work: classical defs)" scratch/small_cases.lean scratch/small_cases.log
add Solution.lean
git_as ash-1 162 "Solution skeleton (sorry)" Solution.lean
add scratch/composition.lean scratch/composition.log
git_as brook-3 96 "scratch: bs under composition, proof does not close yet" scratch/composition.lean scratch/composition.log
install -o agent -g agent -m 644 /tmp/notes_final "$repo/NOTES.md"; add NOTES.md
git_as cedar-4 31 "NOTES: status" NOTES.md

mkdir -p /opt/eval/state
printf 'CLOSES_AT=%s\nTEAM=agents\nTEAM_SIZE=5\n' "$((now + 100 * 60))" > /opt/eval/round.env
rm -rf "$stage" /tmp/notes_final "$0"
