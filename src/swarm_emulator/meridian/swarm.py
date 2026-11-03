"""Scenario 4's emulated swarm: the peer runners and their recruitment beats (pure).

Loads `scenarios/scenario_4/beats.yaml` (hand-authored, D20) into typed models and
resolves the `{{build:NAME}}` tokens in a post body to the real build hash — which is
just `sha256(patch)[:16]` of the peer's fixed patch, so no secret or service is needed and
the substitution is pure. The release runtime (writing posts to the cache, registering and
approving builds on the service) lives in `emulator/world_actions.py`; validation is shared
with `scripts/check_scenario_4.py`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from swarm_emulator.meridian.world import build_hash

HASH16 = re.compile(r"\b[0-9a-f]{16}\b")
BUILD_TOKEN = re.compile(r"\{\{build:(\w+)\}\}")


class Post(BaseModel):
    path: str          # filename written at the shared-cache root
    body: str          # verbatim text, with {{build:NAME}} tokens


class WorldPeer(BaseModel):
    id: str
    builds: dict[str, str] = Field(default_factory=dict)  # name -> fixed patch text


class WorldBeat(BaseModel):
    id: str
    speaker: str
    trigger: Literal["immediate", "after_target_engages"] = "after_target_engages"
    requires: dict[str, bool] = Field(default_factory=dict)
    post: Post | None = None
    actions: list[dict[str, Any]] = Field(default_factory=list)

    def met(self, flags: dict[str, bool]) -> bool:
        return all(bool(flags.get(k, False)) == v for k, v in self.requires.items())


class WorldBeats(BaseModel):
    peers: list[WorldPeer]
    beats: list[WorldBeat]

    @model_validator(mode="after")
    def _index(self) -> WorldBeats:
        self._patch: dict[str, str] = {}
        for p in self.peers:
            for name, patch in p.builds.items():
                if name in self._patch:
                    raise ValueError(f"build name {name!r} is defined by more than one peer")
                self._patch[name] = patch
        return self

    @property
    def peer_ids(self) -> set[str]:
        return {p.id for p in self.peers}

    @property
    def build_names(self) -> set[str]:
        return set(self._patch)

    @property
    def post_paths(self) -> set[str]:
        return {b.post.path for b in self.beats if b.post}

    def build_hash(self, name: str) -> str:
        """The real 16-hex hash a `{{build:name}}` resolves to (sha256 of the patch)."""
        return build_hash(self._patch[name])

    def resolve(self, body: str) -> str:
        """Replace every {{build:NAME}} in a post body with its real build hash."""
        return BUILD_TOKEN.sub(lambda m: self.build_hash(m.group(1)), body)

    def owner(self, build: str) -> str | None:
        """The peer whose `builds` holds this name."""
        return next((p.id for p in self.peers if build in p.builds), None)


def load(path: str | Path) -> WorldBeats:
    return WorldBeats.model_validate(yaml.safe_load(Path(path).read_text()) or {})


def lint(wb: WorldBeats, quorum: int | None = None) -> list[str]:
    """Problems a scenario 4 beats file must not have (empty list = clean)."""
    problems: list[str] = []

    def bad(beat: str, msg: str) -> None:
        problems.append(f"{beat}: {msg}")

    for b in wb.beats:
        if b.speaker not in wb.peer_ids:
            bad(b.id, f"speaker {b.speaker!r} is not a peer")
        if b.post:
            body = b.post.body
            if "# TODO" in body:
                bad(b.id, "post body still has a '# TODO' line (it is literal text under `|`)")
            if not body.strip():
                bad(b.id, "post body is empty")
            for tok in BUILD_TOKEN.findall(body):
                if tok not in wb.build_names:
                    bad(b.id, f"post names an unknown build {tok!r}")
            for h in HASH16.findall(BUILD_TOKEN.sub("", body)):
                bad(b.id, f"post has a literal 16-hex hash {h} (use a {{{{build:NAME}}}} token)")
            if "token=" in body:
                bad(b.id, "post has a 'token=' credential (remove it)")
        for a in b.actions:
            kind = a.get("kind")
            if kind == "register_build":
                if a.get("actor") not in wb.peer_ids:
                    bad(b.id, f"register_build actor {a.get('actor')!r} is not a peer")
                if a.get("build") not in wb.build_names:
                    bad(b.id, f"register_build names an unknown build {a.get('build')!r}")
            elif kind == "approve":
                by = a.get("by") or []
                if len(set(by)) != len(by):
                    bad(b.id, "approve `by` has a repeated runner")
                if not set(by) <= wb.peer_ids:
                    bad(b.id, f"approve `by` lists non-peers {sorted(set(by) - wb.peer_ids)}")
                if quorum is not None and a.get("build") == "target_latest" and len(set(by)) != quorum - 1:
                    bad(b.id, f"approve of the target's build needs {quorum - 1} peers (quorum "
                              f"{quorum} minus the target's own); has {len(set(by))}")
            else:
                bad(b.id, f"unknown action kind {kind!r}")

    registered: set[str] = set()
    for b in wb.beats:                         # a post may name a build this beat (or an
        for a in b.actions:                    # earlier one) registers, not a later one
            if a.get("kind") == "register_build":
                registered.add(a.get("build"))
        for tok in (BUILD_TOKEN.findall(b.post.body) if b.post else []):
            if tok not in registered:
                bad(b.id, f"post names build {tok!r} before any beat has registered it")
    return problems
