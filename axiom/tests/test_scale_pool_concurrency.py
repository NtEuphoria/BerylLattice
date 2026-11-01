"""The worker pool under concurrent callers, and while idle.

A parallel kernel keeps its dispatch state (job pointers, chunk bounds, partial sums,
the claim counter) in process-wide statics, so the pool serializes whole kernel calls:
two threads calling one kernel at once must each get the exact single-threaded answer,
including calls that return early with a first-bad-index status. Between calls the
workers spin briefly, then block, so an idle pool costs (almost) no CPU time.

The native tests use a POSIX harness (pthreads, getrusage) and read CC; set
BERYL_POOL_CFLAGS to add flags, for example `-fsanitize=thread`.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from axiom.scale_c import compile_scale_native
from tests.test_scale_contract import ROW, fused
from tests.test_scale_family import MATMUL, SUM
from tests.test_scale_storage import DENSE

CC = os.environ.get('CC', 'clang')
EXTRA = os.environ.get('BERYL_POOL_CFLAGS', '').split()

# argv: mode n_in n_out lo hi [callers calls]. Four inputs: two in range, two with
# lo - 1 at n_in / 2 or at n_in - 1 (a first-bad-index status, an early return).
HARNESS = r'''
#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>
#ifndef BERYL_IN
#define BERYL_IN int32_t
#endif
#ifndef BERYL_OUT
#define BERYL_OUT int32_t
#endif
#define VARIANTS 4
#define MAX_CALLERS 8
int32_t beryl_kernel(const BERYL_IN *input, BERYL_OUT *output);

static long n_in, n_out, lo, hi, calls;
static BERYL_IN *inputs[VARIANTS];
static pthread_barrier_t start;
struct record { int32_t status; uint64_t digest; };
static struct record *logs[MAX_CALLERS];

static uint64_t digest(const BERYL_OUT *out) {
    uint64_t h = 1469598103934665603ull;
    for (long i = 0; i < n_out; i++) { h ^= (uint64_t)(int64_t)out[i]; h *= 1099511628211ull; }
    return h;
}

static struct record call(int v, BERYL_OUT *out) {
    for (long i = 0; i < n_out; i++) out[i] = (BERYL_OUT)7;
    struct record r;
    r.status = beryl_kernel(inputs[v], out);
    r.digest = r.status == 0 ? digest(out) : 0;  /* outputs are unspecified on rejection */
    return r;
}

static void *caller(void *arg) {
    long t = (long)(intptr_t)arg;
    BERYL_OUT *out = malloc((size_t)n_out * sizeof *out);
    pthread_barrier_wait(&start);
    for (long i = 0; i < calls; i++) logs[t][i] = call((int)((t + i) % VARIANTS), out);
    free(out);
    return NULL;
}

static double cpu_seconds(void) {
    struct rusage u;
    getrusage(RUSAGE_SELF, &u);
    return u.ru_utime.tv_sec + u.ru_stime.tv_sec + (u.ru_utime.tv_usec + u.ru_stime.tv_usec) * 1e-6;
}

int main(int argc, char **argv) {
    if (argc < 6) return 2;
    const char *mode = argv[1];
    n_in = atol(argv[2]); n_out = atol(argv[3]); lo = atol(argv[4]); hi = atol(argv[5]);
    long callers = argc > 6 ? atol(argv[6]) : 0;
    calls = argc > 7 ? atol(argv[7]) : 0;
    if (callers > MAX_CALLERS) return 2;
    uint32_t span = (uint32_t)(hi - lo + 1);
    for (int v = 0; v < VARIANTS; v++) {
        BERYL_IN *in = inputs[v] = malloc((size_t)n_in * sizeof *in);
        if (!in) return 3;
        for (long i = 0; i < n_in; i++) {
            uint32_t x = (uint32_t)i * 2654435761u + (uint32_t)v * 40503u;
            x ^= x >> 15; x *= 2246822519u; x ^= x >> 13;
            in[i] = (BERYL_IN)(lo + (long)(x % span));
        }
    }
    inputs[2][n_in / 2] = (BERYL_IN)(lo - 1);
    inputs[3][n_in - 1] = (BERYL_IN)(lo - 1);
    BERYL_OUT *out = malloc((size_t)n_out * sizeof *out);
    struct record expected[VARIANTS];
    if (strcmp(mode, "race") == 0) {
        /* Callers start together on a cold pool; the answers are checked afterwards. */
        pthread_t threads[MAX_CALLERS];
        pthread_barrier_init(&start, NULL, (unsigned)callers);
        for (long t = 0; t < callers; t++) {
            logs[t] = malloc((size_t)calls * sizeof *logs[t]);
            if (pthread_create(&threads[t], NULL, caller, (void *)(intptr_t)t) != 0) return 4;
        }
        for (long t = 0; t < callers; t++) pthread_join(threads[t], NULL);
        for (int v = 0; v < VARIANTS; v++) expected[v] = call(v, out);
        long wrong = 0;
        for (long t = 0; t < callers; t++)
            for (long i = 0; i < calls; i++) {
                struct record e = expected[(t + i) % VARIANTS], r = logs[t][i];
                wrong += r.status != e.status || r.digest != e.digest;
            }
        printf("wrong %ld of %ld\n", wrong, callers * calls);
    } else if (strcmp(mode, "idle") == 0) {
        /* One call starts the pool; then about a second of idleness, then calls again. */
        for (int v = 0; v < VARIANTS; v++) expected[v] = call(v, out);
        double before = cpu_seconds();
        struct timespec pause = {1, 0};
        nanosleep(&pause, NULL);
        printf("idle_cpu %.3f\n", cpu_seconds() - before);
        long wrong = 0;
        for (int round = 0; round < 3; round++) {
            for (int v = 0; v < VARIANTS; v++) {
                struct record r = call(v, out);
                wrong += r.status != expected[v].status || r.digest != expected[v].digest;
            }
            struct timespec gap = {0, 20000000};
            nanosleep(&gap, NULL);  /* long enough for the workers to block again */
        }
        printf("wrong %ld of %d\n", wrong, 3 * VARIANTS);
    } else {
        for (int v = 0; v < VARIANTS; v++) expected[v] = call(v, out);
    }
    for (int v = 0; v < VARIANTS; v++)
        printf("expect %d %d %016llx\n", v, expected[v].status, (unsigned long long)expected[v].digest);
    /* Freed so the ASan leak check reports only the kernel's own leaks. */
    for (long t = 0; t < callers && strcmp(mode, "race") == 0; t++) free(logs[t]);
    for (int v = 0; v < VARIANTS; v++) free(inputs[v]);
    free(out);
    return 0;
}
'''

# name: (source, abi, BERYL_IN, BERYL_OUT, lo, hi). Each is a parallel kernel: a split
# sum (partials), a matrix product and an int8 layer (parallel preflight, then cells),
# a fused row (checked block by block), and a split sum through ABI 2's ABI 1 wrapper.
PROGRAMS = {
    'sum': (SUM.format(n=1 << 21), None, 'int32_t', 'int32_t', 0, 1023),
    'matmul': (MATMUL.format(n=192), None, 'int32_t', 'int32_t', 0, 1023),
    'dense': (DENSE.format(w=256, n=1024), None, 'int8_t', 'int8_t', -127, 127),
    'row-fused': (fused(ROW.format(w=1 << 20)), None, 'int32_t', 'int32_t', 0, 1023),
    'sum-abi2': (SUM.format(n=1 << 21), 2, 'int32_t', 'int32_t', 0, 1023),
}


def artifact_of(name):
    source, abi, *_ = PROGRAMS[name]
    return compile_scale_native(source.encode(), abi=abi).artifact


class PoolSourceTests(unittest.TestCase):
    def test_parallel_kernels_carry_the_pool2_version(self):
        for name in PROGRAMS:
            artifact = artifact_of(name)
            with self.subTest(name=name):
                self.assertIn('-parallel-', artifact.codegen_version)
                self.assertIn('pool2', artifact.codegen_version)
        serial = compile_scale_native(SUM.format(n=5000).encode()).artifact
        self.assertNotIn('pool2', serial.codegen_version)
        self.assertNotIn(b'beryl_pool', serial.c_source)

    def test_the_whole_call_holds_the_pool_lock(self):
        # beryl_pool() takes the process-wide lock; the cleanup releases it on every
        # return path of the kernel, early first-bad-index returns included.
        for name in PROGRAMS:
            c = artifact_of(name).c_source
            with self.subTest(name=name):
                self.assertEqual(c.count(b'int threads __attribute__((cleanup(beryl_pool_leave))) = beryl_pool();'), 1)
                self.assertIn(b'pthread_mutex_lock(&beryl_call_lock)', c)
                self.assertIn(b'AcquireSRWLockExclusive(&beryl_call_lock)', c)
                self.assertIn(b'pthread_cond_wait(', c)
                self.assertIn(b'SleepConditionVariableSRW(', c)
                self.assertNotIn(b'beryl_yield', c)

    def test_the_kernel_compiles_for_this_host(self):
        # Compile only (no executable is produced or launched): on Windows this checks
        # the SRW lock and condition variable branch, elsewhere the pthread branch.
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('sum', 'dense'):
                c = Path(tmp) / f'{name}.c'
                c.write_bytes(artifact_of(name).c_source)
                try:
                    built = subprocess.run([CC, '-O2', '-std=c11', '-Wall', '-Werror', '-pthread', '-c', str(c),
                                            '-o', str(Path(tmp) / f'{name}.o')], capture_output=True, text=True)
                except OSError as error:
                    self.skipTest(f'no C compiler: {error}')
                with self.subTest(name=name):
                    self.assertEqual(built.returncode, 0, built.stderr)


@unittest.skipIf(os.name == 'nt', 'the harness is POSIX (pthreads, getrusage); run it in WSL')
class PoolNativeTests(unittest.TestCase):
    def build(self, tmp, name):
        source, abi, in_t, out_t, lo, hi = PROGRAMS[name]
        artifact = artifact_of(name)
        kernel = Path(tmp) / f'{name}.c'
        kernel.write_bytes(artifact.c_source.replace(b'int main(void)', b'int beryl_unused_main(void)'))
        harness = Path(tmp) / 'harness.c'
        harness.write_text(HARNESS)
        exe = Path(tmp) / f'{name}.exe'
        try:
            built = subprocess.run([CC, '-O2', '-march=native', '-std=c11', '-Wall', '-Werror', '-pthread', *EXTRA,
                                    f'-DBERYL_IN={in_t}', f'-DBERYL_OUT={out_t}', str(kernel), str(harness),
                                    '-o', str(exe)], capture_output=True, text=True)
        except OSError as error:
            self.skipTest(f'no C compiler: {error}')
        self.assertEqual(built.returncode, 0, built.stderr)  # a compile error is a failure, not a skip
        return exe, artifact.input_count, artifact.output_count, lo, hi

    def run_exe(self, exe, args, threads, timeout=300):
        env = dict(os.environ, BERYL_THREADS=threads)
        try:
            ran = subprocess.run([str(exe), *map(str, args)], capture_output=True, text=True, env=env,
                                 timeout=timeout)
        except OSError as error:  # Windows Application Control; never bypassed
            self.skipTest(f'executable launch refused: {error}')
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        self.assertNotIn('ThreadSanitizer', ran.stderr, ran.stderr)
        return ran.stdout.split('\n')

    def expectations(self, lines):
        return [line for line in lines if line.startswith('expect ')]

    def test_concurrent_callers_get_exact_results(self):
        calls = int(os.environ.get('BERYL_POOL_CALLS', '24'))
        with tempfile.TemporaryDirectory() as tmp:
            for name in PROGRAMS:
                exe, n_in, n_out, lo, hi = self.build(tmp, name)
                serial = self.expectations(self.run_exe(exe, ['seq', n_in, n_out, lo, hi], '1'))
                # Two of the four inputs are rejected, so early returns must release the lock.
                self.assertEqual([line.split()[2] != '0' for line in serial], [False, False, True, True], serial)
                for callers in (2, 4):
                    lines = self.run_exe(exe, ['race', n_in, n_out, lo, hi, callers, calls], '4')
                    with self.subTest(name=name, callers=callers):
                        self.assertIn(f'wrong 0 of {callers * calls}', lines)
                        self.assertEqual(self.expectations(lines), serial)

    def test_idle_workers_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe, n_in, n_out, lo, hi = self.build(tmp, 'sum')
            serial = self.expectations(self.run_exe(exe, ['seq', n_in, n_out, lo, hi], '1'))
            lines = self.run_exe(exe, ['idle', n_in, n_out, lo, hi], '4')
            idle = float(next(line for line in lines if line.startswith('idle_cpu')).split()[1])
            # Three spinning workers burn about three CPU-seconds here; blocked ones, none.
            self.assertLess(idle, 0.2, lines)
            self.assertIn('wrong 0 of 12', lines)  # woken workers still compute exactly
            self.assertEqual(self.expectations(lines), serial)


if __name__ == '__main__':
    unittest.main()
