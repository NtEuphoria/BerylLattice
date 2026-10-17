/* Include in generated-C TU; actual pinned typedef, never a descriptor cast.
 * Private synchronous entry. B5 supplies admitted bindings/specialization;
 * transport, full acquisition/comparison and clocks remain B6/M2 obligations. */
#include "buffer_host.h"
#ifndef AX_CORE_PREFLIGHT
#error missing qualified Core binding
#endif
#ifndef AX_CORE_BODY
#error missing qualified Core body binding
#endif
#define AX_DESCRIPTOR_OK(d,r) ((d).data == (r)->base && (d).len == (r)->logical_cells && (d).cap == (r)->reserved_cells)
static ax_call ax_checked_invoke(ax_host *host, uint64_t specialization) {
    ax_call result={.status=AX_CALL_BOUNDARY,.first_bad=-1};
    if (specialization != AX_SPECIALIZATION ||
        !ax_host_validate(host,AX_SPECIALIZATION,AX_FIXED_H,AX_FIXED_W,AX_FIXED_SCRATCH)) return result;
    const ax_allocation *in=ax_lookup(&host->preparation,host->input);
    const ax_allocation *out=ax_lookup(&host->preparation,host->output);
    be_t_List_3ci32_3e input={in->base,in->logical_cells,in->reserved_cells};
    be_t_List_3ci32_3e output={out->base,out->logical_cells,out->reserved_cells};
    be_t_List_3ci32_3e scratch={NULL,0,0};
    ax_handle scratch_handle={0};
    const ax_allocation *owned_scratch=NULL;
    host->busy=1;
    result.events[result.event_count++]="preflight";
    result.first_bad=AX_CORE_PREFLIGHT(&input);
#ifdef AX_BUFFER_TESTING
    if (host->test_fault == 1) result.first_bad=-2;
#endif
    if (result.first_bad < -1 || result.first_bad >= in->logical_cells) {
        result.status=AX_CALL_INTEGRITY; goto cleanup;
    }
    if (result.first_bad != -1) { result.status=AX_CALL_SOURCE_REJECTED; goto descriptors; }
    ax_alloc_status allocated=ax_host_scratch(host,&scratch_handle);
    if (allocated != AX_ALLOC_OK) {
        result.status=allocated == AX_ALLOC_RESOURCE ? AX_CALL_RESOURCE : AX_CALL_INTEGRITY; goto descriptors;
    }
    if (scratch_handle.identity) {
        owned_scratch=ax_lookup(&host->operation,scratch_handle);
        if (!owned_scratch || owned_scratch->identity == in->identity || owned_scratch->identity == out->identity) {
            result.status=AX_CALL_INTEGRITY; goto cleanup;
        }
        scratch=(be_t_List_3ci32_3e){owned_scratch->base,owned_scratch->logical_cells,owned_scratch->reserved_cells};
    }
    if (scratch_handle.identity) {
        result.events[result.event_count++]="scratch_allocate";
        result.events[result.event_count++]="scratch_zero";
    }
    uint64_t before=host->operation.attempts;
    result.events[result.event_count++]="body";
#ifdef AX_TEST_BODY_START
    AX_TEST_BODY_START();
#endif
    AX_CORE_BODY(&input,&output,&scratch);
#ifdef AX_TEST_BODY_END
    AX_TEST_BODY_END();
#endif
    result.body_called=1; result.body_allocation_attempts=host->operation.attempts-before;
    result.status=result.body_allocation_attempts ? AX_CALL_INTEGRITY : AX_CALL_SUCCESS;
#ifdef AX_BUFFER_TESTING
    if (host->test_fault == 2) scratch.data=NULL;
    if (host->test_fault == 3) scratch.len=-1;
    if (host->test_fault == 4) output.cap=INT32_MAX;
    if (host->test_fault == 5) input.data=out->base;
#endif
descriptors:
    result.events[result.event_count++]="descriptors";
    if (!AX_DESCRIPTOR_OK(input,in) || !AX_DESCRIPTOR_OK(output,out) ||
        (owned_scratch ? !AX_DESCRIPTOR_OK(scratch,owned_scratch) :
         (scratch.data != NULL || scratch.len != 0 || scratch.cap != 0))) result.status=AX_CALL_INTEGRITY;
cleanup:
    if (scratch_handle.identity) {
        if (!ax_release(&host->operation,scratch_handle)) result.status=AX_CALL_INTEGRITY;
        result.events[result.event_count++]="scratch_free";
    }
    host->busy=0; return result;
}
#undef AX_DESCRIPTOR_OK
