#ifndef AXIOM_OPERATION_ALLOCATOR_V2_H
#define AXIOM_OPERATION_ALLOCATOR_V2_H
#include <stddef.h>
#include <stdint.h>
/* Private synchronous owner registry; never a wire/raw-pointer API. Initialize
 * once with zero; never copy a live registry. No views, resizing or callbacks.
 * Requested bytes are exact; malloc usable size/slack/RSS are UNKNOWN.
 * sizeof(ax_allocator) is separate bookkeeping, not requested allocation bytes. */
#define AX_ALLOCATION_SLOTS 3
typedef enum { AX_INPUT=1, AX_OUTPUT=2, AX_SCRATCH=3 } ax_role;
typedef enum { AX_ALLOC_OK, AX_ALLOC_INVALID, AX_ALLOC_RESOURCE } ax_alloc_status;
typedef struct { uint64_t identity, generation; size_t slot; } ax_handle;
typedef struct {
    uint64_t identity, generation;
    ax_role role;
    int live;
    int32_t *base;
    int32_t logical_cells, initialized_cells, reserved_cells;
    size_t bytes, alignment;
} ax_allocation;
typedef struct {
    ax_allocation records[AX_ALLOCATION_SLOTS];
    uint64_t attempts, allocations, frees, live_allocations;
    size_t live_bytes, peak_bytes;
#ifdef AX_BUFFER_TESTING
    uint64_t test_fail_ordinal;
#endif
} ax_allocator;
int ax_i32_bytes(uint64_t cells, size_t limit, size_t *bytes);
int ax_size_add(size_t a, size_t b, size_t *sum);
ax_alloc_status ax_allocate(ax_allocator *, ax_role, uint64_t cells, size_t byte_limit, ax_handle *);
const ax_allocation *ax_lookup(const ax_allocator *, ax_handle);
int ax_release(ax_allocator *, ax_handle);
/* Trusted internal preparation arrays only, before descriptor borrowing. */
int ax_initialize_copy(ax_allocator *, ax_handle, const int32_t *, size_t cells);
int ax_initialize_zero(ax_allocator *, ax_handle);
void ax_allocator_destroy(ax_allocator *);
#ifdef AX_BUFFER_TESTING
void ax_test_fail_at(ax_allocator *, uint64_t ordinal);
#endif
#endif
