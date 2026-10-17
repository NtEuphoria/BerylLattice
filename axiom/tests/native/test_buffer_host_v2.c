/* Actual unchanged emit-c output and exact binding assertions precede the host. */
#include "generated.c"
#include "binding.h"
#include "buffer_host.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#ifdef AX_ALLOC_INTERPOSE
#include <sys/mman.h>
static size_t wrapped_allocations, wrapped_frees, body_allocations;
static size_t body_start;
static int inject_body_allocation;
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
void *__real_realloc(void *, size_t);
void __real_free(void *);
void *__real_aligned_alloc(size_t, size_t);
int __real_posix_memalign(void **, size_t, size_t);
void *__wrap_malloc(size_t n) { ++wrapped_allocations; return __real_malloc(n); }
void *__wrap_calloc(size_t n, size_t s) { ++wrapped_allocations; return __real_calloc(n,s); }
void *__wrap_realloc(void *p, size_t n) { ++wrapped_allocations; return __real_realloc(p,n); }
void __wrap_free(void *p) { if(p) ++wrapped_frees; __real_free(p); }
void *__wrap_aligned_alloc(size_t a, size_t n) { ++wrapped_allocations; return __real_aligned_alloc(a,n); }
int __wrap_posix_memalign(void **p, size_t a, size_t n) { ++wrapped_allocations; return __real_posix_memalign(p,a,n); }
#define AX_TEST_BODY_START() do { \
    body_start = wrapped_allocations; \
    if (inject_body_allocation) { void *p = malloc(11); assert(p); free(p); } \
} while (0)
#define AX_TEST_BODY_END() (body_allocations += wrapped_allocations - body_start)
static void interception_control(void) {
    size_t before = wrapped_allocations;
    void *p = malloc(17); assert(p); p = realloc(p, 29); assert(p); free(p);
    p = calloc(2, 17); assert(p); free(p);
    p = aligned_alloc(16, 32); assert(p); free(p);
    assert(posix_memalign(&p, 16, 32) == 0); free(p);
    assert(wrapped_allocations - before == 5);
    /* Explicit uncovered direct syscall path: wrapping is NOT general coverage. */
    before = wrapped_allocations;
    p = mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
    assert(p != MAP_FAILED); assert(munmap(p,4096) == 0);
    assert(wrapped_allocations == before);
}
#endif
#define AX_CORE_PREFLIGHT be_i_axiom_5fbuffer_5ffixture_2eax_5fpreflight
#define AX_CORE_BODY be_i_axiom_5fbuffer_5ffixture_2eax_5fbody
#define AX_FIXED_H 1
#define AX_FIXED_W 2
#define AX_FIXED_SCRATCH 6
#define AX_SPECIALIZATION UINT64_C(123)
#include "host_protocol.c"

static const int32_t input[6] = {0,1,2,3,4,5};
static const int32_t sentinels[2] = {-99,77};
static void acquire_compare(ax_host *host, ax_call result, const int32_t expected_input[6], int valid) {
    int32_t actual_input[6], actual_output[2];
    assert(ax_host_acquire(host, actual_input, 6, actual_output, 2));
    assert(memcmp(actual_input, expected_input, sizeof actual_input) == 0);
    if (valid) {
        /* Independent hand fixture expectations, no host/generated computation. */
        assert(result.status == AX_CALL_SUCCESS);
        assert(actual_output[0] == 46 && actual_output[1] == 74);
    } else assert(memcmp(actual_output, sentinels, sizeof actual_output) == 0);
    assert(host->operation.live_allocations == 0 && host->operation.live_bytes == 0);
}
static void prepare(ax_host *h, const int32_t *values) {
    assert(ax_host_prepare(h, 1, 2, 6, AX_SPECIALIZATION, 56, values, 6, sentinels, 2) == AX_PREPARED);
}
static void sanitizer_fault(const char *kind) {
    ax_host host = {0}; prepare(&host,input);
    if (strcmp(kind,"leak") == 0) return; /* Deliberately omit owner cleanup. */
    if (strcmp(kind,"uaf") == 0) {
        volatile int32_t *p = ax_lookup(&host.preparation,host.input)->base;
        ax_host_destroy(&host);
        printf("%d\n",*p); /* Deliberate host-owner lifetime violation. */
    } else if (strcmp(kind,"overflow") == 0) {
        volatile int32_t n = INT32_MAX;
        host.shape.input_cells = n + 1; /* Deliberate unchecked host-size violation. */
        printf("%d\n",host.shape.input_cells);
        ax_host_destroy(&host);
    } else { ax_host_destroy(&host); assert(0); }
}
int main(int argc, char **argv) {
    if (argc == 3 && strcmp(argv[1],"sanitizer-fault") == 0) { sanitizer_fault(argv[2]); return 0; }
#ifdef AX_ALLOC_INTERPOSE
    if (argc == 2 && strcmp(argv[1],"unexpected-body-allocation") == 0) inject_body_allocation = 1;
    interception_control();
#endif
    for (uint64_t ordinal = 1; ordinal <= 2; ++ordinal) {
        ax_host host = {0}; ax_test_fail_at(&host.preparation, ordinal);
        assert(ax_host_prepare(&host,1,2,6,AX_SPECIALIZATION,56,input,6,sentinels,2) == AX_PREPARATION_RESOURCE);
        assert(!host.prepared && host.preparation.live_bytes == 0);
        assert(host.operation.attempts == 0);
        ax_host_destroy(&host);
    }
    for (int i = 0; i < 120; ++i) {
        ax_host host = {0}; int32_t values[6]; memcpy(values,input,sizeof values);
        if (i % 3 == 1) { values[1] = -1; values[5] = 1024; }
        prepare(&host, values);
        if (i % 3) ax_test_fail_at(&host.operation,1);
#ifdef AX_ALLOC_INTERPOSE
        size_t before = wrapped_allocations;
#endif
        ax_call result = ax_checked_invoke(&host, AX_SPECIALIZATION);
        assert(result.status == (i%3==0 ? AX_CALL_SUCCESS : i%3==1 ? AX_CALL_SOURCE_REJECTED : AX_CALL_RESOURCE));
        assert(result.first_bad == (i%3==1 ? 1 : -1));
        assert(result.body_called == (i%3==0));
        assert(host.operation.attempts == (i%3==1 ? 0 : 1));
        assert(result.body_allocation_attempts == 0);
#ifdef AX_ALLOC_INTERPOSE
        assert(wrapped_allocations-before == (i%3==0 ? 1u : 0u));
#endif
        acquire_compare(&host,result,values,i%3==0);
        ax_host_destroy(&host);
        assert(!host.prepared && host.preparation.live_bytes == 0);
        assert(host.preparation.allocations == host.preparation.frees);
    }
    /* Reuse one live preparation; each call must return scratch to baseline. */
    ax_host reused = {0}; prepare(&reused,input);
    for (int n = 0; n < 100; ++n) {
        if (n % 2) ax_test_fail_at(&reused.operation,reused.operation.attempts + 1);
        else ax_test_fail_at(&reused.operation,0);
        ax_call call = ax_checked_invoke(&reused,AX_SPECIALIZATION);
        assert(call.status == (n % 2 ? AX_CALL_RESOURCE : AX_CALL_SUCCESS));
        int32_t ai[6], ao[2]; assert(ax_host_acquire(&reused,ai,6,ao,2));
        assert(memcmp(ai,input,sizeof ai) == 0 && ao[0] == 46 && ao[1] == 74);
        assert(reused.operation.live_bytes == 0 && reused.operation.live_allocations == 0);
    }
    assert(reused.operation.allocations == 50 && reused.operation.frees == 50);
    ax_host_destroy(&reused);
    ax_host h = {0}; prepare(&h,input);
    ax_handle stale = h.input;
    ax_host_destroy(&h); prepare(&h,input);
    ax_handle current = h.input; h.input = stale;
    assert(ax_checked_invoke(&h,AX_SPECIALIZATION).status == AX_CALL_BOUNDARY);
    h.input = current;
    assert(ax_checked_invoke(&h,999).status == AX_CALL_BOUNDARY);
    ax_handle output = h.output; h.output = h.input;
    assert(ax_checked_invoke(&h,AX_SPECIALIZATION).status == AX_CALL_BOUNDARY); h.output = output;
    ax_allocation *r = &h.preparation.records[h.input.slot];
    r->initialized_cells = 5;
    assert(ax_checked_invoke(&h,AX_SPECIALIZATION).status == AX_CALL_BOUNDARY); r->initialized_cells = 6;
    r->logical_cells = INT32_MAX;
    assert(ax_checked_invoke(&h,AX_SPECIALIZATION).status == AX_CALL_BOUNDARY); r->logical_cells = 6;
    h.shape.input_cells = -1;
    assert(ax_checked_invoke(&h,AX_SPECIALIZATION).status == AX_CALL_BOUNDARY); h.shape.input_cells = 6;
    assert(h.operation.attempts == 0);
    ax_host_destroy(&h);
    for (int fault = 1; fault <= 5; ++fault) {
        ax_host host = {0}; prepare(&host,input); host.test_fault = fault;
        ax_call result = ax_checked_invoke(&host,AX_SPECIALIZATION);
        assert(result.status == AX_CALL_INTEGRITY);
        assert(host.operation.live_bytes == 0 && host.operation.allocations == host.operation.frees);
        assert(result.body_called == (fault != 1));
        int32_t ai[6], ao[2]; assert(ax_host_acquire(&host, ai,6,ao,2));
        assert(memcmp(ai,input,sizeof ai)==0);
        assert(ao[0] == (fault==1 ? -99 : 46) && ao[1] == (fault==1 ? 77 : 74));
        ax_host_destroy(&host);
    }
    /* Zero scratch lifecycle (no alternate Core body / no semantic invocation). */
    ax_host zero = {0};
    assert(ax_host_prepare(&zero,1,2,0,123,32,input,6,sentinels,2) == AX_PREPARED);
    ax_handle empty = {0};
    assert(ax_host_scratch(&zero,&empty) == AX_ALLOC_OK && empty.identity == 0);
    assert(zero.operation.attempts == 0 && zero.operation.live_bytes == 0);
    ax_host_destroy(&zero);
#ifdef AX_ALLOC_INTERPOSE
    assert(body_allocations == 0);
    assert(wrapped_allocations == wrapped_frees + 1); /* realloc keeps one live allocation */
    puts("interposition: five malloc-family controls; body=0; mmap explicitly uncovered");
#endif
    puts("host: 120 valid/rejected/OOM + 100 reused-preparation calls; stale/boundary/5 corruption controls; complete comparisons; cleanup balanced");
    return 0;
}
