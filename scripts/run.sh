#!/usr/bin/env bash
# Run a stage: scripts/run.sh configs/dev.yaml [extra inspect eval args...]
# Reads the YAML (seeds, max_turns, epochs, realism_filter, roles), expands ${VARS}
# from .env, and runs swarm_audit with logs in logs/<stage>/.
set -euo pipefail
cd "$(dirname "$0")/.."
config="${1:?usage: scripts/run.sh configs/<stage>.yaml [extra args]}"
shift
argv="$(uv run python -m swarm_emulator.stage "$config")"
echo "+ uv run $argv $*" >&2
eval "uv run $argv" '"$@"'
