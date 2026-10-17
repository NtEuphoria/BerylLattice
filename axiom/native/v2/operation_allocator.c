#include "operation_allocator.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>
_Static_assert(CHAR_BIT == 8 && sizeof(int32_t) == 4, "i32 byte profile");
/* Process lifetime serial never resets on host reuse. Private synchronous worker. */
static uint64_t ax_next_identity = 1;
int ax_i32_bytes(uint64_t cells, size_t limit, size_t *bytes) {
    if (!bytes || cells > INT32_MAX || cells > SIZE_MAX / sizeof(int32_t)) return 0;
    size_t n = (size_t)cells * sizeof(int32_t);
    if (n > limit) return 0;
    *bytes = n; return 1;
}
int ax_size_add(size_t a, size_t b, size_t *sum) {
    if (!sum || a > SIZE_MAX - b) return 0;
    *sum = a + b; return 1;
}
const ax_allocation *ax_lookup(const ax_allocator *a, ax_handle h) {
    if (!a || !h.identity || !h.generation || h.slot >= AX_ALLOCATION_SLOTS) return NULL;
    const ax_allocation *r = &a->records[h.slot];
    return r->live && r->identity == h.identity && r->generation == h.generation ? r : NULL;
}
ax_alloc_status ax_allocate(ax_allocator *a, ax_role role, uint64_t cells, size_t limit, ax_handle *handle) {
    size_t bytes, live;
    if (!a || !handle || role < AX_INPUT || role > AX_SCRATCH || !cells ||
        !ax_i32_bytes(cells,limit,&bytes) || !ax_size_add(a->live_bytes,bytes,&live)) return AX_ALLOC_INVALID;
    size_t slot = 0;
    while (slot < AX_ALLOCATION_SLOTS && a->records[slot].live) ++slot;
    if (slot == AX_ALLOCATION_SLOTS || a->attempts == UINT64_MAX ||
        a->allocations == UINT64_MAX || ax_next_identity == UINT64_MAX) return AX_ALLOC_RESOURCE;
    *handle = (ax_handle){0}; ++a->attempts;
#ifdef AX_BUFFER_TESTING
    if (a->test_fail_ordinal && a->attempts == a->test_fail_ordinal) return AX_ALLOC_RESOURCE;
#endif
    int32_t *base = malloc(bytes);
    if (!base) return AX_ALLOC_RESOURCE;
    uint64_t identity = ax_next_identity++;
    a->records[slot] = (ax_allocation){identity,identity,role,1,base,(int32_t)cells,0,(int32_t)cells,bytes,_Alignof(int32_t)};
    *handle = (ax_handle){identity,identity,slot};
    ++a->allocations; ++a->live_allocations; a->live_bytes = live;
    if (live > a->peak_bytes) a->peak_bytes = live;
    return AX_ALLOC_OK;
}
int ax_initialize_copy(ax_allocator *a, ax_handle h, const int32_t *values, size_t cells) {
    const ax_allocation *r = ax_lookup(a,h);
    if (!r || !values || cells != (size_t)r->logical_cells || r->initialized_cells) return 0;
    memcpy(r->base,values,r->bytes); a->records[h.slot].initialized_cells = r->logical_cells; return 1;
}
int ax_initialize_zero(ax_allocator *a, ax_handle h) {
    const ax_allocation *r = ax_lookup(a,h);
    if (!r || r->initialized_cells) return 0;
    memset(r->base,0,r->bytes); a->records[h.slot].initialized_cells = r->logical_cells; return 1;
}
int ax_release(ax_allocator *a, ax_handle h) {
    const ax_allocation *r = ax_lookup(a,h);
    if (!r) return 0;
    free(r->base); /* original owner, never borrowed descriptor contents */
    a->live_bytes -= r->bytes; --a->live_allocations; ++a->frees;
    a->records[h.slot] = (ax_allocation){0}; return 1;
}
void ax_allocator_destroy(ax_allocator *a) {
    if (!a) return;
    for (size_t i = 0; i < AX_ALLOCATION_SLOTS; ++i) {
        const ax_allocation *r = &a->records[i];
        if (r->live) ax_release(a,(ax_handle){r->identity,r->generation,i});
    }
}
#ifdef AX_BUFFER_TESTING
void ax_test_fail_at(ax_allocator *a, uint64_t ordinal) { a->test_fail_ordinal = ordinal; }
#endif
