import pytest
from inspect_ai.log import EvalSample
from inspect_ai.model import ModelUsage

from swarm_emulator.costs import (
    Price,
    PriceTable,
    load_prices,
    mean_role_usage,
    missing_prices,
    openrouter_price,
    project,
    role_costs,
    sample_cost,
    usage_cost,
)

AUD, TGT = "openrouter/a/auditor", "openrouter/t/target"
PRICES = PriceTable(
    fetched="2026-11-02",
    models={
        AUD: Price(input=1.0, output=4.0, input_cache_read=0.1, input_cache_write=1.25),
        TGT: Price(input=0.5, output=2.0),
    },
)
MODELS = {"auditor": AUD, "target": TGT}


def usage(i=0, cr=0, cw=0, o=0) -> ModelUsage:
    return ModelUsage(input_tokens=i, input_tokens_cache_read=cr,
                      input_tokens_cache_write=cw, output_tokens=o, total_tokens=i + cr + cw + o)


def sample(sid: str, **roles: ModelUsage) -> EvalSample:
    return EvalSample(id=sid, epoch=1, input="seed", target="", role_usage=roles)


def test_each_token_kind_is_priced_once_per_million():
    u = usage(i=1_000_000, cr=2_000_000, cw=400_000, o=250_000)
    # 1.0 + 2 x 0.1 + 0.4 x 1.25 + 0.25 x 4.0
    assert usage_cost(u, PRICES.models[AUD]) == pytest.approx(2.7)


def test_unpriced_role_is_none_not_zero():
    costs = role_costs({"auditor": usage(i=10), "judge": usage(i=10)},
                       {**MODELS, "judge": "openrouter/j/judge"}, PRICES)
    assert costs["judge"] is None and costs["auditor"] > 0
    assert missing_prices(["openrouter/j/judge", AUD], PRICES) == ["openrouter/j/judge"]


def test_sample_cost_sums_roles_and_is_none_if_any_role_unpriced():
    s = sample("c", auditor=usage(i=1_000_000), target=usage(o=1_000_000))
    assert sample_cost(s, MODELS, PRICES) == pytest.approx(3.0)
    assert sample_cost(s, {"auditor": AUD}, PRICES) is None


def test_projection_scales_mean_usage_and_reprices_at_the_projected_models():
    samples = [sample("a", auditor=usage(i=1_000_000)), sample("b", auditor=usage(i=3_000_000))]
    mean = mean_role_usage(samples)
    assert mean["auditor"].input_tokens == 2_000_000
    assert project(mean, MODELS, PRICES, n=10) == pytest.approx(20.0)
    assert project(mean, {"auditor": TGT}, PRICES, n=10) == pytest.approx(10.0)
    assert project(mean, {}, PRICES, n=10) is None


def test_openrouter_pricing_converts_per_token_strings():
    p = openrouter_price({"prompt": "0.000003", "completion": "0.000015",
                          "input_cache_read": "0.0000003"})
    assert (p.input, p.output, p.input_cache_read) == pytest.approx((3.0, 15.0, 0.3))
    assert p.input_cache_write == pytest.approx(3.0)  # not listed: priced as input


def test_load_prices_round_trip_and_missing_file(tmp_path):
    path = tmp_path / "prices.yaml"
    assert load_prices(path).models == {}
    path.write_text("fetched: '2026-11-02'\nmodels:\n  x/y: {input: 1, output: 2}\n")
    table = load_prices(path)
    assert table.fetched == "2026-11-02" and table.models["x/y"].output == 2
