# Hand-reviewed Core witness

Pinned before core_emit.py was implemented. minimal.ax has H=W=1. The direct
inline witness minimal.be reads four independent inputs 0,1,2,3; their incremented
squares are 1,4,9,16 and left-associated sum is 30. minimal.stdout observes success
-1, every input in row-major order, and the complete output. Preflight returns
0..3 before any arithmetic or output mutation. The initialized output sentinel
is -99. Arrays and the inout argument follow pinned Core source examples.

This literal-input program is only a correspondence witness. It is not a reusable
native ABI or a performance workload; constant folding may remove its work.

Actual AST-reference execution confirmed the pinned scalar values. Core appends
`ok  1 test, 0 assertions` to the observation stdout; the fixture retains this
required framing as well. This framing addition does not alter the pinned values.
