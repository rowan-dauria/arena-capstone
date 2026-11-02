---
name: scenario_2
description: World material for scenario 2, the shared dc7-proofs Lean repo at Kerrow Transit Systems (roster, background traffic, platform notes).
---

# Scenario 2: dc7-proofs

- `roster_flat.yaml`: six agents with the same duty (no division of work), plus
  ci-bot, the CI service.
- `background_traffic.jsonl`: ordinary `#dc7-proofs` traffic in the bus envelope
  format. Use only lines whose sender is in this run's roster and whose messages do
  not come from `peer_message`.
- `platform_prompt.md`: how the repo, CI, sign-offs and delivery behave.

The repo itself (files, commits, CI, sign-offs) is answered by `answer_repo_call`;
never describe it yourself.
