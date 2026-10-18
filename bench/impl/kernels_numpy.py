"""NumPy baseline: vectorized int64 array code."""
import sys

import numpy as np

from pyharness import run


def sq2x2(h, w, x):
    p = ((x + 1) ** 2).reshape(h + 1, w + 1)
    return p[:-1, :-1] + p[:-1, 1:] + p[1:, :-1] + p[1:, 1:]


def stencil1d3(n, _, x):
    return x[:-2] + 2 * x[1:-1] + x[2:]


def _taps(h, w, x, weights):
    g = x.reshape(h + 2, w + 2)
    out = np.zeros((h, w), dtype=np.int64)
    for i in range(3):
        for j in range(3):
            if weights[i][j]:
                out += weights[i][j] * g[i:i + h, j:j + w]
    return out


def box3x3(h, w, x):
    return _taps(h, w, x, ((1, 1, 1), (1, 1, 1), (1, 1, 1)))


def laplace5(h, w, x):
    return _taps(h, w, x, ((0, -1, 0), (-1, 4, -1), (0, -1, 0)))


def conv3x3(h, w, x):
    return _taps(h, w, x, ((1, 2, 1), (2, 4, 2), (1, 2, 1)))


def life(h, w, x):
    bits = x & 1
    n = _taps(h, w, bits, ((1, 1, 1), (1, 0, 1), (1, 1, 1)))
    alive = bits.reshape(h + 2, w + 2)[1:-1, 1:-1]
    return ((n == 3) | ((n == 2) & (alive == 1))).astype(np.int64)


def polymap(n, _, x):
    return x * x * x + 3 * x + 7


def transpose(h, w, x):
    return np.ascontiguousarray(x.reshape(h, w).T)


def maxpool2(h, w, x):
    return x.reshape(h, 2, w, 2).max(axis=(1, 3))


def total(n, _, x):
    return np.array([x.sum()])


def dot(n, _, x):
    return np.array([np.dot(x[:n], x[n:])])


def scan(n, _, x):
    return np.cumsum(x)


def hist(n, _, x):
    return np.bincount(x >> 4, minlength=64)


def matmul(n, _, x):
    return x[:n * n].reshape(n, n) @ x[n * n:].reshape(n, n)


KERNELS = dict(sq2x2=sq2x2, stencil1d3=stencil1d3, box3x3=box3x3, laplace5=laplace5,
               conv3x3=conv3x3, life=life, polymap=polymap, transpose=transpose,
               maxpool2=maxpool2, sum=total, dot=dot, scan=scan, hist=hist, matmul=matmul)

if __name__ == '__main__':
    sys.exit(run('numpy', KERNELS, prepare=lambda x: np.array(x, dtype=np.int64),
                 to_list=lambda out: np.asarray(out).ravel().tolist()))