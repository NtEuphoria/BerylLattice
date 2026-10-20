"""Fresh bounded source compilation, with untrusted compact scheduling hints.

A transaction owns admission, ranked proof and emission. No caller-supplied
context or proof is accepted, and no live authority escapes the transaction.
"""
from dataclasses import dataclass

from .bounded_loop_c import _emit_native_c_compact
from .bounded_loop_codec import encode_loop_program
from .bounded_loop_model import HintError
from .bounded_loop_planner import make_loop_program
from .bounded_loop_wasm import _compile_wasm_compact
from .codec import DecodeError
from .compilation import _CompilationContext
from .compilation_selection import FastSearchResult, FastSearchStop, _select_ranked
from .frontend import admit_source, parse_source
from .model import CANONICAL_PROFILE, SCALE_PROFILE, AdmittedKernel, DiagnosticError, Limits
from .native_codegen import NativeArtifact, _emit_native_c_checked
from .scale_c import compile_scale_native
from .window_loop_planner import make_window_loop_program
from .wasm import WasmArtifact, _compile_wasm_checked


@dataclass(frozen=True, slots=True)
class SourceCompilation:
    kernel: AdmittedKernel
    search: FastSearchResult
    artifact: NativeArtifact | WasmArtifact | None
    hint_failure: str | None


def _compile_source(source, limits, trace, compact, finite):
    context = _CompilationContext(source, limits, trace=trace)
    try:
        search, owned = _select_ranked(context, 100000)
        if owned is None:
            return SourceCompilation(context.kernel, search, None, None)
        failure = None
        try:
            with context.phase('hint_generation'):
                # Portfolio identity chooses intent, never proof authority. A plan
                # may carry an arbitrary label; exact correspondence still decides.
                schedule = next(attempt.candidate_id for attempt in search.attempts
                                if attempt.check is owned.checked)
                if context.kernel.profile == CANONICAL_PROFILE:
                    program = make_loop_program(context.kernel, schedule)
                else:
                    try:
                        program = make_window_loop_program(context.kernel, schedule)
                    except ValueError as error:
                        raise HintError('HINT_UNAVAILABLE', str(error)) from None
                hint = encode_loop_program(program)
            artifact = compact(owned, hint)
        except (HintError, DecodeError) as error:
            failure = error.code
            artifact = finite(owned)
        return SourceCompilation(context.kernel, search, artifact, failure)
    finally:
        context.close()


@dataclass(frozen=True, slots=True)
class ScaleSearch:
    """The outcome of one template proof, in the shape callers read."""
    termination_reason: FastSearchStop
    reason: str
    check: object
    selected_plan: object = None
    attempts: tuple = ()

    @property
    def selected_check(self):
        return self.check if self.selected_plan is not None else None


def _scale_kernel(source, limits):
    try:
        kernel = admit_source(parse_source(source, limits))
    except DiagnosticError:
        return None  # the finite path reports the same diagnostic
    return kernel if kernel.profile == SCALE_PROFILE else None


def compile_native_source(source: bytes, limits: Limits = Limits(), *, trace=None) -> SourceCompilation:
    """Admit fresh source and emit checked compact C, or a typed finite fallback.

    scale-v1 kernels instead compile from a template-checked loop plan."""
    if _scale_kernel(source, limits) is not None:
        result = compile_scale_native(source, limits)
        stop = FastSearchStop.COMPLETED if result.artifact is not None else FastSearchStop.UNKNOWN
        return SourceCompilation(result.kernel, ScaleSearch(stop, result.reason, result.check,
                                                 result.plan if result.artifact is not None else None),
                                 result.artifact, None)
    return _compile_source(source, limits, trace, _emit_native_c_compact, _emit_native_c_checked)


def compile_wasm_source(source: bytes, limits: Limits = Limits(), *, trace=None) -> SourceCompilation:
    """Admit fresh source and emit checked compact Wasm, or a typed finite fallback."""
    kernel = _scale_kernel(source, limits)
    if kernel is not None:
        raise DiagnosticError('UNSUPPORTED_PROFILE', kernel.source_module.span,
                              'scale-v1 programs compile to native C only for now')
    return _compile_source(source, limits, trace, _compile_wasm_compact, _compile_wasm_checked)
