"""Deterministic teleport harness with a hard viewpoint budget.

Protocol (identical for every policy):
1. Observe the initial viewpoint (counts as view 1).
2. Apply the shared decision rule. Stop if the decision is definitive
   (present / absent) or the budget is exhausted.
3. Otherwise ask the policy for the next unvisited candidate, teleport, observe,
   and repeat. A policy may stop early by returning ``None``.

The budget counts observations, initial view included: budget 1 == Single View
for every policy.
"""

from __future__ import annotations

from .decision import DecisionRule
from .policies.base import Policy
from .sim.base import ObservationSource
from .types import Decision, EpisodeRecord, EpisodeSpec


class HarnessError(RuntimeError):
    pass


def run_episode(
    spec: EpisodeSpec,
    world: ObservationSource,
    policy: Policy,
    rule: DecisionRule,
    budget: int,
    run_seed: int = 0,
) -> EpisodeRecord:
    if budget < 1:
        raise ValueError("budget must be >= 1 (the initial view)")
    episode = spec.deployable()
    candidate_ids = {vp.id for vp in episode.candidate_viewpoints}
    policy.reset(episode, run_seed)
    history = [world.observe(spec, spec.initial_viewpoint)]
    out = rule.decide(episode, history)
    while out.decision == Decision.INCONCLUSIVE and len(history) < budget:
        nxt = policy.select_next(episode, tuple(history), budget - len(history))
        if nxt is None:
            break
        if nxt not in candidate_ids:
            raise HarnessError(f"{policy.name}: unknown candidate id {nxt}")
        if nxt in {o.viewpoint_id for o in history}:
            raise HarnessError(f"{policy.name}: revisited candidate id {nxt}")
        history.append(world.observe(spec, episode.candidate(nxt)))
        out = rule.decide(episode, history)
    if len(history) > budget:
        raise HarnessError("budget exceeded")
    return EpisodeRecord(
        episode_id=spec.episode_id,
        policy=policy.name,
        budget=budget,
        run_seed=run_seed,
        viewpoint_sequence=tuple(o.viewpoint_id for o in history),
        observations=tuple(history),
        decision=out.decision,
        confidence=out.confidence,
        features=dict(out.features),
    )


def run_episode_set(
    specs: list[EpisodeSpec],
    world: ObservationSource,
    policy: Policy,
    rule: DecisionRule,
    budget: int,
    run_seed: int = 0,
) -> list[EpisodeRecord]:
    return [run_episode(s, world, policy, rule, budget, run_seed) for s in specs]
