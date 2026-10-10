"""Active perception under a fixed viewpoint budget (Core).

Research question: can rule-based next-best-view selection reduce *inconclusive*
inspection outcomes (and avoid false-absent) compared with single-view and random
baselines, at the same viewpoint budget?

Package layout
--------------
- ``types``      frozen schemas: ground-truth states, decisions, poses, episodes.
- ``geometry``   pinhole camera projection and segment/box occlusion tests.
- ``episodes``   seeded episode generator, candidate viewpoints, split assignment.
- ``labeling``   world-independent rule mapping GT visibility to the 3 GT states.
- ``sim``        observation sources (synthetic analytic world; Gazebo later).
- ``decision``   shared decision rule: observation history -> present/absent/inconclusive.
- ``policies``   Single View / Random NBV / Rule-based NBV / Oracle NBV.
- ``harness``    deterministic teleport loop with a hard viewpoint budget.
- ``grader``     per-episode outcome (correct / false-absent / false-present / inconclusive).
- ``metrics``    aggregate metrics + cluster bootstrap CIs (cluster = scene group).
"""

__version__ = "0.1.0"
