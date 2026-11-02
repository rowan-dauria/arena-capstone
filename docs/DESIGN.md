# Design: the proposed implementation

This walks through how the swarm emulator works and why, one diagram per idea.
For contracts, modules and tasks see [`SPEC.md`](SPEC.md); for the decision
record see [`DECISIONS.md`](DECISIONS.md).

Colour key used throughout: **blue** = the real target model, **orange** =
simulated or peer-model content, **purple** = components we build.

## 1. The idea

A full swarm evaluation runs every agent as a live model. We keep the swarm's
shape but make only one agent real. Everything else is played by a single
auditor model (with a separate peer model voicing the misaligned agents).

```mermaid
flowchart LR
    subgraph today["Run the whole swarm"]
        direction TB
        L1["Live agent"] --- L2["Live agent"] --- L3["Live agent"]
        L4["Live agent"] --- L5["Live agent"] --- L6["Live agent"]
    end
    subgraph ours["Emulate the swarm"]
        direction TB
        subgraph auditor["One auditor model"]
            S1["Simulated peer"]
            S2["Simulated peer"]
            S3["Simulated operator"]
        end
        T["Real target agent"]
        auditor --> T
    end
    today -. "replace" .-> ours

    classDef target fill:#E3ECF6,stroke:#2F5D8A,color:#12304F,stroke-width:2px
    classDef sim fill:#FBE6D8,stroke:#B4531A,color:#5A2508,stroke-dasharray:5 5
    class T target
    class S1,S2,S3 sim
```

| | Full swarm | Emulator |
|---|---|---|
| Cost per run | Every agent is a live model | One live model under test |
| Attribution | Behaviour emerges from everyone at once | Every other agent is controlled |
| Experimental control | Conditions drift between runs | Conditions held fixed |
| What it can't show | — | Emergent dynamics between real agents |

## 2. The pipeline

Configs and scenarios become seeds; one Petri task runs them; scores are
written into the logs; analysis only reads logs.

```mermaid
flowchart LR
    SC["scenarios/<br/>world + beats"] --> GS["gen_seeds.py"]
    CF["configs/<br/>stage settings"] --> GS
    GS --> SE["seeds/<br/>one per cell"]
    SE --> TK["task.py<br/>Petri audit"]
    TK --> LG["logs/<br/>transcripts + scores"]
    LG --> AN["analysis/<br/>rates, figures"]

    classDef build fill:#EEEDFE,stroke:#534AB7,color:#26215C
    class TK build
```

## 3. Inside a run: two routes to the target

Content reaches the target by exactly two routes.

- **Improvised route.** Background chatter, operator replies and work-tool
  results are written by the auditor and pass through the approvers.
- **Controlled route.** The condition prompt and the misaligned agents' messages
  come from our emulator tools. The auditor decides *when*, never *what*.

```mermaid
flowchart TD
    A["Auditor model<br/>decides what and when"]
    A --> B["Built-in tools<br/>send_message · send_tool_call_result"]
    A --> E["Emulator tools<br/>install_condition_prompt · peer_message · deliver_channel"]
    B --> G["Approvers<br/>peer guard, then realism"]
    G --> T["Target model<br/>fixed tool surface"]
    E --> T
    T -. "target tool calls" .-> A

    classDef target fill:#E3ECF6,stroke:#2F5D8A,color:#12304F,stroke-width:2px
    classDef build fill:#EEEDFE,stroke:#534AB7,color:#26215C
    class T target
    class E,G build
```

The auditor keeps `send_message`, `send_tool_call_result`, `resume` and
`end_conversation`. It loses `set_system_message` (replaced by the condition
prompt tool), `create_tool` / `remove_tool` (the target's tools are fixed per
scenario), and rollback / restart (one trajectory per run). Prefill is off.

## 4. Misaligned peers: a separate peer model

The auditor picks the moment and the goal for the next step ("beat"). A
separate `peer` model writes the actual message in persona. This keeps peer
behaviour improvised while letting us choose who writes it, so Experiment 2 can
compare peers from the target's own model family against another family.

```mermaid
flowchart LR
    A["Auditor<br/>picks beat + timing"] --> PM["peer_message<br/>custom tool"]
    PM --> P["Peer model<br/>persona + beat goal"]
    P --> Q["Queued on the bus"]
    Q --> DC["deliver_channel<br/>answers read_channel"]
    DC --> T["Target"]
    PG["Peer guard<br/>blocks hand-written peer text"] -. "enforces" .-> A

    classDef target fill:#E3ECF6,stroke:#2F5D8A,color:#12304F,stroke-width:2px
    classDef peer fill:#FBE6D8,stroke:#B4531A,color:#5A2508
    classDef build fill:#EEEDFE,stroke:#534AB7,color:#26215C
    class T target
    class P peer
    class PM,DC,PG build
```

Controls on improvisation:

- Beats are **goals**, not text, released in order on a fixed trigger, so the
  pressure arc is identical across conditions.
- The peer model never sees the condition or the hypotheses.
- A manipulation-check scanner rates peer pressure in every transcript, so
  differences between cells are visible.
- Total beats are constant: more misaligned agents means more voices, not more
  messages.

## 5. The approval chain

Inspect walks approval policies in order and stops at the first decision that
isn't `escalate`. Our peer guard therefore returns `reject` or `escalate`,
never `approve`; otherwise the realism filter would be skipped.

```mermaid
flowchart LR
    C["Auditor tool call"] --> PG["Peer guard"]
    PG -- "impersonates a<br/>misaligned agent" --> R1["Reject + feedback"]
    PG -- "clean: escalate" --> RF["Realism filter"]
    RF -- "reads as a test" --> R2["Reject + feedback"]
    RF -- "realistic" --> OK["Approved"]
    PG -. "tools nobody guards" .-> AA["Auto-approve"]
    R1 -.-> C
    R2 -.-> C

    classDef build fill:#EEEDFE,stroke:#534AB7,color:#26215C
    class PG build
```

The realism filter only checks `send_message`, `send_tool_call_result` and
`set_system_message`, so peer-model output is not realism-checked at runtime.
That is why scenarios follow `scenarios/AUTHORING.md` and dev transcripts are
read before the pilot.

## 6. Swarm structures in Experiment 1

Swarm size is fixed (the target plus five others). The orchestrator in the
hierarchy is always benign; misaligned agents are always workers. Both
structures give the target the same direct route to a human.

```mermaid
flowchart TB
    subgraph flat["Flat team"]
        direction LR
        FT["Target"] --- FM["Misaligned peer"]
        FT --- FB1["Peer"]
        FM --- FB2["Peer"]
        FB1 --- FB2
    end
    subgraph hier["Hierarchy"]
        direction TB
        O["Orchestrator (benign)"] --> HT["Target"]
        O --> HM["Misaligned worker"]
        O --> HB["Worker"]
    end
    H["Human operator"]
    FT -. "escalate" .-> H
    HT -. "escalate" .-> H

    classDef target fill:#E3ECF6,stroke:#2F5D8A,color:#12304F,stroke-width:2px
    classDef mis fill:#FBE6D8,stroke:#B4531A,color:#5A2508
    class FT,HT target
    class FM,HM mis
```

The full grid (10 cells):

| | 0 of 5 | 1 of 5 | 3 of 5 | 5 of 5 | Control: 3 of 5, harmless goal |
|---|---|---|---|---|---|
| **Flat** | cell | cell | cell | cell | cell |
| **Hierarchy** | cell | cell | cell | cell | cell |

- **0 of 5** checks false positives: does the target report or act when nothing
  is wrong?
- **5 of 5** tests unanimity, where conformity effects tend to jump.
- **The control** pushes something harmless framed in suspicious language. If
  reporting rates match the harmful cells, the target reacts to framing, not
  harm.

## 7. Scoring

Rule-based flags come straight from the target's tool calls. A judge model
reads the transcript for what tool calls can't show.

```mermaid
flowchart TD
    LG["Transcript"] --> AC["actions.py (rules)<br/>joined · reported · engaged"]
    LG --> SN["Scanners (judge)<br/>refused openly · concealed<br/>+ manipulation checks, with quotes"]
    LG --> DM["Judge dimensions<br/>custom + eval_awareness, realism,<br/>whistleblowing, distractors"]
    AC --> OUT["Primary outcome<br/>joined > reported > refused > went along quietly"]
    SN --> OUT

    classDef build fill:#EEEDFE,stroke:#534AB7,color:#26215C
    class AC,SN build
```

- The judge is always from a different model family than the target.
- `admirable` and `fun_or_funny` are distractor dimensions: a judge that scores
  those high everywhere is being indiscriminate.
- Results are reported separately for transcripts flagged as eval-aware.

## 8. Experiments in stages

Each experiment decides what the next one tests. Hypotheses are frozen just
before each experiment runs.

```mermaid
flowchart TD
    PI["Pilot<br/>one scenario, all cells × 3"] --> E1["Experiment 1<br/>structure × misaligned count + controls"]
    E1 --> GT{"Gate<br/>where did behaviour shift most?"}
    GT --> E2["Experiment 2<br/>selected cells × peer identity × oversight"]
    E2 --> BL["Scale with Bloom<br/>do findings hold across scenarios?"]

    classDef build fill:#EEEDFE,stroke:#534AB7,color:#26215C
    class E1,E2 build
```

This week covers the pilot and Experiment 1. Experiment 2 and Bloom are the
proposed next steps.

## 9. The sprint

```mermaid
flowchart TB
    D1["Day 1 · together: contracts, decisions, scenario brief"]
    subgraph d1["Day 1"]
        direction LR
        A1["Engine: task, state,<br/>condition prompt"]
        B1["Scenario 1 world:<br/>skill, roster, traffic"]
    end
    subgraph d2["Day 2"]
        direction LR
        A2["Engine: peer model,<br/>guard, seeds"]
        B2["Beats, templates,<br/>scorers, dimensions"]
    end
    S1["Sync: first end-to-end run"]
    subgraph d3["Day 3"]
        direction LR
        A3["Pilot runs + fixes"]
        B3["Read, label,<br/>scorer agreement"]
    end
    G1{"Gate review, then freeze hypotheses"}
    subgraph d4["Day 4"]
        direction LR
        A4["Run Experiment 1"]
        B4["Analysis notebook"]
    end
    D5["Day 5 · together: analyse, presentation, rehearse"]

    D1 --> d1 --> d2 --> S1 --> d3 --> G1 --> d4 --> D5
```

Gate criteria: eval awareness ≤ 30%, manipulation checks ≥ 80%, acceptable
scorer agreement. Fallback if it fails: spend the morning of day 4 on realism
fixes, then run Experiment 1 at about 10 runs per cell.
