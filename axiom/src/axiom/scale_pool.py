"""The persistent worker pool shared by parallel scale-v1 kernels (C source)."""

_POOL = r'''
/* Persistent worker pool. Workers start on the first parallel call, then wait
 * for work. A dispatch cuts its range into about four chunks per thread; every
 * thread, the caller included, claims chunks from one atomic counter until
 * none are left, and the dispatch returns once every chunk has finished. A
 * preempted worker therefore delays a dispatch only while holding a chunk.
 * Chunks are disjoint ranges of output cells (or inputs, for the preflight).
 * The claim counter holds (chunk count << 32 | next index), so a worker always
 * reads the count of the dispatch whose job it then runs. BERYL_THREADS=n caps
 * the pool; 1 disables it.
 *
 * The job state below is shared by every caller, so beryl_pool() takes a
 * process-wide lock (statically initialized) that the kernel holds until it
 * returns: beryl_pool_leave runs on every return path. A one-thread pool shares
 * nothing and releases the lock at once. Waiting threads (idle workers, and a
 * caller whose chunks are still running elsewhere) spin for a bounded time,
 * then sleep on a condition variable. A sleeper announces itself (a counter or
 * flag) under beryl_wait_lock before it re-checks the word it waits on; the
 * waker changes that word, then reads the announcement, both sequentially
 * consistent, so at least one of them sees the other and no wakeup is lost. */
#include <stdatomic.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <pthread.h>
#include <unistd.h>
#endif
#define BERYL_MAX_THREADS 16
#define BERYL_MAX_CHUNKS 64
#define BERYL_SPINS (1u << 14)
static const int32_t *beryl_job_input;
static int32_t *beryl_job_output;
static int beryl_job_phase;
static int beryl_job_chunks;
static int64_t beryl_job_begin[BERYL_MAX_CHUNKS + 1];
static uint32_t beryl_job_invalid[BERYL_MAX_CHUNKS];
static int32_t beryl_job_partial[BERYL_MAX_CHUNKS] __attribute__((unused));
static atomic_ullong beryl_claim;
static atomic_uint beryl_generation;
static atomic_uint beryl_done;
static atomic_uint beryl_sleepers;      /* workers asleep (or about to be) on beryl_wake */
static atomic_uint beryl_caller_waits;  /* the caller asleep (or about to be) on beryl_finished */
static int beryl_threads = 1;
static int beryl_pool_ready;
#ifdef _WIN32
typedef CONDITION_VARIABLE beryl_cond;
static SRWLOCK beryl_call_lock = SRWLOCK_INIT;
static SRWLOCK beryl_wait_lock = SRWLOCK_INIT;
static CONDITION_VARIABLE beryl_wake = CONDITION_VARIABLE_INIT;
static CONDITION_VARIABLE beryl_finished = CONDITION_VARIABLE_INIT;
#else
typedef pthread_cond_t beryl_cond;
static pthread_mutex_t beryl_call_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t beryl_wait_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t beryl_wake = PTHREAD_COND_INITIALIZER;
static pthread_cond_t beryl_finished = PTHREAD_COND_INITIALIZER;
#endif

static void beryl_pause(void) {
#if defined(__x86_64__) || defined(__i386__)
    __builtin_ia32_pause();
#endif
}

static void beryl_wait_enter(void) {
#ifdef _WIN32
    AcquireSRWLockExclusive(&beryl_wait_lock);
#else
    pthread_mutex_lock(&beryl_wait_lock);
#endif
}

static void beryl_wait_leave(void) {
#ifdef _WIN32
    ReleaseSRWLockExclusive(&beryl_wait_lock);
#else
    pthread_mutex_unlock(&beryl_wait_lock);
#endif
}

/* Sleep on `cond`, holding beryl_wait_lock (released while asleep). */
static void beryl_sleep(beryl_cond *cond) {
#ifdef _WIN32
    SleepConditionVariableSRW(cond, &beryl_wait_lock, INFINITE, 0);
#else
    pthread_cond_wait(cond, &beryl_wait_lock);
#endif
}

static void beryl_wake_all(beryl_cond *cond) {
    beryl_wait_enter();
#ifdef _WIN32
    WakeAllConditionVariable(cond);
#else
    pthread_cond_broadcast(cond);
#endif
    beryl_wait_leave();
}

static void beryl_run_chunk(int c);

/* Claim and run chunks of the current dispatch until none are left. */
static void beryl_claim_chunks(void) {
    for (;;) {
        unsigned long long v = atomic_fetch_add_explicit(&beryl_claim, 1ull, memory_order_acq_rel);
        unsigned index = (unsigned)(v & 0xffffffffull), count = (unsigned)(v >> 32);
        if (index >= count) return;
        beryl_run_chunk((int)index);
        /* The last chunk wakes a caller that went to sleep waiting for it. */
        if (atomic_fetch_add(&beryl_done, 1u) + 1u == count && atomic_load(&beryl_caller_waits))
            beryl_wake_all(&beryl_finished);
    }
}

/* Wait (spin, then sleep) for a generation other than `seen`, and return it. */
static unsigned beryl_next_generation(unsigned seen) {
    unsigned now;
    for (unsigned spins = 0; spins < BERYL_SPINS; ++spins) {
        if ((now = atomic_load_explicit(&beryl_generation, memory_order_acquire)) != seen) return now;
        beryl_pause();
    }
    beryl_wait_enter();
    atomic_fetch_add(&beryl_sleepers, 1u);
    while ((now = atomic_load(&beryl_generation)) == seen) beryl_sleep(&beryl_wake);
    atomic_fetch_sub(&beryl_sleepers, 1u);
    beryl_wait_leave();
    return now;
}

#ifdef _WIN32
static DWORD WINAPI beryl_worker(LPVOID arg)
#else
static void *beryl_worker(void *arg)
#endif
{
    unsigned seen = (unsigned)(uintptr_t)arg;
    for (;;) {
        seen = beryl_next_generation(seen);
        beryl_claim_chunks();
    }
#ifndef _WIN32
    return NULL;
#endif
}

static void beryl_call_leave(void) {
#ifdef _WIN32
    ReleaseSRWLockExclusive(&beryl_call_lock);
#else
    pthread_mutex_unlock(&beryl_call_lock);
#endif
}

/* Start the pool once, and take the call lock while it has workers. The kernel
 * stores the result in a variable with cleanup(beryl_pool_leave), which drops
 * the lock on every return path. */
static int beryl_pool_start(void);
static int beryl_pool(void) {
#ifdef _WIN32
    AcquireSRWLockExclusive(&beryl_call_lock);
#else
    pthread_mutex_lock(&beryl_call_lock);
#endif
    int threads = beryl_pool_ready ? beryl_threads : beryl_pool_start();
    if (threads == 1) beryl_call_leave();
    return threads;
}

static void beryl_pool_leave(int *threads) {
    if (*threads > 1) beryl_call_leave();
}

static int beryl_pool_start(void) {
    beryl_pool_ready = 1;
    long logical;
#ifdef _WIN32
    SYSTEM_INFO info;
    GetSystemInfo(&info);
    logical = (long)info.dwNumberOfProcessors;
#else
    logical = sysconf(_SC_NPROCESSORS_ONLN);
#endif
    /* Leave one logical processor for the rest of the system. */
    long want = logical > 2 ? logical - 1 : logical;
    const char *cap = getenv("BERYL_THREADS");
    if (cap && *cap) {
        long c = strtol(cap, NULL, 10);
        if (c >= 1 && c <= logical) want = c;
    }
    if (want < 1) want = 1;
    if (want > BERYL_MAX_THREADS) want = BERYL_MAX_THREADS;
    /* Workers start from the generation before any dispatch, so a worker that
     * starts late still runs the first dispatch. */
    unsigned start = atomic_load_explicit(&beryl_generation, memory_order_relaxed);
    for (long t = 1; t < want; ++t) {
#ifdef _WIN32
        HANDLE h = CreateThread(NULL, 0, beryl_worker, (LPVOID)(uintptr_t)start, 0, NULL);
        if (!h) break;
        CloseHandle(h);
#else
        pthread_t h;
        if (pthread_create(&h, NULL, beryl_worker, (void *)(uintptr_t)start) != 0) break;
        pthread_detach(h);
#endif
        beryl_threads = (int)t + 1;
    }
    return beryl_threads;
}

/* Cut [0, total) into `align`-aligned chunks (about `per_thread` per thread),
 * run them on the pool, and wait for all. */
static void beryl_dispatch(int phase, int64_t total, int64_t align, int per_thread,
                           const int32_t *input, int32_t *output) {
    int chunks = beryl_threads * per_thread;
    if (chunks > BERYL_MAX_CHUNKS) chunks = BERYL_MAX_CHUNKS;
    int64_t step = (total + chunks - 1) / chunks;
    step = (step + align - 1) / align * align;
    if (step < align) step = align;
    chunks = (int)((total + step - 1) / step);
    if (chunks < 1) chunks = 1;
    for (int c = 0; c <= chunks; ++c) {
        int64_t at = (int64_t)c * step;
        beryl_job_begin[c] = at < total ? at : total;
    }
    beryl_job_input = input;
    beryl_job_output = output;
    beryl_job_phase = phase;
    beryl_job_chunks = chunks;
    atomic_store_explicit(&beryl_done, 0u, memory_order_relaxed);
    atomic_store_explicit(&beryl_claim, (unsigned long long)chunks << 32, memory_order_release);
    atomic_fetch_add(&beryl_generation, 1u);
    if (atomic_load(&beryl_sleepers)) beryl_wake_all(&beryl_wake);
    beryl_claim_chunks();
    for (unsigned spins = 0; spins < BERYL_SPINS; ++spins) {
        if (atomic_load_explicit(&beryl_done, memory_order_acquire) >= (unsigned)chunks) return;
        beryl_pause();
    }
    beryl_wait_enter();
    atomic_store(&beryl_caller_waits, 1u);
    while (atomic_load(&beryl_done) < (unsigned)chunks) beryl_sleep(&beryl_finished);
    atomic_store(&beryl_caller_waits, 0u);
    beryl_wait_leave();
}
'''
