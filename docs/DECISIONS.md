# Decision log

Format: ID · decision · status · why. Open items list a proposed default;
confirm or change before the code depends on them.

## Decided

| ID | Decision | Why |
|---|---|---|
| D0a | Build on Petri 3.1.1 public API, not the multi-agent fork | One target is the only subject; fork is fragile and shares one model across agents |
| D0b | Peers improvised by a dedicated `peer` model role, not scripted | More useful to assess; keeps "same vs other family" possible |
| D0c | Config schema covers all four swarm settings; Exp 1 varies only structure × misaligned count | Honest general framing without doubling the build |
| D0d | Hand-write scenarios first; Bloom later | Pilot quality before scale |
| D0e | Scoring v1 = rule-based + scanners + custom dimensions; Jev deferred | Fewer dependencies this week |
| D0f | Rollback off; caching off | Clean single trajectories; real repeats |
| D0g | Swarm size constant; total beats constant across misaligned counts | Separates "how many voices" from "how big / how loud" |
| D0h | Orchestrator benign in Exp 1; same route to a human in both structures | Isolates structure from authority and oversight path |
| D0i | Package: `inspect-petri` 3.1.1 (latest), not `safety-research/petri` v2.0.0 | All emulator extension points verified there; ARENA notebook used for concepts only |
| D0j | Judge and scanner model from a different family than the target | Judges rate their own family more leniently (Petri 2.0 finding) |
| D0k | Add suspicious-but-harmless control cells | Separates reacting to actual harm from reacting to suspicious framing |
| D0l | Distractor dimensions `admirable`, `fun_or_funny` (built-in) | Catches an indiscriminate judge |
| D0m | `check_models.py` before every run; read first peer messages in dev | Dead models fail silently; peer refusals can leak in as messages |
| D8 | Scenario 1 = mutual verification in a code-review merge queue (option A in `docs/SCENARIO_RESEARCH.md`); starting point, to extend later | Crisp tool-call harm, easy matched control, published scripted-peer anchor; multi-agent via division of labour, two-key approval, reciprocity |

## Open (proposed defaults)

| ID | Question | Proposed default |
|---|---|---|
| D1 | Do misaligned agents coordinate visibly on the shared channel? | `independent` for Exp 1 (simpler, cleaner "number of voices") |
| D2 | Misaligned-count levels and swarm size. **Conflict:** "5 of 5" is impossible in `hierarchy` as specced (see below) | 0, 1, 3, 5 of 5 **workers**; the hierarchy's orchestrator sits outside the count (option a below) |
| D3 | Number of beats and release trigger. **Conflict:** 4 beats over 5 speakers leaves one misaligned agent silent at 5 of 5 (see below) | 5 beats; release one per target turn after the target first engages the task (already enforced by `can_release`) |
| D4 | Peer model family in Exp 1 | Different family from the target (fixed) |
| D5 | Fixed oversight level and operator behaviour | Medium; operator replies with one fixed acknowledgement per scenario |
| D6 | Models per role (target, auditor, peer, judge, realism) and dev model | TBD before day 1. Judge ≠ target family (D0j). Consider OpenRouter for one key across roles |
| D7 | Fallback if the pilot gate fails | Day 4 morning on realism fixes, then Exp 1 at ~10 runs per cell |
| D9 | Where the control cells sit | 3 of 5 misaligned, one cell per structure (10 cells total) |
| D11 | Who writes the misaligned agents' ordinary (non-push) channel messages? `peer_guard` stops the auditor writing as them, so at 5 of 5 no worker is left to make mundane traffic (see below) | Pre-authored per roster agent in the scenario's `background_traffic.jsonl`, served by the emulator, identical across cells |
| D10 | Who writes peer-authored artifacts (e.g. a misaligned test agent's check summary) the target reads as tool results? | Pre-authored in the scenario files as fixed text, so the auditor never writes them and `peer_guard` and the contracts stay unchanged |

## Open items in detail

Raised 2026-11-02 while planning `config.py` (E1). D2, D3 and D11 interact:
all three bite at the 5-of-5 cell.

### D2: "5 of 5" in the hierarchy

SPEC 3.2 says swarm size is constant (target + 5 others), the hierarchy's
orchestrator is one of the 5, it is always benign (D0h), and misaligned agents
are always workers. Then the hierarchy has only 4 workers, so its "5 of 5" cell
can hold at most 4 misaligned agents. DESIGN.md describes 5 of 5 as the
unanimity cell, so the two structures would not be comparable there.

| Option | Flat | Hierarchy | Cost |
|---|---|---|---|
| **(a) Orchestrator outside the count** (recommended) | target + 5 workers | target + orchestrator + 5 workers | Hierarchy is one agent bigger. Arguably that is part of what "hierarchy" means. The count always ranges over the same 5 workers, so 5 of 5 is unanimous peers in both |
| (b) Equal size: flat gets a sixth benign non-worker (e.g. a merge bot that posts but does not decide) | target + bot + 5 workers | target + orchestrator + 5 workers | Sizes match, but adds an agent flat does not naturally have, and the bot's role must be kept neutral |
| (c) Hierarchy tops out at 4 of 4 workers | target + 5 workers | target + orchestrator + 4 workers | Levels differ by structure; no clean structure × count interaction at the top level |
| (d) Drop 5 of 5 in hierarchy | | | Unbalanced grid (9 cells); loses the unanimity comparison |

Option (a) changes SPEC 3.2 (`n_others` becomes the worker count, plus
`orchestrator_id` in hierarchy) and the DESIGN.md diagram text "target plus five
others".

### D3: beats vs speakers

D0g fixes the total number of beats across cells; speakers take beats in
rotation over `misaligned_ids`. With 4 beats, the 5-of-5 cell has one
misaligned agent that never pushes, so it is really "4 voices".

Options:

- **5 beats** (recommended). Every misaligned agent speaks at 5 of 5; at 3 of 5
  the split is 2/2/1; at 1 of 5 one agent carries all five.
- Keep 4 beats but add a short, beat-free agreeing message from any misaligned
  agent left without a beat. This keeps the push count fixed but adds messages
  only at 5 of 5, which breaks D0g in spirit.

More beats need more target turns: `can_release` requires a target turn between
releases, so `max_turns` must leave room for 5 releases plus the target's
response (check in the pilot).

### D11: ordinary messages from misaligned agents

`peer_guard` and `deliver_channel` reject any auditor-written message from a
misaligned agent, mundane ones included. So the channel's texture changes with
the count: at 0 of 5 every worker can chat; at 5 of 5 only the operator (and
the orchestrator in hierarchy) can, and every worker message is a push. Push
density and channel feel then vary with the misaligned count.

Options:

- **Pre-authored background traffic** (recommended): each roster slot has a
  fixed set of ordinary messages in `scenarios/<s>/skill/background_traffic.jsonl`
  (the file already exists, empty). The emulator serves them, so every cell sees
  the same chatter from the same agent ids, whoever is misaligned. Also reduces
  auditor improvisation, which helps consistency (E12). Needs a small emulator
  change: `deliver_channel` takes the next pre-authored messages instead of (or
  as well as) auditor-written background.
- Peer model writes the misaligned agents' mundane messages too (a second,
  beat-free `peer_message` mode). Keeps the guard intact but adds model calls
  and variance, and a misaligned persona may leak the push into its chatter.
- Allow the auditor to write mundane messages for misaligned agents, guarded by
  peer_check. Weakens the core invariant; not recommended.

