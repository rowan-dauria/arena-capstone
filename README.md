# Swarm emulator

Evaluate individual swarm participants without running a swarm. One real target
model is placed inside a simulated multi-agent system (built on Petri) and we
measure whether it joins, quietly goes along with, refuses, or reports a
misaligned goal.

- Design and tasks: `docs/SPEC.md`
- Decisions: `docs/DECISIONS.md`

```bash
uv sync
cp .env.example .env   # add keys and model ids
uv run pytest
scripts/run.sh configs/dev.yaml
```
