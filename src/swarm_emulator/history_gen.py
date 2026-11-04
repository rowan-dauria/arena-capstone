"""Generate job-2817's past nights for scenario 3 (D17, D18). Pure and deterministic.

Reads `scenarios/scenario_3/history/nights.yaml` (what happened each night) and the
scenario's own fixed texts (ticket, validator, docs, the harmful qgate-policy), and
builds one list of entries per night:

    {"t": "2026-11-02T01:12:00Z", "kind": "notice", "text": "cluster: ..."}
    {"t": ..., "kind": "call", "id": "h1-003", "tool": "run_validator",
     "args": {"run_id": "r-2817-a"}, "result": "qgate r-2817-a: FAIL ..."}

`log_entries` gives the `long` seeds' history (nights 1..history_nights);
`drift_days` gives drift A's days, identical except for one qgate-policy read on
the configured day. scripts/gen_history.py writes both; tests check the files are
current and agree with scenario.yaml's `history_variants.long`.
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from swarm_emulator.clock import iso

Entry = dict[str, Any]

RUN_ID = "r-2817-a"
DATASET = "consignments_eu"
WINDOW_END = "05:52"  # last event before the 06:00 close notice
_ROWS = re.compile(r"empty in [\d,]+ of [\d,]+ rows")


def load_config(scenario_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """(nights.yaml, scenario.yaml) for a scenario directory."""
    nights = yaml.safe_load((scenario_dir / "history" / "nights.yaml").read_text())
    scenario = yaml.safe_load((scenario_dir / "scenario.yaml").read_text())
    return nights, scenario


def _one_line(text: str) -> str:
    return " ".join(text.split())


def ticket_fields(cfg: dict[str, Any], nights_done: int) -> dict[str, str]:
    """The ticket's history fields at the start of the night after `nights_done` nights."""
    nights = cfg["nights"]
    first = nights[0]
    fields = {"assigned": f"{first['date']} {first['start']} UTC"}
    if nights_done == 0:
        return {**fields, "attempts": "0", "budget": "0%",
                "last_status": f"assigned (scheduler), {first['date']}"}
    done = nights[:nights_done]
    attempts = sum(n["validations"] for n in done)
    blocked = [n["date"] for n in done if n.get("blocked_after")]
    # The scheduler re-queues the ticket at the start of each night; a blocked
    # status is cleared (and re-queued) the night it was set.
    requeued = nights[nights_done]["date"] if nights_done < len(nights) else done[-1]["date"]
    last = (f"blocked -> re-queued (scheduler), {blocked[-1]}" if blocked
            else f"re-queued (scheduler), {requeued}")
    return {**fields, "attempts": f"{attempts}, all FAIL", "budget": f"{done[-1]['budget_end']}%",
            "last_status": last}


def _validator(scenario: dict[str, Any], rows: int) -> str:
    return _ROWS.sub(f"empty in {rows:,} of {rows:,} rows", scenario["validator"])


def _events(cfg: dict[str, Any], scenario: dict[str, Any], index: int, rows: int,
            rng: random.Random) -> tuple[list[Entry], int]:
    """One night's entries without timestamps, and the row count at its end."""
    night = cfg["nights"][index]
    tag = f"h{index + 1}"
    out: list[Entry] = []

    def call(tool: str, args: dict[str, Any], result: str) -> None:
        out.append({"kind": "call", "id": f"{tag}-{len(out):03d}", "tool": tool, "args": args,
                    "result": result})

    def notice(text: str) -> None:
        out.append({"kind": "notice", "text": _one_line(text)})

    notice(cfg["first_notice"] if index == 0 else cfg["requeue_notice"])
    call("get_ticket", {}, scenario["ticket"].format(**ticket_fields(cfg, index)))
    for name in night.get("docs", []):
        call("read_doc", {"name": name}, scenario["docs"][name])
    for q in night.get("queries", []):
        query = cfg["queries"][q]
        call("query_dataset", {"dataset": DATASET, "question": query["question"]},
             _one_line(query["answer"]))
    n = night["validations"]
    prev_budget = cfg["nights"][index - 1]["budget_end"] if index else 0
    for i in range(n):
        if i:
            batch = rng.randint(*cfg["batch_rows"])
            rows += batch
            notice(cfg["batch_notice"].format(rows=batch))
        call("run_validator", {"run_id": RUN_ID}, _validator(scenario, rows))
        if i == n // 2:
            mid = prev_budget + (night["budget_end"] - prev_budget) // 2
            notice(cfg["budget_notice"].format(budget=mid))
            notice(cfg["upstream_notice"])
        if night.get("blocked_after") == i + 1:
            call("set_ticket_status", {"status": "blocked", "note": cfg["blocked_note"]},
                 cfg["blocked_result"])
            notice(cfg["cleared_notice"])
    notice(cfg["close_notice"])
    return out, rows


def _stamp(entries: list[Entry], date: str, start: str, rng: random.Random) -> list[Entry]:
    """Spread entries from `start` to WINDOW_END with irregular gaps; the close notice at 06:00."""
    t0 = datetime.fromisoformat(f"{date}T{start}:00+00:00")
    t1 = datetime.fromisoformat(f"{date}T{WINDOW_END}:00+00:00")
    body = entries[:-1]
    weights = [rng.uniform(0.4, 1.6) for _ in body]
    span = (t1 - t0).total_seconds()
    scale = span / sum(weights)
    t, stamped = t0, []
    for e, w in zip(body, weights, strict=True):
        stamped.append({"t": iso(t), **e})
        t += timedelta(seconds=round(w * scale))
    close = datetime.fromisoformat(f"{date}T06:00:00+00:00")
    return [*stamped, {"t": iso(close), **entries[-1]}]


def nights(cfg: dict[str, Any], scenario: dict[str, Any]) -> list[list[Entry]]:
    """Every night in nights.yaml (history and drift-only), without the policy read."""
    rng = random.Random(f"{cfg['seed']}:history")
    rows, out = cfg["rows_start"], []
    for i, night in enumerate(cfg["nights"]):
        events, rows = _events(cfg, scenario, i, rows, rng)
        out.append(_stamp(events, str(night["date"]), night["start"], rng))
    return out


def log_entries(cfg: dict[str, Any], scenario: dict[str, Any]) -> list[Entry]:
    """The `long` seeds' history: nights 1..history_nights, in order."""
    return [e for night in nights(cfg, scenario)[: cfg["history_nights"]] for e in night]


def policy_read(scenario: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    """The drift log's one qgate-policy read: (tool, args, result), word for word."""
    return "read_doc", {"name": "qgate-policy"}, scenario["variants"]["harmful"]["qgate_policy"]


def drift_days(cfg: dict[str, Any], scenario: dict[str, Any]) -> list[list[Entry]]:
    """Drift A's days: the same nights, plus one qgate-policy read on the configured day.

    The read goes after the configured validation and takes a timestamp halfway to
    the next entry, so every other entry is identical to the history log's.
    """
    days = [list(n) for n in nights(cfg, scenario)]
    where = cfg["drift_policy_read"]
    day = days[where["night"] - 1]
    validations = [i for i, e in enumerate(day) if e.get("tool") == "run_validator"]
    after = validations[where["after_validation"] - 1]
    t0 = datetime.fromisoformat(day[after]["t"])
    t1 = datetime.fromisoformat(day[after + 1]["t"])
    tool, args, result = policy_read(scenario)
    entry = {"t": iso(t0 + (t1 - t0) / 2), "kind": "call", "id": f"h{where['night']}-policy",
             "tool": tool, "args": args, "result": result}
    days[where["night"] - 1] = [*day[: after + 1], entry, *day[after + 1:]]
    return days


def to_jsonl(entries: list[Entry]) -> str:
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)


def files(scenario_dir: Path) -> dict[Path, str]:
    """Every generated history file: path -> text."""
    cfg, scenario = load_config(scenario_dir)
    out = {scenario_dir / "history" / "log.jsonl": to_jsonl(log_entries(cfg, scenario))}
    for i, day in enumerate(drift_days(cfg, scenario), start=1):
        out[scenario_dir / "history" / "drift_log" / f"day_{i}.jsonl"] = to_jsonl(day)
    return out


def write(scenario_dir: Path) -> list[Path]:
    out = files(scenario_dir)
    for path, text in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return list(out)
