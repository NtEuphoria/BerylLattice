#include "operation_allocator.h"
#include "buffer_host.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    size_t bytes = 17;
    assert(ax_i32_bytes(0, SIZE_MAX, &bytes) && bytes == 0);
    assert(ax_i32_bytes(INT32_MAX, SIZE_MAX, &bytes) && bytes == (size_t)INT32_MAX * 4);
    assert(!ax_i32_bytes((uint64_t)INT32_MAX + 1, SIZE_MAX, &bytes));
    assert(!ax_i32_bytes(UINT64_MAX, SIZE_MAX, &bytes));
    assert(!ax_i32_bytes(2, 7, &bytes));
    assert(ax_size_add(SIZE_MAX - 1, 1, &bytes) && bytes == SIZE_MAX);
    assert(!ax_size_add(SIZE_MAX, 1, &bytes));
    ax_shape s;
    assert(ax_shape_checked(1, 1, 0, SIZE_MAX, &s));
    assert(s.input_cells == 4 && s.output_cells == 1 && s.scratch_cells == 0);
    assert(ax_shape_checked(8191, 1023, 8388608, SIZE_MAX, &s));
    assert(s.input_cells == 8388608 && s.output_cells == 8379393);
    assert(ax_shape_checked(8192, 1, 0, SIZE_MAX, &s));
    assert(!ax_shape_checked(8192, 1023, 0, SIZE_MAX, &s));
    assert(!ax_shape_checked(0, 1, 0, SIZE_MAX, &s));
    assert(!ax_shape_checked(UINT64_MAX, 1, 0, SIZE_MAX, &s));
    assert(!ax_shape_checked(1, 2, 7, SIZE_MAX, &s));
    assert(!ax_shape_checked(1, 2, 6, 55, &s));
    assert(ax_shape_checked(1, 2, 6, 56, &s));
    ax_allocator a = {0};
    ax_handle h = {0};
    assert(ax_allocate(&a, AX_SCRATCH, 0, SIZE_MAX, &h) == AX_ALLOC_INVALID);
    assert(a.attempts == 0 && a.live_bytes == 0);
    for (uint64_t ordinal = 1; ordinal <= 3; ++ordinal) {
        ax_allocator b = {0};
        ax_test_fail_at(&b, ordinal);
        ax_handle handles[3] = {{0}};
        for (uint64_t i = 0; i < 3; ++i) {
            ax_alloc_status status = ax_allocate(&b, AX_SCRATCH, 6, 24, &handles[i]);
            assert(status == (i + 1 == ordinal ? AX_ALLOC_RESOURCE : AX_ALLOC_OK));
        }
        assert(b.attempts == 3 && b.allocations == 2 && b.live_bytes == 48);
        for (size_t i = 0; i < 3; ++i) if (handles[i].identity) assert(ax_release(&b, handles[i]));
        assert(b.live_bytes == 0 && b.live_allocations == 0 && b.frees == 2);
    }
    assert(ax_allocate(&a, AX_INPUT, 6, 24, &h) == AX_ALLOC_OK);
    const ax_allocation *r = ax_lookup(&a, h);
    assert(r && r->role == AX_INPUT && r->logical_cells == 6 && r->reserved_cells == 6);
    assert(r->initialized_cells == 0 && r->bytes == 24 && r->alignment == _Alignof(int32_t));
    assert((uintptr_t)r->base % r->alignment == 0);
    ax_handle old = h;
    assert(ax_release(&a, h));
    assert(!ax_lookup(&a, old) && !ax_release(&a, old));
    for (size_t i = 0; i < 1000; ++i) {
        assert(ax_allocate(&a, AX_INPUT, 1, 4, &h) == AX_ALLOC_OK);
        assert(h.identity != old.identity && h.generation > old.generation);
        assert(!ax_lookup(&a, old));
        assert(ax_release(&a, h));
    }
    assert(ax_allocate(&a, AX_SCRATCH, 6, 24, &h) == AX_ALLOC_OK);
    memset(ax_lookup(&a,h)->base, 0x7f, 24);
    assert(ax_initialize_zero(&a,h));
    for (size_t i = 0; i < 6; ++i) assert(ax_lookup(&a,h)->base[i] == 0);
    assert(ax_lookup(&a,h)->initialized_cells == 6);
    assert(!ax_initialize_zero(&a,h));
    assert(ax_release(&a,h));
    ax_allocator other = {0};
    assert(!ax_lookup(&other, h));
    assert(a.live_bytes == 0 && a.live_allocations == 0 && a.allocations == a.frees);
    puts("allocator: sizes, 3 failure ordinals, 1000 generations, balanced cleanup");
    return 0;
}
