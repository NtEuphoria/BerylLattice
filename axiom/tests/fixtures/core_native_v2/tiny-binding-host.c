/* B2 seam probe with B3 owned lifecycle; not a general production worker.
 * All stencil computations below are in unchanged real emit-c output. */
#include "generated.c"
#include "binding.h"
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "buffer_host.h"
#define AX_CORE_PREFLIGHT be_i_axiom_5fbuffer_5ffixture_2eax_5fpreflight
#define AX_CORE_BODY be_i_axiom_5fbuffer_5ffixture_2eax_5fbody
#define AX_FIXED_H 1
#define AX_FIXED_W 2
#define AX_FIXED_SCRATCH 6
#define AX_SPECIALIZATION UINT64_C(123)
#include "host_protocol.c"

static int read_values(int32_t values[8]) {
    char buffer[256];
    if (!fgets(buffer, sizeof buffer, stdin)) return 0;
    char *cursor = buffer;
    for (size_t i = 0; i < 8; ++i) {
        char *end;
        errno = 0;
        intmax_t value = strtoimax(cursor, &end, 10);
        if (errno || end == cursor || value < INT32_MIN || value > INT32_MAX) return 0;
        values[i] = (int32_t)value;
        cursor = end;
    }
    while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r' || *cursor == '\n') ++cursor;
    return *cursor == '\0' && fgetc(stdin) == EOF;
}

int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "invoke") != 0) return 64;
    int32_t values[8];
    if (!read_values(values)) return 65;
    ax_host host = {0};
    if (ax_host_prepare(&host,1,2,6,AX_SPECIALIZATION,56,values,6,values+6,2) != AX_PREPARED) return 66;
    ax_call call = ax_checked_invoke(&host,AX_SPECIALIZATION);
    if (call.status != AX_CALL_SUCCESS && call.status != AX_CALL_SOURCE_REJECTED) {
        ax_host_destroy(&host);
        return call.status == AX_CALL_RESOURCE ? 73 : call.status == AX_CALL_BOUNDARY ? 70 : 72;
    }
    /* Full acquisition after checked entry; independent Python comparison follows. */
    int32_t acquired_input[6], acquired_output[2];
    if (!ax_host_acquire(&host,acquired_input,6,acquired_output,2)) { ax_host_destroy(&host); return 74; }
    ax_host_destroy(&host);
    printf("{\"status\":\"%s\",\"first_bad_index\":", call.first_bad == -1
           ? "success" : "input_precondition_failed");
    if (call.first_bad == -1) printf("null");
    else printf("%" PRId32, call.first_bad);
    printf(",\"input\":[");
    for (size_t i = 0; i < 6; ++i) printf("%s%" PRId32, i ? "," : "", acquired_input[i]);
    printf("],\"output\":[");
    for (size_t i = 0; i < 2; ++i) printf("%s%" PRId32, i ? "," : "", acquired_output[i]);
    printf("],\"events\":[");
    for (size_t i = 0; i < call.event_count; ++i) printf("%s\"%s\"", i ? "," : "", call.events[i]);
    printf(",\"acquire\",\"input_output_free\"]");
    printf(",\"scratch_allocations\":%" PRIu64 ",\"scratch_live_bytes\":%zu,\"body_allocation_attempts\":%" PRIu64 "}\n",
           host.operation.allocations,host.operation.live_bytes,call.body_allocation_attempts);
    return 0;
}
