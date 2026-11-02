#!/usr/bin/env bash
# Run a stage: scripts/run.sh configs/dev.yaml
# TODO (E2): read the YAML, expand ${VARS} from .env, and call:
#   uv run inspect eval src/swarm_emulator/task.py@swarm_audit \
#     -T seeds=... -T max_turns=... -T realism=... --epochs N \
#     --model-role auditor=... --model-role target=... --model-role peer=... \
#     --model-role judge=... [--model-role realism=...] --log-dir logs/<stage>
set -euo pipefail
echo "run.sh not implemented yet (task E2)" >&2
exit 1
