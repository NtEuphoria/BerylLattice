"""C11 loops for checked scale-v1 loop plans.

Emission happens only after scale_checker proves the plan against fresh
source. Arithmetic is plain int32_t: the checker's interval proof shows no +,
* or partial sum (in any order) leaves i32, so nothing overflows and the C
compiler may vectorize and reassociate accumulations. Index arithmetic is
int64_t. The branch-free input preflight runs before any output is written;
on rejection the first invalid index plus one is returned.
"""
from dataclasses import dataclass
from hashlib import sha256

from .model import Limits
from .native_codegen import _DRIVER, NativeArtifact
from .scale_checker import check_loop_plan
from .scale_plan import make_scale_plan
from .frontend import admit_source, parse_source

SCALE_CODEGEN_VERSION = 'beryl-loop-c-v1'


def _affine(value):
    constant, terms = value
    parts = [f'(int64_t){constant}'] + [f'(int64_t){k} * {var}' for var, k in terms]
    return ' + '.join(parts)


def _literal(value):
    return '(-2147483647 - 1)' if value == -2147483648 else f'{value}'


def _lower(expr, statements, counter):
    kind = expr[0]
    if kind == 'const':
        return _literal(expr[1])
    if kind == 'load':
        return f'input[{_affine(expr[1])}]'
    if kind in ('add', 'mul'):
        operator = '+' if kind == 'add' else '*'
        left, right = _lower(expr[1], statements, counter), _lower(expr[2], statements, counter)
        return f'({left} {operator} {right})'
    _, var, lower, upper, body = expr
    name = f'ax_s{next(counter)}'
    inner = []
    value = _lower(body, inner, counter)
    statements.append(f'int32_t {name} = 0;')
    statements.append(f'for (int32_t {var} = {lower}; {var} < {upper}; ++{var}) {{')
    statements.extend('    ' + line for line in inner)
    statements.append(f'    {name} += {value};')
    statements.append('}')
    return name


def emit_scale_c(kernel, plan, source_digest, plan_digest) -> NativeArtifact:
    """Emit C for a plan that check_loop_plan has just proved for `kernel`."""
    (stage,) = plan.stages
    (v0, h), (v1, w) = stage.loops
    statements = []
    counter = iter(range(1 << 30))
    value = _lower(stage.value, statements, counter)
    n_in, n_out = kernel.input_count, kernel.height * kernel.width
    lower, upper = kernel.input_interval
    body = '\n'.join('            ' + line for line in statements)
    kernel_c = f'''/* Generated from a template-checked scale-v1 loop plan ({plan.plan_id}). */
#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

_Static_assert(sizeof(int32_t) == 4, "four-byte i32 required");
_Static_assert(sizeof(int64_t) == 8, "eight-byte i64 required");
enum {{ BERYL_HEIGHT = {kernel.height}, BERYL_WIDTH = {kernel.width},
       BERYL_INPUT_COUNT = {n_in}, BERYL_OUTPUT_COUNT = {n_out} }};

/* Caller owns disjoint initialized arrays of the exact compiled counts. */
int32_t beryl_kernel(const int32_t *restrict input, int32_t *restrict output) {{
    uint32_t ax_invalid = 0;
    for (int64_t i = 0; i < {n_in}; ++i)
        ax_invalid |= (uint32_t)(input[i] < {lower} || input[i] > {upper});
    if (ax_invalid) {{
        for (int64_t i = 0; i < {n_in}; ++i)
            if (input[i] < {lower} || input[i] > {upper}) return (int32_t)(i + 1);
    }}
    for (int32_t {v0} = 0; {v0} < {h}; ++{v0}) {{
        for (int32_t {v1} = 0; {v1} < {w}; ++{v1}) {{
{body}
            output[{_affine(stage.index)}] = {value};
        }}
    }}
    return 0;
}}
'''
    # Large buffers live in static storage, not on the driver's stack.
    assert '= {0};' in _DRIVER
    driver = (_DRIVER.replace('    int32_t input[BERYL_INPUT_COUNT] = {0};', '    static int32_t input[BERYL_INPUT_COUNT];')
              .replace('    int32_t output[BERYL_OUTPUT_COUNT] = {0};', '    static int32_t output[BERYL_OUTPUT_COUNT];'))
    generated = (kernel_c + driver).encode('ascii')
    return NativeArtifact(generated, kernel.height, kernel.width, n_in, n_out, source_digest,
                          plan_digest, sha256(generated).hexdigest(), SCALE_CODEGEN_VERSION,
                          None, plan.format)


@dataclass(frozen=True, slots=True)
class ScaleCompilation:
    kernel: object
    check: object
    artifact: NativeArtifact | None
    reason: str
    plan: object = None


def compile_scale_native(source: bytes, limits: Limits = Limits()) -> ScaleCompilation:
    """Fresh admission, plan generation, template proof, then C emission."""
    kernel = admit_source(parse_source(source, limits))
    try:
        plan = make_scale_plan(kernel, max_nodes=limits.plan_operations)
    except Exception as error:  # an untrusted generator may fail in any way
        return ScaleCompilation(kernel, None, None, getattr(error, 'code', type(error).__name__))
    check = check_loop_plan(source, plan, limits)
    if not check.valid:
        return ScaleCompilation(kernel, check, None, check.reason, plan)
    return ScaleCompilation(kernel, check, emit_scale_c(kernel, plan, sha256(source).hexdigest(),
                                                        check.plan_digest), 'VALID', plan)
