"""Pure-Python baseline: idiomatic loops, no third-party packages."""
import sys

from pyharness import run


def sq2x2(h, w, x):
    cols = w + 1
    p = [(v + 1) * (v + 1) for v in x]
    out = []
    for r in range(h):
        top, bot = r * cols, (r + 1) * cols
        for c in range(w):
            out.append(p[top + c] + p[top + c + 1] + p[bot + c] + p[bot + c + 1])
    return out


def stencil1d3(n, _, x):
    return [x[i] + 2 * x[i + 1] + x[i + 2] for i in range(n)]


def _window(h, w, x, cell):
    cols = w + 2
    out = []
    for r in range(h):
        r0, r1, r2 = r * cols, (r + 1) * cols, (r + 2) * cols
        for c in range(w):
            out.append(cell(x, r0 + c, r1 + c, r2 + c))
    return out


def box3x3(h, w, x):
    return _window(h, w, x, lambda x, a, b, c: (x[a] + x[a + 1] + x[a + 2] + x[b] + x[b + 1]
                                                 + x[b + 2] + x[c] + x[c + 1] + x[c + 2]))


def laplace5(h, w, x):
    return _window(h, w, x, lambda x, a, b, c: 4 * x[b + 1] - x[a + 1] - x[c + 1] - x[b] - x[b + 2])


def conv3x3(h, w, x):
    return _window(h, w, x, lambda x, a, b, c: (x[a] + 2 * x[a + 1] + x[a + 2] + 2 * x[b]
                                                 + 4 * x[b + 1] + 2 * x[b + 2] + x[c]
                                                 + 2 * x[c + 1] + x[c + 2]))


def life(h, w, x):
    bits = [v & 1 for v in x]

    def cell(_, a, b, c):
        n = (bits[a] + bits[a + 1] + bits[a + 2] + bits[b] + bits[b + 2]
             + bits[c] + bits[c + 1] + bits[c + 2])
        return 1 if n == 3 or (n == 2 and bits[b + 1]) else 0
    return _window(h, w, x, cell)


def polymap(n, _, x):
    return [v * v * v + 3 * v + 7 for v in x]


def transpose(h, w, x):
    return [x[r * w + c] for c in range(w) for r in range(h)]


def maxpool2(h, w, x):
    cols = 2 * w
    out = []
    for r in range(h):
        top, bot = 2 * r * cols, (2 * r + 1) * cols
        for c in range(w):
            j = 2 * c
            out.append(max(x[top + j], x[top + j + 1], x[bot + j], x[bot + j + 1]))
    return out


def total(n, _, x):
    return [sum(x)]


def dot(n, _, x):
    return [sum(p * q for p, q in zip(x[:n], x[n:]))]


def scan(n, _, x):
    out, acc = [], 0
    for v in x:
        acc += v
        out.append(acc)
    return out


def hist(n, _, x):
    bins = [0] * 64
    for v in x:
        bins[v >> 4] += 1
    return bins


def matmul(n, _, x):
    A, B = x[:n * n], x[n * n:]
    cols = [B[j::n] for j in range(n)]
    out = []
    for i in range(n):
        row = A[i * n:(i + 1) * n]
        out.extend(sum(p * q for p, q in zip(row, col)) for col in cols)
    return out


KERNELS = dict(sq2x2=sq2x2, stencil1d3=stencil1d3, box3x3=box3x3, laplace5=laplace5,
               conv3x3=conv3x3, life=life, polymap=polymap, transpose=transpose,
               maxpool2=maxpool2, sum=total, dot=dot, scan=scan, hist=hist, matmul=matmul)

if __name__ == '__main__':
    sys.exit(run('python', KERNELS))