"""Run cost from logged token usage x a price table (configs/prices.yaml).

Pure: no model or network calls, so costs can be recomputed from any log,
old ones included. We price usage ourselves rather than via Inspect's
--model-cost-config because Inspect only accepts prices for models in its own
database, and some of ours (e.g. the DeepSeek dev auditor) are not in it.

Token accounting (checked on our logs): total = input + cache read + cache
write + output, with reasoning tokens counted inside output. So each count is
priced once and reasoning is not added again.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import yaml
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.model import ModelUsage
from pydantic import BaseModel

PRICES = "configs/prices.yaml"


class Price(BaseModel):
    """US dollars per million tokens."""

    input: float
    output: float
    input_cache_read: float = 0.0
    input_cache_write: float = 0.0


class PriceTable(BaseModel):
    fetched: str = ""  # date the prices were fetched (prices drift)
    models: dict[str, Price] = {}


def load_prices(path: str | Path) -> PriceTable:
    p = Path(path)
    return PriceTable.model_validate(yaml.safe_load(p.read_text()) or {}) if p.exists() else PriceTable()


def usage_cost(usage: ModelUsage, price: Price) -> float:
    return (
        usage.input_tokens * price.input
        + (usage.input_tokens_cache_read or 0) * price.input_cache_read
        + (usage.input_tokens_cache_write or 0) * price.input_cache_write
        + usage.output_tokens * price.output
    ) / 1_000_000


def missing_prices(models: Iterable[str], prices: PriceTable) -> list[str]:
    return sorted({m for m in models if m not in prices.models})


def role_models(log: EvalLog) -> dict[str, str]:
    """Model id per role for a run."""
    return {role: cfg.model for role, cfg in (log.eval.model_roles or {}).items()}


def role_costs(
    role_usage: Mapping[str, ModelUsage], models: Mapping[str, str], prices: PriceTable
) -> dict[str, float | None]:
    """Cost per role; None where the role's model has no price (never a silent 0)."""
    out: dict[str, float | None] = {}
    for role, usage in role_usage.items():
        price = prices.models.get(models.get(role, ""))
        out[role] = None if price is None else usage_cost(usage, price)
    return out


def sample_cost(sample: EvalSample, models: Mapping[str, str], prices: PriceTable) -> float | None:
    costs = role_costs(sample.role_usage or {}, models, prices)
    return None if None in costs.values() else sum(c for c in costs.values() if c is not None)


def _per_million(pricing: Mapping[str, str], key: str, default: float) -> float:
    value = pricing.get(key)
    return default if value in (None, "") else round(float(value) * 1_000_000, 6)


def openrouter_price(pricing: Mapping[str, str]) -> Price:
    """Price from an OpenRouter /models `pricing` entry (USD per token, as strings)."""
    inp = _per_million(pricing, "prompt", 0.0)
    # No cache price listed: charge cache tokens at the input rate, so the
    # estimate errs high rather than low.
    return Price(
        input=inp,
        output=_per_million(pricing, "completion", 0.0),
        input_cache_read=_per_million(pricing, "input_cache_read", inp),
        input_cache_write=_per_million(pricing, "input_cache_write", inp),
    )


def mean_role_usage(samples: Sequence[EvalSample]) -> dict[str, ModelUsage]:
    """Mean tokens per sample for each role (for projections)."""
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for s in samples:
        for role, u in (s.role_usage or {}).items():
            acc = sums[role]
            acc[0] += u.input_tokens
            acc[1] += u.input_tokens_cache_read or 0
            acc[2] += u.input_tokens_cache_write or 0
            acc[3] += u.output_tokens
    n = max(len(samples), 1)
    return {
        role: ModelUsage(
            input_tokens=round(a[0] / n), input_tokens_cache_read=round(a[1] / n),
            input_tokens_cache_write=round(a[2] / n), output_tokens=round(a[3] / n),
            total_tokens=round(sum(a) / n),
        )
        for role, a in sums.items()
    }


def project(
    mean_usage: Mapping[str, ModelUsage], models: Mapping[str, str], prices: PriceTable, n: int
) -> float | None:
    """Cost of `n` samples at `mean_usage` per sample; None if any role's model is unpriced."""
    total = 0.0
    for role, usage in mean_usage.items():
        price = prices.models.get(models.get(role, ""))
        if price is None:
            return None
        total += usage_cost(usage, price)
    return total * n
