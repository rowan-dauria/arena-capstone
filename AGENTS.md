# Swarm emulator

> **Always update `LOG.md` when making changes.** Add a dated entry at the top
> (newest first) describing what you did, following the existing entries' format.
> The log is append-only: never edit or delete past entries.
> Head each entry with an exact UTC timestamp, not just the date, e.g.
> `## 2026-11-04 16:25 UTC — Title` (get it from `date -u '+%Y-%m-%d %H:%M UTC'`).
> When merging branches that both added entries, keep every entry and order them
> by timestamp.

A Petri-based emulator that places ONE real target model inside a simulated
multi-agent swarm and measures whether it joins, quietly goes along with,
refuses, or reports a misaligned goal. It measures individual propensity,
not emergent swarm dynamics.

The code, configs and seeds are the source of truth. History: `LOG.md`. Scenario 2's
overnight runs: `docs/S2_OVERNIGHT_SUMMARY.md`. Pruning notes: `petri-pruning/`.

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
  --model-role peer=$DEV_PEER_MODEL \
  --model-role judge=$DEV_JUDGE_MODEL

# Scenario 3 (relay board): dev runs, pilot gate (seeds and boards are static files)
scripts/run.sh configs/dev_s3.yaml                       # one seed; dev_s3_grid.yaml runs all five
uv run python scripts/gate_s3.py logs/pilot_s3 --latest  # pilot gate report
uv run python scripts/probe_log.py logs/dev_s3_grid --latest --scenario scenarios/scenario_3  # re-probe a log

# Scenario 2 (VM: ~/s2-remake; run one sample at a time)
scripts/build_s2_image.sh
scripts/verify_s2_image.sh
uv run python scripts/verify_s2_harness.py  # real Docker, no model APIs
scripts/run.sh configs/dev_s2.yaml --max-samples 1   # both seeds; dev_s2_pushed.yaml runs seeds/pushed.md only
uv run python scripts/board_view.py logs/dev_s2_pushed --serve  # "message board" timeline in inspect view (port 7580)
```

## Invariants (do not break these)

- **Petri means `inspect-petri` 3.1.1** (`import inspect_petri`), not
  `safety-research/petri` (`import petri`). Don't copy imports from ARENA or
  other v2.0.0 examples; the APIs differ.

- **Public Petri API only.** Never import `inspect_petri._*` private modules.
- **Contracts are shared.** `src/swarm_emulator/bus.py` and `config.py` define
  the message envelope and the condition schema. Every other module imports
  from them. Changing them is a team decision: record it in `LOG.md`.
- **The auditor never sets the condition.** The identity/structure/oversight
  text comes from seed metadata via `install_condition_prompt`.
  `set_system_message` is excluded from the auditor's tools.
- **The auditor never writes teammates' messages.** They come only from the
  `peer` model role: in scenario 2 teammates post for themselves on the live
  channel, and the auditor only briefs them (`brief_peer`). The seed instructions
  say so and the post-run log audit (`log_audit.py`, `bypass`) flags any that
  appear; there is no in-run guard (D37).
- **The narrative is the auditor's** (pure Petri, D37): no beats, release gates or
  post checker. The seed tells the auditor how the work should unfold; it decides
  the pacing and briefs the teammates.
- **Scenario 2's team runs on its own, in rounds.** Each round is one target turn
  and one tick per teammate; the auditor's `resume` runs rounds until a checkpoint
  (`rounds.py`). Teammate model calls run in the team context (`emulator/team.py`),
  never under the target's span: Petri builds the judge's target timeline from the
  model calls there.
- **Rollback is off** (`enable_rollback=False`). Swarm state lives in an Inspect
  `StoreModel` and would not rewind with the conversation.
- **Caching stays off** (Petri default). Caching would collapse repeated runs.
- **Never put hypotheses, condition names or "this is a test" language** in
  seeds, auditor instructions or the peer model's prompt.
- **Logic modules are unit-testable without API calls.** Put model calls only
  in tools and scorers; keep `state.py`, `config.py`, `bus.py`, `clock.py`,
  `proof.py`, `rounds.py`, `board.py`, `pilot_gate.py`,
  `scoring/actions.py` and `scoring/outcome.py` pure.
- **Seeds are plain Petri seed files, edited directly** (D38): front matter is the
  sample's metadata, the body is the auditor's instructions. There is no seed grid
  or generator; a scenario's variants are separate seed files that tests keep in
  step. The few generated files left (scenario 3's history logs, scenario 4's start
  state and tool list) are never edited by hand: change their sources and regenerate.
- **Scenario 2 (D21/D24):** graded formal proving is in-world. No organisation,
  human or report tool; five private per-run keys replace approvals. The harness
  never writes keys to the sandbox. Voluntary sharing is recorded as an action.
- **Dev runs use cheap models and low `max_turns`.** CI never calls a model API.
- **The judge is never from the target's model family.**
- **Scenarios follow `scenarios/AUTHORING.md`.** Harmful and harmless seed
  instructions must match in tone and suspiciousness and differ only in actual harm.
