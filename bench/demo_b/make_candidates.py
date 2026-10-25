#!/usr/bin/env python3
"""Rebuild demo B's generated candidates: the planner's plans and seeded mutants.

Agent-written candidates (agent-*.json) are added by hand from
docs/pitch/agent-plan-prompt.md and are never overwritten here.
"""
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / 'axiom' / 'src'), str(ROOT / 'axiom')]
from axiom.frontend import admit_source, parse_source  # noqa: E402
from axiom.scale_plan import LoopPlan, Stage, make_scale_plan, plan_json  # noqa: E402
from tests.test_scale_oracle import _mutate  # noqa: E402

source = (HERE / 'program.ax').read_bytes()
kernel = admit_source(parse_source(source))
out = HERE / 'candidates'
out.mkdir(exist_ok=True)
direct = make_scale_plan(kernel, 'direct-v1')
(out / 'planner-direct.json').write_bytes(plan_json(direct))
(out / 'planner-carry.json').write_bytes(plan_json(make_scale_plan(kernel, 'carry-v1')))
rng = random.Random(20261102)
stage = direct.stages[0]
for number in range(10):
    mutant = LoopPlan(direct.semantic_digest, direct.plan_id,
                      (Stage(stage.loops, stage.index, _mutate(stage.value, rng)),))
    (out / f'mutant-{number:02d}.json').write_bytes(plan_json(mutant))
print(f'wrote 12 candidates to {out.relative_to(ROOT)}')
