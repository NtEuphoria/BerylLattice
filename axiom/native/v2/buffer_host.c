#include "buffer_host.h"
#include <string.h>
int ax_shape_checked(uint64_t h, uint64_t w, uint64_t scratch, size_t limit, ax_shape *s) {
    if (!s || h == 0 || w == 0 || h > 8192 || w > 8192) return 0;
    /* Products bounded by 8193^2 in uint64_t, before narrowing. */
    uint64_t p = (h+1)*(w+1), q = h*w;
    size_t ib,ob,sb,total;
    if (p > (UINT64_C(1)<<23) || scratch > p ||
        !ax_i32_bytes(p,limit,&ib) || !ax_i32_bytes(q,limit,&ob) ||
        !ax_i32_bytes(scratch,limit,&sb) || !ax_size_add(ib,ob,&total) ||
        !ax_size_add(total,sb,&total) || total > limit) return 0;
    *s = (ax_shape){(uint32_t)h,(uint32_t)w,(int32_t)p,(int32_t)q,(int32_t)scratch,ib,ob,sb,total}; return 1;
}
static int ax_record_valid(const ax_allocation *r, ax_role role, int32_t cells, size_t bytes) {
    return r && r->role == role && r->base && r->logical_cells == cells &&
        r->reserved_cells == cells && r->initialized_cells == cells && r->bytes == bytes &&
        r->alignment == _Alignof(int32_t) && (uintptr_t)r->base % _Alignof(int32_t) == 0;
}
ax_preparation ax_host_prepare(ax_host *h, uint64_t height, uint64_t width, uint64_t scratch,
    uint64_t spec, size_t limit, const int32_t *input, size_t ni, const int32_t *output, size_t no) {
    ax_shape s;
    if (!h || h->prepared || h->busy || h->preparation.live_allocations ||
        h->operation.live_allocations || !spec || !input || !output ||
        !ax_shape_checked(height,width,scratch,limit,&s) || ni != (size_t)s.input_cells || no != (size_t)s.output_cells)
        return AX_PREPARATION_BOUNDARY;
    h->shape=s; h->specialization=spec; h->byte_limit=limit;
    ax_preparation result=AX_PREPARATION_RESOURCE;
    if (ax_allocate(&h->preparation,AX_INPUT,ni,s.input_bytes,&h->input) != AX_ALLOC_OK) goto cleanup;
    if (ax_allocate(&h->preparation,AX_OUTPUT,no,s.output_bytes,&h->output) != AX_ALLOC_OK) goto cleanup;
    if (!ax_initialize_copy(&h->preparation,h->input,input,ni) || !ax_initialize_copy(&h->preparation,h->output,output,no)) {
        result=AX_PREPARATION_BOUNDARY; goto cleanup;
    }
    h->prepared=1; return AX_PREPARED;
cleanup:
    ax_host_destroy(h); return result;
}
int ax_host_validate(const ax_host *h, uint64_t spec, uint64_t height, uint64_t width, uint64_t scratch) {
    ax_shape s;
    if (!h || !h->prepared || h->busy || !spec || h->specialization != spec ||
        !ax_shape_checked(height,width,scratch,h->byte_limit,&s)) return 0;
    const ax_shape *r=&h->shape;
    if (r->height != s.height || r->width != s.width || r->input_cells != s.input_cells ||
        r->output_cells != s.output_cells || r->scratch_cells != s.scratch_cells ||
        r->input_bytes != s.input_bytes || r->output_bytes != s.output_bytes ||
        r->scratch_bytes != s.scratch_bytes || r->total_bytes != s.total_bytes) return 0;
    const ax_allocation *i=ax_lookup(&h->preparation,h->input), *o=ax_lookup(&h->preparation,h->output);
    return h->preparation.live_allocations == 2 && h->operation.live_allocations == 0 &&
        h->operation.live_bytes == 0 && h->input.identity != h->output.identity &&
        ax_record_valid(i,AX_INPUT,s.input_cells,s.input_bytes) && ax_record_valid(o,AX_OUTPUT,s.output_cells,s.output_bytes);
}
ax_alloc_status ax_host_scratch(ax_host *h, ax_handle *handle) {
    if (!h || !handle || !h->prepared || h->operation.live_allocations || h->shape.scratch_cells < 0) return AX_ALLOC_INVALID;
    *handle=(ax_handle){0};
    if (!h->shape.scratch_cells) return AX_ALLOC_OK;
    ax_alloc_status s=ax_allocate(&h->operation,AX_SCRATCH,(uint64_t)h->shape.scratch_cells,h->shape.scratch_bytes,handle);
    if (s != AX_ALLOC_OK) return s;
    if (!ax_initialize_zero(&h->operation,*handle)) { ax_release(&h->operation,*handle); *handle=(ax_handle){0}; return AX_ALLOC_INVALID; }
    return AX_ALLOC_OK;
}
int ax_host_acquire(const ax_host *h, int32_t *input, size_t ni, int32_t *output, size_t no) {
    if (!h || h->busy || !input || !output ||
        !ax_host_validate(h,h->specialization,h->shape.height,h->shape.width,(uint64_t)h->shape.scratch_cells) ||
        ni != (size_t)h->shape.input_cells || no != (size_t)h->shape.output_cells) return 0;
    const ax_allocation *i=ax_lookup(&h->preparation,h->input), *o=ax_lookup(&h->preparation,h->output);
    memcpy(input,i->base,i->bytes); memcpy(output,o->base,o->bytes); return 1;
}
void ax_host_destroy(ax_host *h) {
    if (!h) return;
    ax_allocator_destroy(&h->operation); ax_allocator_destroy(&h->preparation);
    h->input=(ax_handle){0}; h->output=(ax_handle){0}; h->prepared=0; h->busy=0;
}
