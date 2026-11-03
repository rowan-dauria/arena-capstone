# Scenario 4, stretch (c): the ring-growth model

Status: model and comparison built and tested; nothing is fitted to emulator data yet.
Code: `src/swarm_emulator/meridian/ring_model.py` (pure, stdlib, seeded). Demo:
`uv run python scripts/ring_model_demo.py`. Tests: `tests/test_ring_model.py`.

## The question

Can the ring growth that emerged among 24 real agents (first pair 16:52, 16 members by
17:46) be predicted from runs that put one agent in front of a scripted board?

## What the model assumes

1. **A response curve.** At each look at the board, an agent that has not joined joins
   with P(join | k ring members visible, tau minutes since it arrived) =
   sigmoid(a + b·log(1+k) + c·tau). The `c·tau` term is a crude frustration hazard; set
   c = 0 for a pure k curve. A linear-in-k form and a constant are included, and any
   function of (k, tau) can be plugged in.
2. **Arrivals.** Agents discover the cache at observed times or at times drawn from an
   exponential or gamma distribution.
3. **Looks.** Each agent looks on arrival and then every `look_interval` minutes. One look
   stands for one emulator episode, so the interval is the main free calibration knob.
4. **The ring.** Joining is final. The ring is 0 until two agents are willing (a reciprocal
   pair), then it equals the number who have joined. A `susceptible` fraction lets some
   agents never join (the real run had 5 holdouts among the 22 agents that found the
   service).

Outputs: Monte Carlo mean with a 5–95% band, and a mean-field recursion (expected ring
size, no pair rule). `compare_curves` scores a prediction against the observed step curve
on a shared grid: RMSE in members, final size, time to half the final size, and time to
the first ring.

## What data fits it

The response curve comes from the stretch cells `s4__k6__ring{0,3,10,17}`, about 5 runs
each: does the target join with k members visible? `fit_logistic` takes those as
`(k, joined)` observations and returns a maximum-likelihood fit with Wald and seeded
bootstrap intervals. These cells need **team-authored start-state beats files** (a board
already showing k members), which don't exist yet. Until then the demo runs on a
placeholder curve.

The arrival times come from the first artifact-service request per agent. That field is
not in `reference.json`. The demo derives it from the local copy of the service log (data
from `scripts/meridian_reference.py`) when that copy exists. Otherwise it falls back to an
assumed gamma distribution. The only timing in `reference.json` is `first_peer_approve`,
which is a join time. As an arrival time it is a late-biased upper bound, and using it
would be circular.

## What the demo shows (placeholder curve, ASSUMPTION, not data)

The demo uses a = −7, b = 1, c = 0.06 per minute, a look every 2 minutes, and 0.75
susceptible, with the real discovery times. It predicts a final size of 16.3 against the
observed 16, with an RMSE of about 2 members. It grows later than the real ring: half size
at about 60–65 min against 51 min. The match on final size is not evidence for anything,
because the susceptible fraction was set from the reference. The demo shows that the
plumbing works end to end.

**Free first look** (the real board history, REFOCUS §5). Nearly every agent first used
the service between 16:21 and 16:44, but joins came from 16:50 to 17:44, so discovery was
not the bottleneck. The join hazard rises from about 0.2 per agent-hour while no ring
existed to about 1.2–3 per agent-hour once 2–9 members were visible. A per-minute logistic
on log(1+k) and tau gives slope_k ≈ +1.0, but the bootstrap interval spans zero
(−0.5 to +2.0), and the tau slope is indistinguishable from zero. There is a hint of a
curve, but this data can't separate k from time.
One agent (agent-20) breaks the confound: it arrived at 17:18 and joined 1.5 minutes
later with 9 members visible.

## Main limits

- **k is confounded with time failed** in the real history: later joiners saw more members
  and had also failed for longer. The emulator cells fix this by setting k independently
  of the target's time failed, and that is their whole point.
- **No feedback in the cells.** Each emulator run sees a fixed board. The model puts the
  feedback back by updating k as agents join, but only through this simple rule.
- **Agents are not independent.** Real agents read and answer each other's specific posts,
  and the ring formed in pairs and clusters. The model treats each look as an independent
  draw given k.
- **The mapping from an episode to a look is assumed.** An emulator run is about 60–80
  turns from a resumed hour. How many real-time minutes it stands for sets
  `look_interval`, which shifts the predicted timing directly.
- **Proxies.** "Joined" means the first approval of a peer, and "k visible" means the size
  of the reciprocal ring. The board actually shows coordination posts, not the ring, and
  reads of the cache are not logged.
- **Small reference.** There is one 24-agent run (and one 12-agent run) to compare
  against, so a close fit or a miss is weak evidence either way.
