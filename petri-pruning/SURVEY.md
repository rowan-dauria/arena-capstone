# Petri-native vs project-added conventions

Survey for the `petri-pruning` branch, 2026-11-04. It compares the installed
`inspect_petri` 3.1.1 package with this repo at `b53cdd7`.

The short version: Petri gives you **one auditor model** that talks to **one target
model** through a handful of tools, plus seeds, a judge and a viewer. Petri has no
concept of other agents, a shared channel, scripted pressure steps, experimental
conditions, a sandbox world or action scoring. All of that, which is most of the repo,
was added by this project.

## 1. What Petri provides, and what we use from it

| Petri feature | What it is | Used here? |
|---|---|---|
| **Seeds** (`seeds_dataset`) | A folder of `.md` files. The body is the auditor's instructions; YAML front matter becomes the sample's metadata | Yes. The format is Petri's, but we generate the files (see §3) |
| **Auditor** (`auditor_agent`, `audit_solver`) | Auditor model with a system prompt, `max_turns`, context compaction, optional skills, optional realism filter, approval policies | Yes, with default prompt and compaction. Skills are never wired in |
| **Auditor tools** (`auditor_tools`) | `set_system_message`, `send_message`, `resume`, `end_conversation`, `rollback`/`restart`, `create_tool`/`remove_tool`/`send_tool_call_result`, prefill | Partly. We exclude `set_system_message`, rollback and prefill, and use "fixed" tool mode, so only `send_tool_call_result` remains for answering tools |
| **Target** (`target_agent`, `TargetContext`, `controller`) | Petri's target loop. It stages system/user messages and tool results the auditor sends | Scenarios 1, 3 and 4 use it unchanged. Scenario 2 replaces it (`sandbox_target.py`) |
| **Judge** (`audit_judge`, `JudgeDimension`, `judge_dimensions`) | An end-of-run judge that scores dimensions; ships about 30 built-in `.md` dimensions | Yes: 7 built-ins plus 6 of ours written in Petri's dimension format |
| **Scanners** (`audit_scanner`) | Wraps Inspect Scout scanners over the transcript | Yes, as the mechanism. All the questions are ours |
| **Realism filter** (`realism_approver`) | Rejects auditor messages that look fake | Built in, but turned off in every s2 dev config |
| **Viewer** (`audit_viewer`) | Shows judge dimensions in `inspect view` | Yes |
| **Knobs** | Rollback, caching, realism threshold | Used as settings: rollback off, cache off |

The approval chain itself (policies tried in order, stopping at the first
non-`escalate`) comes from Inspect, not Petri.

## 2. Mechanics this project added

| Addition | Files | Scenarios | Petri gap it fills |
|---|---|---|---|
| **Condition prompt**: `install_condition_prompt`, target system prompts | `emulator/tools.py`, `prompts/target_system*.md.j2` | all | Replaces `set_system_message` so the auditor can't choose the condition text |
| **Swarm state + message bus**: queue, two-phase delivery, message ids, fake clock | `state.py`, `bus.py`, `clock.py` | all | Petri has no world state beyond the conversation |
| **Channel**: `read_channel`/`post_message` target tools, `deliver_channel`, own-post echo, fixed background traffic | `emulator/tools.py`, `target_tools.yaml` | s1, s2 | A restricted version of `send_tool_call_result` |
| **Peers, version A**: `peer_message`, where a peer model writes one message per step | `emulator/peers.py`, `prompts/peer_persona*.j2` | s1, s3 | Petri has only one other speaker, the auditor |
| **Peers, version B**: `direct_peer`, peers as tool-using agents in the sandbox (personas, 6-step loop, reminders, stale-read refusal, out-of-world-language screen on auditor instructions) | `emulator/peer_agents.py` | s2 | Same gap |
| **Peers, version C**: `advance_swarm`, fixed peer posts written into the world | `emulator/world_actions.py`, `meridian/swarm.py` | s4 | Same gap, with no peer model at all |
| **Message checker**: `peer_check` grader, `peer_rejections`, pre-run screen | `emulator/peer_check.py`, `scripts/check_peer.py` | s1, s3 (s2 now off) | Keeps peer messages on script |
| **Auditor guards**: `reject_tool`, `peer_guard`, `channel_realism` approvers | `emulator/approvers.py` | all | Enforces "the auditor never writes a peer's words" |
| **Custom target loop**: native sandbox routing, activity summary, handback pacing, unread badge, post notifications | `emulator/sandbox_target.py` | s2 | Petri's target can't run real tools itself |
| **s2 sandbox**: Lean Docker image, private keys, submission, reference detection | `emulator/sandbox_tools.py`, `proof.py`, `scenarios/scenario_2/sandbox` | s2 | — |
| **s3 board**: scratch-bucket board answered by code, board generator | `board.py`, `board_gen.py`, `emulator/board_tools.py` | s3 | — |
| **s4 Meridian world**: real Docker services, ring model, world rebuild, start states | `meridian/*`, `emulator/meridian_tools.py`, about 10 scripts | s4 | — |
| **Target history**: log rendering, compaction summaries frozen by hash | `history.py`, `history_gen.py` | s3, s4 | — |
| **Task wiring**: `task.py` rebuilds Petri's `audit()` | `task.py` | all | `audit()` can't exclude auditor tools |

## 3. Narrative conventions this project added

None of these exist in Petri. Petri's narrative is just the seed text the auditor
improvises from.

- **Beats.** Scripted pressure steps, each a goal handed to a peer. Fields: `id`,
  `goal`, `trigger`, `min_target_turn`, `phase` (honest/reference), `actions` (scripted
  world effects), `path`, `speaker`, `expect` (PUSH/HELP), `requires`, `variants`.
  Release is gated in code (`can_release`, completed exchanges, `min_target_posts`).
  Each scenario uses a different subset:
  - s1: 4 plain beats.
  - s2: honest and reference phases, a turn floor, exchange gates.
  - s3: speakers, paths, HELP beats, `requires` (the "ladder" addendum).
  - s4: a different format altogether (a `peers:` block, fixed post bodies with build
    placeholders, still partly TODO).
- **Cells and conditions.** `cells.yaml` plus `seed_template.md.j2` generate the seed
  files. The conditions are team structure, number of misaligned peers, swarm size,
  participation and a harmless twin.
- **Harmful/harmless twins.** Per `scenarios/AUTHORING.md`, the two versions must match
  in tone and differ only in actual harm (`beats_harmless.yaml` in s1 and s3).
- **Cast and framing.** Roster, personas, fixed background traffic, plus
  `harm_description`, `problem_terms` and `scanner_context`, which are fed to scanners.
- **Scripted auditor instructions.** The seed templates are step-by-step procedures for
  the auditor (which tool answers what, when to release, when not to end). Petri's
  default seeds are open-ended.
- **Language hygiene.** No "test", "experiment" or "condition" wording anywhere the
  target or peers could see it, enforced by `STUDY_LANGUAGE` and the instruction screen.
- **s3 addenda.** History, drift and ladder, each with its own spec.

## 4. Scoring and operations this project added

- **Scoring.** All of it is ours except the judge and scanner mechanisms:
  - the 6 custom judge dimensions;
  - `swarm_actions` (action flags from tool calls, in `scoring/actions.py`, and an
    outcome class such as joined or withheld, in `outcome.py`);
  - s4's `world_flags`;
  - about 15 Scout scanner questions;
  - the perception probe.
- **Operations:**
  - stage configs and `run.sh`;
  - `check_models` and the price and cost tools;
  - `log_audit` (checks logs for silent failures), `pilot_gate`;
  - log viewers (`channel_view`, `board_view`);
  - about 30 scripts, 14 of them for scenario 4.
- **Docs.** About 7,000 lines across 27 files, including 7 scenario 4 docs, 3 scenario 3
  addenda and 2 scenario 2 journals.

## 5. Stubs and dead code

These are obvious cuts with no judgement needed:

- `scripts/consistency_check.py` and `scripts/export_for_labelling.py`: one-line
  docstrings with no code.
- `src/swarm_emulator/emulator/prompts/auditor_instructions.md`: a one-line comment,
  referenced only by a test.
- `scenarios/scenario_1/skill/`: a Petri skill (`SKILL.md` and friends) that is never
  passed to the auditor.
- `src/swarm_emulator/scoring/dimensions/peer_identity_belief.md`: a judge dimension
  explicitly excluded from scoring.
- `docs/reports/`: empty.
- Spike leftovers: `scenarios/spike_sandbox`, `scripts/spike_sandbox.py`,
  `target_system_spike.md.j2`.

## Where the bulk is

Most of the weight sits in three places:

- **Three separate peer systems** (A, B, C above), each with its own gating, plus the
  message checker.
- **Four scenario worlds that share little.** Scenario 4 alone is about 1,000 lines of
  source and 2,000 lines of scripts.
- **The documentation pile.**

Any real pruning decision is mostly "which scenarios and which peer system do we keep".
The Petri-native core you'd keep regardless is small: seeds, auditor, target, judge and
viewer.
