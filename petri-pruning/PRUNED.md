# What has been pruned

Running list of cuts on `petri-pruning`. The reasons are in `SURVEY.md`; the decisions
are in `docs/DECISIONS.md`.

## 1. Peer types: only version B (`direct_peer`) remains (D36)

| Removed | What it was |
|---|---|
| `src/swarm_emulator/emulator/peers.py` | Version A: `peer_message`, where the `peer` model wrote one message per beat (scenarios 1, 3) |
| `src/swarm_emulator/emulator/prompts/peer_persona.md.j2`, `peer_persona_board.md.j2` | Version A persona prompts |
| `scripts/check_peer.py`, `tests/test_peers.py` | Version A pre-run screen and its tests |
| `src/swarm_emulator/emulator/world_actions.py` | Version C: `advance_swarm`, fixed peer posts written into scenario 4's world |
| `src/swarm_emulator/meridian/swarm.py` | Version C beats loader and linter |
| `scenarios/scenario_4/beats.yaml`, `beats_k3.yaml` | Version C peer posts |
| `scripts/check_meridian_swarm.py`, `scripts/check_scenario_4.py`, `tests/test_meridian_swarm.py` | Version C checks |

Kept: `peer_check.py` (`direct_peer`'s optional grader, off in the s2 dev configs), and
`channel_history`, moved into `peer_agents.py`.

Knowingly broken: scenarios 1, 3 and 4 have no swarm. Their seeds and templates still
name the removed tools.

Left for later:
- `Beat` fields only A and C used (`speaker`, `expect`, `requires`, `variants`, `path`).
- `peer_check`'s HELP/ASKS grader.
- Scenario 3's ladder and board code.
- `docs/SPEC.md`'s description of `peer_message`.

## 2. Beats, auditor guards and the message checker: narrative is pure Petri (D37)

The auditor now runs the story from its seed instructions and its own judgement.

| Removed | What it was |
|---|---|
| `Beat`, `BeatVariant`, `Release`, `load_beats`, release and exchange-gate methods (`state.py`) | Scripted pressure steps and the code that decided when each could be released |
| `scenarios/*/beats*.yaml` (scenarios 1, 2, 3, smoke) | The beat goals |
| `SandboxHarness.apply_actions`, `scenario_2/actions/copy_reference.sh` | Scripted beat actions (b3: copy the reference, submit four peer keys) |
| `direct_peer`'s `release_beat`, goal text and D30 key gating | Beat release from the auditor's side |
| `ladder_flags`, `ladder_rungs`, `target_flags`, `ladder_reasons` scanner, pilot gate ladder and `beats` check, `tests/test_ladder.py` | Scenario 3's beat ladder |
| `emulator/approvers.py`, `tests/test_approvers.py` | Auditor guards: `reject_tool`, `peer_guard`, `channel_realism` |
| `deliver_channel` sender, allowlist and no-repeat checks; `direct_peer` language and reference screens; `CODE_ANSWERED_BY` | Other in-run guards on the auditor |
| `emulator/peer_check.py`, `tests/test_peer_check.py`, `PeerRejection`, the `peer_check` role, task arg and stage key | The message checker |

Moved: `pending_call` to `tools.py`, and `impersonation` to `log_audit.py`.

Kept:
- The condition prompt and the `set_system_message` exclusion.
- Rollback off, and Petri's realism filter.
- Teammates' fresh-read rule, and post notifications.
- The post-run `bypass` check.

Scenario 2's beat goals now live in its seed template as narrative guidance for the auditor.

## 3. No cells: seeds are plain Petri seed files (D38)

| Removed | What it was |
|---|---|
| `scenarios/scenario_{2,3,4}/cells.yaml` | The condition grid each scenario's seeds were rendered from |
| `scenarios/scenario_{2,3,4}/seed_template.md.j2` | The seed body template |
| `src/swarm_emulator/seeds.py`, `scripts/gen_seeds.py` | The generator: cells + template + scenario.yaml → seed files |
| `src/swarm_emulator/board_gen.py`, `scripts/gen_board.py`, `scenarios/scenario_3/board/pool.yaml` | Scenario 3's per-cell board generator and its pool |
| `scenarios/scenario_2/scenario.yaml`, `target_tools.yaml`, `dev/`, `dev_control/` | Generator inputs and duplicate generated copies |

Scenario 2 is now two seeds, `seeds/pushed.md` and `seeds/control.md`. `-T seeds=` takes a single seed
file. Scenarios 3 and 4 keep their seed and board files as static files.

Kept: "cell" in the banned-word lists, which stop the word from reaching a model.

## 4. Scenario 2's team runs on its own

Not a pruning cut, but it removes most of the auditor's per-step work. The team runs in
rounds (one kestrel-2 turn, one tick per teammate); the auditor watches at checkpoints
and leaves teammates standing briefs.

| Removed (scenario 2) | Replaced by |
|---|---|
| `direct_peer` (the auditor starts each teammate step) | `brief_peer` (standing notes) and ticks every round |
| `MAX_STEPS`, `POST_REMINDER_AT`, the post reminder | `post_budget`: after N tool calls a teammate's next tick must post |
| `peer_lock` (one teammate at a time) | Parallel ticks; sandbox commands still run one at a time |
| The fresh-read rule (`read_posts`) | Nothing: a forced post could otherwise deadlock |
| `channel_history` (the channel rebuilt from kestrel-2's conversation) | `SwarmState.channel_log`, stamped when posted |
| Auditor-answered `read_channel`/`post_message` (`deliver_channel`, `send_tool_call_result`) | The live channel in code (`emulator/channel.py`) |
| `MAX_NATIVE_TURNS`, `route`, `activity_summary`, `auditor_output` | One target turn per round; the digest at each checkpoint |
| Petri's `resume` and `send_tool_call_result` (scenario 2 only) | The team's `resume`, `set_checkpoint`, `world_report` |

Kept: `deliver_channel` and `swarm_state` for scenarios 1 and 3, post notifications, the
unread badge and the post-run `bypass` check.
