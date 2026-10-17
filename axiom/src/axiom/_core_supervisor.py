"""Private Linux process supervisor. Run as its own Python process, never import to enable.

Subreaper semantics belong only to this process. Descendants cannot escape ownership
by setsid(), changing process groups, or orphaning themselves. pidfds prevent PID
reuse from redirecting a signal. Successful cleanup requires a final waitpid ECHILD.
This is process lifecycle isolation for the compiler, not a hostile-code sandbox.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def descendants(root: int) -> set[int]:
    parents = {}
    for item in Path('/proc').iterdir():
        if not item.name.isdecimal():
            continue
        try:
            # comm can include spaces and parentheses; the final ')' closes it.
            fields = (item / 'stat').read_text().rsplit(')', 1)[1].split()
            parents[int(item.name)] = int(fields[1])
        except (FileNotFoundError, ProcessLookupError):
            continue
    owned = {root}
    while True:
        additions = {pid for pid, parent in parents.items() if parent in owned} - owned
        if not additions:
            return owned - {root}
        owned.update(additions)


def send_owned(root: int, sig: int) -> None:
    for pid in descendants(root):
        try:
            fd = os.pidfd_open(pid)
        except ProcessLookupError:
            continue
        try:
            # Re-establish ancestry after obtaining the stable process handle.
            if pid in descendants(root):
                signal.pidfd_send_signal(fd, sig)
        except ProcessLookupError:
            pass
        finally:
            os.close(fd)


def reap() -> bool:
    """True only when kernel confirms this subreaper has no remaining children."""
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return True
        if pid == 0:
            return False


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text())
    receipt = Path(request['receipt'])
    result = {'returncode': None, 'timed_out': False, 'cleanup_verified': False,
              'cleanup_method': 'linux-subreaper-proc-pidfd', 'error': None,
              'forced_cleanup': False}
    process = None
    try:
        if sys.platform != 'linux' or not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            raise RuntimeError('Linux subreaper and pidfd support required')
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), 'Cannot enable child subreaper')
        setting = ctypes.c_int()
        if libc.prctl(37, ctypes.byref(setting), 0, 0, 0) != 0 or setting.value != 1:
            raise RuntimeError('Cannot verify child subreaper')
        # Verify proc ancestry visibility and pidfd signalling before launching Core.
        descendants(os.getpid())
        fd = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(fd, 0)
        finally:
            os.close(fd)
        cancelled = [False]
        signal.signal(signal.SIGTERM, lambda *_: cancelled.__setitem__(0, True))
        signal.signal(signal.SIGINT, lambda *_: cancelled.__setitem__(0, True))
        # The caller blocks SIGINT around spawning so cancellation cannot destroy
        # a half-created owner. Restore delivery only after our handlers exist.
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
        with open(request['stdout'], 'wb') as stdout, open(request['stderr'], 'wb') as stderr:
            process = subprocess.Popen(request['argv'], cwd=request['cwd'], stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            deadline = time.monotonic() + request['timeout_ms'] / 1000
            while process.poll() is None and time.monotonic() < deadline and not cancelled[0]:
                time.sleep(0.01)
            if process.poll() is None:
                result['timed_out'] = not cancelled[0]
                if cancelled[0]:
                    result['error'] = 'Supervisor was cancelled'
                # Core owns graceful process-group cancellation; give it first chance.
                process.terminate()
                until = time.monotonic() + 0.5
                while process.poll() is None and time.monotonic() < until:
                    time.sleep(0.01)
            result['returncode'] = process.poll()
            # Even normal Core exit must not leak a detached native descendant.
            if descendants(os.getpid()):
                result['forced_cleanup'] = True
            until = time.monotonic() + 3.0
            while time.monotonic() < until:
                send_owned(os.getpid(), signal.SIGSTOP)
                send_owned(os.getpid(), signal.SIGKILL)
                if process.returncode is None:
                    try:
                        result['returncode'] = process.wait(timeout=0.02)
                    except subprocess.TimeoutExpired:
                        continue
                if reap():
                    result['cleanup_verified'] = not descendants(os.getpid())
                    break
                time.sleep(0.01)
            if not result['cleanup_verified']:
                result['error'] = 'Owned descendant cleanup could not be verified'
    except (OSError, ValueError, RuntimeError) as exc:
        result['error'] = str(exc)
        # Never claim isolation when platform inspection failed. Only descendants
        # proven by the same ownership checks may be signalled in this fallback.
        if process is not None:
            try:
                send_owned(os.getpid(), signal.SIGKILL)
                process.wait(timeout=1)
                until = time.monotonic() + 1
                while not reap() and time.monotonic() < until:
                    send_owned(os.getpid(), signal.SIGKILL)
                    time.sleep(0.01)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
    receipt.write_text(json.dumps(result) + '\n')


if __name__ == '__main__':
    main()
