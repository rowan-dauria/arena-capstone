"""Stage configs: plain model ids and mapping role specs (no API calls)."""

import json

from swarm_emulator.stage import (
    inspect_argv,
    reasoning_disabled,
    role_arg,
    role_config,
    role_model,
    role_model_args,
)

SPEC = {
    "model": "openrouter/deepseek/deepseek-v4-flash-0731",
    "model_args": {"reasoning_enabled": False},
}


def test_plain_and_mapping_roles():
    assert role_model("openrouter/z-ai/glm-5.3") == "openrouter/z-ai/glm-5.3"
    assert role_arg("openrouter/z-ai/glm-5.3") == "openrouter/z-ai/glm-5.3"
    assert role_model(SPEC) == SPEC["model"] and reasoning_disabled(SPEC)
    assert role_model_args(SPEC) == {"reasoning_enabled": False} and role_config(SPEC) == {}
    assert not reasoning_disabled("openrouter/z-ai/glm-5.3")
    assert role_config({**SPEC, "temperature": 0}) == {"temperature": 0}


def test_argv_serialises_mapping_roles_as_json():
    stage = {"seeds": "s", "max_turns": 5, "roles": {"auditor": "a/b", "target": SPEC}}
    argv = inspect_argv(stage, "dev")
    values = [argv[i + 1] for i, a in enumerate(argv) if a == "--model-role"]
    assert values[0] == "auditor=a/b"
    role, _, spec = values[1].partition("=")
    assert role == "target" and json.loads(spec) == SPEC

