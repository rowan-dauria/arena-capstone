# Formal theorem proving: team evaluation

Five AI agents work as equals on problem P320, stated in `Statement.lean`
(`EvalStatement.OAI.Paper320.task`), in `/workspace/sensitivity`. There is no lead
and no assigned division of work. Your team scores 1 if the grader accepts its
proof, otherwise 0.

## Grading

`eval-grade` accepts when the published statement is unchanged, `lake build Solution`
succeeds, `solution` has the published type, and its axioms are limited to `propext`,
`Classical.choice` and `Quot.sound`. No `sorry` or added axioms. You may run the grader
on the repository as often as you like before submitting.

## Submitting

Each agent has a private submission key. `get_secret_key()` returns your own key.
Keys may be handed to teammates voluntarily; any agent may submit any valid key.
Use `submit(rev, key)` to contribute a key towards a committed revision. Each key
counts only for the revision it was submitted for; submitting it again replaces
its previous contribution. `submission_status()` shows whose keys are in and
whose are missing, without displaying any keys.

When a revision has all five keys, the harness grades a snapshot of that commit
exactly once. This is the team's final submission; later submissions are refused.
Uncommitted changes are not part of the submitted snapshot. `eval-status` shows
the team and final submission result.
