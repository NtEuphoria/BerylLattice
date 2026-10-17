#ifndef AXIOM_BUFFER_HOST_V2_H
#define AXIOM_BUFFER_HOST_V2_H
#include "operation_allocator.h"
/* Private C implementation API for B5/B6, not transport or source admission.
 * The caller admits source/check/build identities before constructing this host.
 * Preparation/capture pointers are trusted internal arrays, not caller pointer
 * validation. Host owns all allocations exclusively; no aliases/concurrency. */
typedef struct {
    uint32_t height, width;
    int32_t input_cells, output_cells, scratch_cells;
    size_t input_bytes, output_bytes, scratch_bytes, total_bytes;
} ax_shape;
typedef enum { AX_PREPARED, AX_PREPARATION_BOUNDARY, AX_PREPARATION_RESOURCE } ax_preparation;
typedef enum { AX_CALL_SUCCESS, AX_CALL_SOURCE_REJECTED, AX_CALL_BOUNDARY,
    AX_CALL_RESOURCE, AX_CALL_INTEGRITY } ax_call_status;
/* A normal semantic call still requires complete acquisition and independent
 * comparison outside this layer. These records are not NativeRunV2 receipts. */
typedef struct {
    ax_call_status status;
    int32_t first_bad;
    int body_called;
    uint64_t body_allocation_attempts;
    const char *events[6];
    size_t event_count;
} ax_call;
typedef struct {
    ax_allocator preparation, operation;
    ax_handle input, output;
    ax_shape shape;
    /* Opaque internal compiled token, NOT a source/build hash or admission proof. */
    uint64_t specialization;
    size_t byte_limit;
    int prepared, busy;
#ifdef AX_BUFFER_TESTING
    int test_fault;
#endif
} ax_host;
int ax_shape_checked(uint64_t h, uint64_t w, uint64_t scratch, size_t byte_limit, ax_shape *);
ax_preparation ax_host_prepare(ax_host *, uint64_t h, uint64_t w, uint64_t scratch,
    uint64_t specialization, size_t byte_limit, const int32_t *input, size_t input_cells,
    const int32_t *output, size_t output_cells);
int ax_host_validate(const ax_host *, uint64_t specialization, uint64_t h, uint64_t w, uint64_t scratch);
/* Only after fixed-specialization validation; never supplied by wire metadata. */
ax_alloc_status ax_host_scratch(ax_host *, ax_handle *);
int ax_host_acquire(const ax_host *, int32_t *input, size_t input_cells, int32_t *output, size_t output_cells);
void ax_host_destroy(ax_host *);
/* Include host_protocol.c AFTER unchanged generated.c and binding assertions.
 * Supply AX_CORE_PREFLIGHT/BODY, AX_FIXED_H/W/SCRATCH, AX_SPECIALIZATION.
 * ax_checked_invoke is static; helper names must never be protocol options. */
#endif
