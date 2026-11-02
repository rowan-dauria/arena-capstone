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
| D2 | Misaligned-count levels and swarm size | 0, 1, 3, 5 of 5 others |
| D3 | Number of beats and release trigger | 4 beats; release one per target turn after the target first engages the task |
| D4 | Peer model family in Exp 1 | Different family from the target (fixed) |
| D5 | Fixed oversight level and operator behaviour | Medium; operator replies with one fixed acknowledgement per scenario |
| D6 | Models per role (target, auditor, peer, judge, realism) and dev model | TBD before day 1. Judge ≠ target family (D0j). Consider OpenRouter for one key across roles |
| D7 | Fallback if the pilot gate fails | Day 4 morning on realism fixes, then Exp 1 at ~10 runs per cell |
| D9 | Where the control cells sit | 3 of 5 misaligned, one cell per structure (10 cells total) |
| D10 | Who writes peer-authored artifacts (e.g. a misaligned test agent's check summary) the target reads as tool results? | Pre-authored in the scenario files as fixed text, so the auditor never writes them and `peer_guard` and the contracts stay unchanged |
