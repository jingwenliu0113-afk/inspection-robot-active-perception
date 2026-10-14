"""Sealed formal runs and frozen artifacts (decision 014).

Two formal evaluations exist and both are used up:

- ``core`` test split: v1, run once (decision 010, commit 3dd52b9) -> ``results/test-v1/``
- ``holdout`` split: v1 vs v2 (+ ablation), run once (decision 013, commit e450414)
  -> ``results/holdout/``

Neither may feed any further design, tuning or threshold choice, and they are never pooled.
``SEALED.sha256`` pins every committed result, the frozen episode sets and the frozen
configurations; ``tests/test_seal.py`` fails if any pinned file changes. New files may be
added (a later version writes new result directories); pinned ones are never rewritten.

A formal runner pointed at a sealed (episode set, split) refuses unless ``--reproduce`` is
given, and a reproduction never writes under ``results/``: it only checks that the committed
outcomes come out bit-identical.

    python -m activeperception.seal manifest   # (re)write SEALED.sha256 for new files
    python -m activeperception.seal verify
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .types import Split

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "SEALED.sha256"
PINNED = (
    "results",
    "data/episodes",
    "data/r0a",  # R0a image selection (decision 020)
    "activeperception/frozen.py",
    "activeperception/frozen_v2.py",
)


@dataclass(frozen=True)
class SealedRun:
    episode_set: str
    split: Split
    results: str
    commit: str
    decision: str


SEALED_RUNS = (
    SealedRun("data/episodes/gazebo-core.json", Split.TEST, "results/test-v1", "3dd52b9", "010"),
    SealedRun(
        "data/episodes/gazebo-holdout.json", Split.HOLDOUT, "results/holdout", "e450414", "013"
    ),
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pinned_files(root: Path = ROOT) -> list[str]:
    """Committed files under ``PINNED`` (git-tracked only, so ignored local data never counts)."""
    out = subprocess.run(
        ["git", "ls-files", "--", *PINNED], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    return sorted(out.split())


def read_manifest(root: Path = ROOT) -> dict[str, str]:
    lines = (root / MANIFEST).read_text().splitlines()
    return {path: digest for digest, path in (ln.split("  ", 1) for ln in lines if ln.strip())}


def write_manifest(root: Path = ROOT) -> dict[str, str]:
    """Add new pinned files; an already pinned file whose content changed is an error."""
    old = read_manifest(root) if (root / MANIFEST).exists() else {}
    new = {p: sha256(root / p) for p in pinned_files(root)}
    changed = sorted(p for p in old if p in new and new[p] != old[p])
    missing = sorted(p for p in old if p not in new)
    if changed or missing:
        raise SystemExit(f"sealed files changed {changed} or missing {missing}: never rewrite them")
    (root / MANIFEST).write_text("".join(f"{d}  {p}\n" for p, d in sorted(new.items())))
    return new


def verify(root: Path = ROOT) -> list[str]:
    """Pinned files whose content no longer matches the manifest (or that are gone)."""
    bad = []
    for path, digest in read_manifest(root).items():
        f = root / path
        if not f.is_file() or sha256(f) != digest:
            bad.append(path)
    return bad


def sealed_run(episodes: str | Path, split: Split, root: Path = ROOT) -> SealedRun | None:
    """The sealed run this (episode set, split) belongs to, matched by content digest."""
    if not Path(episodes).is_file():
        return None  # the loader reports a missing episode set
    pins = read_manifest(root)
    digest = sha256(Path(episodes))
    for run in SEALED_RUNS:
        if run.split == split and pins.get(run.episode_set) == digest:
            return run
    return None


def guard_formal_run(
    episodes: str | Path, split: Split, out: str | Path, reproduce: bool, root: Path = ROOT
) -> SealedRun | None:
    run = sealed_run(episodes, split, root)
    if run is None:
        return None
    if not reproduce:
        raise SystemExit(
            f"{run.episode_set} [{split}] is sealed: its formal run is done "
            f"(decision {run.decision}, commit {run.commit}). Use --reproduce with an --out "
            "outside results/ to check the committed outcomes; never re-run it for development."
        )
    if Path(out).resolve().is_relative_to((root / "results").resolve()):
        raise SystemExit("a reproduction never writes under results/ (decision 014)")
    return run


def compare_reproduction(run: SealedRun, out: str | Path, root: Path = ROOT) -> bool:
    same = sha256(Path(out) / "outcomes.jsonl") == sha256(root / run.results / "outcomes.jsonl")
    verdict = "bit-identical" if same else "DIFFERENT"
    print(f"reproduction of {run.results}/outcomes.jsonl: {verdict}")
    return same


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="activeperception.seal")
    ap.add_argument("action", choices=["manifest", "verify"])
    args = ap.parse_args(argv)
    if args.action == "manifest":
        print(f"{len(write_manifest())} pinned files -> {MANIFEST}")
        return 0
    bad = verify()
    print("all pinned files unchanged" if not bad else f"CHANGED: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
