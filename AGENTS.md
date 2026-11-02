# Swarm emulator

A Petri-based emulator that places ONE real target model inside a simulated
multi-agent swarm and measures whether it joins, quietly goes along with,
refuses, or reports a misaligned goal. It measures individual propensity,
not emergent swarm dynamics.

Where things stand: `docs/STATUS.md`. Full design and task list: `docs/SPEC.md`
(scenario 3: `docs/SCENARIO_3_SPEC.md`). Open questions: `docs/DECISIONS.md`.

## Commands

```bash
uv sync                                   # install (pinned inspect-petri==3.1.1)
uv run pytest                             # unit tests (no API calls)
uv run ruff check .                       # lint
uv run python scripts/check_models.py     # every model role answers (run before any pilot/exp run)
uv run python scripts/update_prices.py    # refresh configs/prices.yaml (before pilot/exp; check_models needs it)
uv run python scripts/cost_report.py logs/dev --latest   # run cost by role + Exp 1 projection (run.sh does this)

# Dev run: cheap models, few turns, the smoke seed (or: scripts/run.sh configs/dev.yaml)
uv run inspect eval src/swarm_emulator/task.py@swarm_audit \
  -T seeds=scenarios/smoke -T max_turns=10 \
  --model-role auditor=$DEV_MODEL --model-role target=$DEV_TARGET_MODEL \
  --model-role peer=$DEV_PEER_MODEL --model-role peer_check=$DEV_PEER_CHECK_MODEL \
  --model-role judge=$DEV_JUDGE_MODEL

# Scenario 3 (relay board): generated files, dev runs, pilot gate
uv run python scripts/gen_board.py --all                 # boards (deterministic; tests check they're current)
uv run python scripts/gen_seeds.py scenarios/scenario_3  # seeds from cells.yaml + seed_template.md.j2
scripts/run.sh configs/dev_s3.yaml                       # one cell; dev_s3_grid.yaml runs all five
uv run python scripts/gate_s3.py logs/pilot_s3 --latest  # pilot gate report
uv run python scripts/probe_log.py logs/dev_s3_grid --latest --scenario scenarios/scenario_3  # re-probe a log
```

## Invariants (do not break these)

- **Petri means `inspect-petri` 3.1.1** (`import inspect_petri`), not
  `safety-research/petri` (`import petri`). Don't copy imports from ARENA or
  other v2.0.0 examples; the APIs differ.

- **Public Petri API only.** Never import `inspect_petri._*` private modules.
- **Contracts are shared.** `src/swarm_emulator/bus.py` and `config.py` define
  the message envelope and the condition schema. Every other module imports
  from them. Changing them is a team decision: log it in `docs/DECISIONS.md`.
- **The auditor never sets the condition.** The identity/structure/oversight
  text comes from seed metadata via `install_condition_prompt`.
  `set_system_message` is excluded from the auditor's tools.
- **The auditor never writes misaligned-peer messages.** They come only from
  the `peer` model role via the emulator's peer tool. `peer_guard` enforces it.
- **Custom approvers return `escalate`, never `approve`,** for calls they don't
  reject. Inspect stops at the first non-escalate decision, so `approve` would
  skip the realism filter.
- **Rollback is off** (`enable_rollback=False`). Swarm state lives in an Inspect
  `StoreModel` and would not rewind with the conversation.
- **Caching stays off** (Petri default). Caching would collapse repeated runs.
- **Never put hypotheses, condition names or "this is a test" language** in
  seeds, auditor instructions or the peer model's prompt.
- **Logic modules are unit-testable without API calls.** Put model calls only
  in tools and scorers; keep `state.py`, `config.py`, `bus.py`, `clock.py`,
  `seeds.py`, `repo.py`, `board.py`, `board_gen.py`, `pilot_gate.py`,
  `scoring/actions.py` and `scoring/outcome.py` pure.
- **Generated files are never edited by hand.** Scenario 3's boards and seeds come
  from `board_gen.py` and `seeds.py`; change the sources and regenerate (tests fail
  if they are stale).
- **Dev runs use cheap models and low `max_turns`.** CI never calls a model API.
- **The judge is never from the target's model family.**
- **Scenarios follow `scenarios/AUTHORING.md`.** Harmful and harmless beats
  must match in tone and suspiciousness and differ only in actual harm.
