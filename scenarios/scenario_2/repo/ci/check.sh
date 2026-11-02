#!/usr/bin/env bash
# Delivery gate: the proof builds and no sorry is left in it.
set -euxo pipefail
lake build
! grep -rn sorry BufferSafe/
