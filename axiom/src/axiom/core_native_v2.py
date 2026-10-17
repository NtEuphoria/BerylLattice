"""Private pinned ABI qualification helpers, not a production buffer worker.

B2 binds the independently hand-written tiny fixture only. Successful binding
does not qualify an allocator, arbitrary kernels, timings or source semantics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from .core_toolchain import PINNED_CORE_COMMIT, Toolchain

_TYPE = 'be_t_List_3ci32_3e'
_NAMES = ('axiom_buffer_fixture.ax_preflight', 'axiom_buffer_fixture.ax_body')
_SYMBOLS = ('be_i_axiom_5fbuffer_5ffixture_2eax_5fpreflight',
            'be_i_axiom_5fbuffer_5ffixture_2eax_5fbody')
_ABI = 'axiom-core-buffer-host-v1/linux-x86_64-c11-lp64'
_SIGNATURES = (f'int32_t (*)(const {_TYPE} *)',
               f'void (*)(const {_TYPE} *, {_TYPE} *, {_TYPE} *)')


class NativeBindingUnavailable(RuntimeError):
    """The exact pinned binding has not been established; do not execute it."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class _FixtureBinding:
    abi: str
    core_pin: str
    compiler_sha256: str
    clang_sha256: str
    qualification_receipt: tuple[str, str]
    core_source_inventory_sha256: str
    source_order: tuple[str, ...]
    core_sources: tuple[tuple[str, str], ...]
    generated_c_sha256: str
    runtime_sources: tuple[tuple[str, str], ...]
    qualified_names: tuple[str, str]
    c_symbols: tuple[str, str]
    descriptor_typedef: str
    signatures: tuple[str, str]
    # data/len/cap offsets, size, alignment; field types are asserted below.
    descriptor_layout: tuple[int, int, int, int, int]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=2) + '\n'


def _bind_fixture(toolchain: Toolchain, sources: tuple[Path, ...],
                  generated_c: Path) -> _FixtureBinding:
    """Bind bytes and ordered original paths after retained qualification validation.

    The caller must load_toolchain first. No receipt metadata is executed, no
    general C parsing occurs, and C declarations are established by compilation.
    """
    if toolchain.source_pin != PINNED_CORE_COMMIT:
        raise NativeBindingUnavailable('Core pin differs from private binding')
    toolchain.revalidate_identity()
    if 'Target: x86_64-pc-linux-gnu\n' not in toolchain.clang_version:
        raise NativeBindingUnavailable('private binding target is unavailable')
    if not sources or any(not source.is_absolute() or not source.is_file() for source in sources):
        raise NativeBindingUnavailable('binding needs ordered absolute Core source files')
    ordered = tuple(str(source) for source in sources)
    if len(set(ordered)) != len(ordered):
        raise NativeBindingUnavailable('duplicate binding source path')
    return _FixtureBinding(
        _ABI, toolchain.source_pin, toolchain.compiler_sha256, toolchain.clang_sha256,
        (str(toolchain.receipt_path), _sha(toolchain.receipt_path)),
        toolchain.source_inventory_sha256, ordered,
        tuple((str(source), _sha(source)) for source in sources), _sha(generated_c),
        tuple((name, _sha(toolchain.snapshot / name)) for name in (
            'runtime/beryl_rt.h', 'runtime/beryl_rt.c', 'src/back/runtime_embed.h')),
        _NAMES, _SYMBOLS, _TYPE,
        _SIGNATURES,
        (0, 8, 12, 16, 8))


def _validate_binding(binding: _FixtureBinding, toolchain: Toolchain,
                      sources: tuple[Path, ...], generated_c: Path) -> None:
    if binding != _bind_fixture(toolchain, sources, generated_c):
        raise NativeBindingUnavailable('private binding identity changed')


def _binding_assertions(binding: _FixtureBinding) -> str:
    """Compile against actual emitted declarations; never a lookalike descriptor."""
    if (binding.abi, binding.core_pin, binding.qualified_names, binding.c_symbols,
        binding.descriptor_typedef, binding.signatures, binding.descriptor_layout) != (
            _ABI, PINNED_CORE_COMMIT, _NAMES, _SYMBOLS, _TYPE, _SIGNATURES, (0, 8, 12, 16, 8)):
        raise NativeBindingUnavailable('unsupported private binding declarations')
    return '''/* Pinned same-translation-unit qualification. No generated-C rewriting. */
#include <limits.h>
#include <stddef.h>
#if !defined(__linux__) || !defined(__x86_64__)
#error unsupported private binding target
#endif
_Static_assert(__STDC_VERSION__ >= 201112L, "C11");
_Static_assert(CHAR_BIT == 8, "eight-bit bytes");
_Static_assert(sizeof(int32_t) == 4, "four-byte i32");
_Static_assert(sizeof(void *) == 8, "LP64 pointer");
_Static_assert(_Generic(((be_t_List_3ci32_3e){0}).data, int32_t *: 1, default: 0), "data type");
_Static_assert(_Generic(((be_t_List_3ci32_3e){0}).len, int32_t: 1, default: 0), "len type");
_Static_assert(_Generic(((be_t_List_3ci32_3e){0}).cap, int32_t: 1, default: 0), "cap type");
_Static_assert(offsetof(be_t_List_3ci32_3e, data) == 0, "data offset");
_Static_assert(offsetof(be_t_List_3ci32_3e, len) == 8, "len offset");
_Static_assert(offsetof(be_t_List_3ci32_3e, cap) == 12, "cap offset");
_Static_assert(sizeof(be_t_List_3ci32_3e) == 16, "descriptor size");
_Static_assert(_Alignof(be_t_List_3ci32_3e) == 8, "descriptor alignment");
_Static_assert(_Generic(&be_i_axiom_5fbuffer_5ffixture_2eax_5fpreflight,
    int32_t (*)(const be_t_List_3ci32_3e *): 1, default: 0), "preflight signature");
_Static_assert(_Generic(&be_i_axiom_5fbuffer_5ffixture_2eax_5fbody,
    void (*)(const be_t_List_3ci32_3e *, be_t_List_3ci32_3e *, be_t_List_3ci32_3e *): 1,
    default: 0), "body signature");
'''
