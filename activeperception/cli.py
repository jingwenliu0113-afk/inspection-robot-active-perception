"""Command line entry points.

python -m activeperception build-episodes --world synthetic --namespace dev --groups 50
python -m activeperception make-specs --namespace pilot --groups 6   # Gazebo renderer input
python -m activeperception states --episodes data/episodes/synthetic-dev.json
python -m activeperception run   --episodes ... --split val --policy rule --budget 3
python -m activeperception sweep --episodes ... --split val \\
    --policies single,random,rule,oracle --budgets 1,3,5
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .decision import DECISION_RULE_VERSION, DecisionRule
from .detector.cache import DetectionCache
from .episodes import GENERATOR_VERSION, GeneratorConfig, build_episode_set
from .framestore import FrameStore
from .grader import grade_all
from .harness import run_episode_set
from .labeling import LABELING_VERSION
from .metrics import markdown_table, summarize
from .policies import OracleNBVPolicy, RandomNBVPolicy, RuleNBVPolicy, SingleViewPolicy
from .policies.rule_nbv import RULE_NBV_VERSION
from .serialize import (
    load_episode_set,
    load_spec_set,
    save_episode_set,
    save_spec_set,
    write_jsonl,
)
from .sim import SyntheticWorld
from .sim.replay import GazeboReplayWorld
from .types import Split


def make_world(name: str, args=None, meta: dict | None = None):
    """synthetic, or the Gazebo replay world (frame store + detection cache)."""
    if name == "synthetic":
        return SyntheticWorld()
    if name == "gazebo":
        renders = getattr(args, "renders", None) or (meta or {}).get("renders")
        if not renders:
            raise SystemExit("gazebo world needs --renders (frame store directory)")
        dets = getattr(args, "detections", None)
        cache = (
            DetectionCache.load(dets, min_confidence=getattr(args, "min_conf", 0.0))
            if dets
            else None
        )
        return GazeboReplayWorld(FrameStore(renders), cache)
    raise SystemExit(f"unknown world '{name}'")


def make_policy(name: str, gts):
    if name == "single":
        return SingleViewPolicy()
    if name == "random":
        return RandomNBVPolicy()
    if name == "rule":
        return RuleNBVPolicy()
    if name == "oracle":
        return OracleNBVPolicy(lambda eid: gts[eid])
    raise SystemExit(f"unknown policy '{name}'")


def cmd_build(args) -> int:
    extra = {"labeling_version": LABELING_VERSION, "package_version": __version__}
    if args.world == "gazebo":
        if not (args.specs and args.renders):
            raise SystemExit("--world gazebo needs --specs and --renders")
        specs, spec_meta = load_spec_set(args.specs)
        namespace = spec_meta.get("namespace") or specs[0].namespace
        world = make_world("gazebo", args)
        missing = [s.episode_id for s in specs if not world.store.has(s.episode_id)]
        if missing:
            raise SystemExit(f"{len(missing)} episodes not rendered, e.g. {missing[:3]}")
        image_ids = sorted(
            {str(world.store.episode(s.episode_id).meta.get("image_id")) for s in specs}
        )
        extra.update(
            {"renders": str(args.renders), "specs": str(args.specs), "image_ids": image_ids}
        )
    else:
        if not (args.namespace and args.groups):
            raise SystemExit("--world synthetic needs --namespace and --groups")
        namespace = args.namespace
        world = make_world(args.world)
        specs = build_episode_set(args.namespace, args.groups, GeneratorConfig())
    gts = {s.episode_id: world.ground_truth(s) for s in specs}
    out = Path(args.out or f"data/episodes/{args.world}-{namespace}.json")
    save_episode_set(out, specs, gts, world.name, extra=extra)
    print(f"wrote {len(specs)} episodes -> {out}")
    return cmd_states(argparse.Namespace(episodes=str(out)))


def cmd_make_specs(args) -> int:
    """Episode specs only (no GT): the frozen input of the Gazebo renderer."""
    specs = build_episode_set(args.namespace, args.groups, GeneratorConfig())
    out = Path(args.out or f"data/episodes/specs-{args.namespace}.json")
    save_spec_set(out, specs, extra={"namespace": args.namespace, "package_version": __version__})
    print(f"wrote {len(specs)} episode specs ({args.groups} groups) -> {out}")
    return 0


def cmd_states(args) -> int:
    specs, gts, meta = load_episode_set(args.episodes)
    print(
        f"episode set: {args.episodes}  world={meta.get('world')}  "
        f"generator={meta.get('generator_version')}"
    )
    for split in Split:
        sub = [s for s in specs if s.split == split]
        if not sub:
            continue
        c = Counter(str(gts[s.episode_id].state) for s in sub)
        unrev = sum(
            1 for s in sub if not gts[s.episode_id].revealable and gts[s.episode_id].object_present
        )
        groups = len({s.scene_group for s in sub})
        print(
            f"  {split:5s} n={len(sub):4d} groups={groups:3d} "
            f"{dict(sorted(c.items()))} unrevealable={unrev}"
        )
    return 0


def _select(specs, split: str | None, limit: int | None):
    if split:
        specs = [s for s in specs if s.split == Split(split)]
    if limit:
        specs = specs[:limit]
    return specs


def cmd_run(args) -> int:
    specs, gts, meta = load_episode_set(args.episodes)
    specs = _select(specs, args.split, args.limit)
    if not specs:
        raise SystemExit("no episodes selected")
    world = make_world(meta.get("world", "synthetic"), args, meta)
    rule = DecisionRule()
    policy = make_policy(args.policy, gts)
    records = run_episode_set(specs, world, policy, rule, args.budget, args.run_seed)
    outcomes = grade_all(records, gts, {s.episode_id: s for s in specs})
    summary = summarize(outcomes, n_boot=args.n_boot, seed=args.run_seed)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        write_jsonl(out / "records.jsonl", records)
        write_jsonl(out / "outcomes.jsonl", outcomes)
        (out / "metrics.json").write_text(json.dumps(summary, indent=1))
        (out / "config.json").write_text(json.dumps(_config(args, meta), indent=1))
    print(markdown_table({(args.policy, args.budget): summary}))
    return 0


def cmd_sweep(args) -> int:
    specs, gts, meta = load_episode_set(args.episodes)
    specs = _select(specs, args.split, args.limit)
    if not specs:
        raise SystemExit("no episodes selected")
    world = make_world(meta.get("world", "synthetic"), args, meta)
    rule = DecisionRule()
    summaries = {}
    all_records = []
    all_outcomes = []
    for budget in [int(b) for b in args.budgets.split(",")]:
        for pname in args.policies.split(","):
            policy = make_policy(pname, gts)
            records = run_episode_set(specs, world, policy, rule, budget, args.run_seed)
            outcomes = grade_all(records, gts, {s.episode_id: s for s in specs})
            summaries[(pname, budget)] = summarize(outcomes, n_boot=args.n_boot, seed=args.run_seed)
            all_records += records
            all_outcomes += outcomes
    table = markdown_table(summaries)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        write_jsonl(out / "records.jsonl", all_records)
        write_jsonl(out / "outcomes.jsonl", all_outcomes)
        (out / "metrics.json").write_text(
            json.dumps({f"{p}@{b}": s for (p, b), s in summaries.items()}, indent=1)
        )
        (out / "table.md").write_text(table + "\n")
        (out / "config.json").write_text(json.dumps(_config(args, meta), indent=1))
    print(table)
    return 0


def _config(args, meta) -> dict:
    return {
        "args": {k: v for k, v in vars(args).items() if k != "fn"},
        "episode_set": meta,
        "versions": {
            "package": __version__,
            "generator": GENERATOR_VERSION,
            "labeling": LABELING_VERSION,
            "decision_rule": DECISION_RULE_VERSION,
            "rule_nbv": RULE_NBV_VERSION,
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="activeperception")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build-episodes")
    b.add_argument("--world", default="synthetic", choices=["synthetic", "gazebo"])
    b.add_argument("--namespace", help="synthetic: namespace to generate")
    b.add_argument("--groups", type=int, help="synthetic: number of scene groups")
    b.add_argument("--specs", help="gazebo: spec-set JSON the renders were made from")
    b.add_argument("--renders", help="gazebo: frame store directory")
    b.add_argument("--out")
    b.set_defaults(fn=cmd_build)

    m = sub.add_parser("make-specs")
    m.add_argument("--namespace", required=True)
    m.add_argument("--groups", type=int, required=True)
    m.add_argument("--out")
    m.set_defaults(fn=cmd_make_specs)

    s = sub.add_parser("states")
    s.add_argument("--episodes", required=True)
    s.set_defaults(fn=cmd_states)

    for name, fn in (("run", cmd_run), ("sweep", cmd_sweep)):
        r = sub.add_parser(name)
        r.add_argument("--episodes", required=True)
        r.add_argument("--split")
        r.add_argument("--limit", type=int)
        r.add_argument("--run-seed", type=int, default=0)
        r.add_argument("--n-boot", type=int, default=0)
        r.add_argument("--out")
        r.add_argument("--renders", help="gazebo: frame store (default: from the episode set)")
        r.add_argument("--detections", help="gazebo: detection cache JSONL")
        r.add_argument("--min-conf", type=float, default=0.0, help="drop detections below this")
        if name == "run":
            r.add_argument("--policy", required=True)
            r.add_argument("--budget", type=int, required=True)
        else:
            r.add_argument("--policies", default="single,random,rule,oracle")
            r.add_argument("--budgets", default="1,3,5")
        r.set_defaults(fn=fn)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
