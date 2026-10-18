"""Literal-definition reference outputs, independent of every measured implementation.

Written for obviousness rather than speed: each kernel reads its definition
directly with explicit row/column helpers. NumPy is deliberately not used, so
the NumPy baseline is verified rather than compared with itself.
"""
from catalog import KERNELS, checksum, gen_input

CONV = ((1, 2, 1), (2, 4, 2), (1, 2, 1))


def expected(kernel, a, b, x):
    if kernel == 'sq2x2':
        cols = b + 1
        p = lambda r, c: (x[r * cols + c] + 1) * (x[r * cols + c] + 1)
        return [p(r, c) + p(r, c + 1) + p(r + 1, c) + p(r + 1, c + 1)
                for r in range(a) for c in range(b)]
    if kernel == 'stencil1d3':
        return [x[i] + 2 * x[i + 1] + x[i + 2] for i in range(a)]
    if kernel in ('box3x3', 'laplace5', 'conv3x3', 'life'):
        cols = b + 2
        g = lambda r, c: x[r * cols + c]
        out = []
        for r in range(a):
            for c in range(b):
                if kernel == 'box3x3':
                    out.append(sum(g(r + i, c + j) for i in range(3) for j in range(3)))
                elif kernel == 'conv3x3':
                    out.append(sum(CONV[i][j] * g(r + i, c + j) for i in range(3) for j in range(3)))
                elif kernel == 'laplace5':
                    out.append(4 * g(r + 1, c + 1) - g(r, c + 1) - g(r + 2, c + 1)
                               - g(r + 1, c) - g(r + 1, c + 2))
                else:
                    alive = g(r + 1, c + 1) & 1
                    n = sum(g(r + i, c + j) & 1 for i in range(3) for j in range(3)) - alive
                    out.append(1 if n == 3 or (alive and n == 2) else 0)
        return out
    if kernel == 'polymap':
        return [v * v * v + 3 * v + 7 for v in x]
    if kernel == 'transpose':
        return [x[r * b + c] for c in range(b) for r in range(a)]
    if kernel == 'maxpool2':
        cols = 2 * b
        return [max(x[(2 * r + i) * cols + 2 * c + j] for i in range(2) for j in range(2))
                for r in range(a) for c in range(b)]
    if kernel == 'sum':
        return [sum(x)]
    if kernel == 'dot':
        return [sum(x[i] * x[a + i] for i in range(a))]
    if kernel == 'scan':
        out, total = [], 0
        for v in x:
            total += v
            out.append(total)
        return out
    if kernel == 'hist':
        bins = [0] * 64
        for v in x:
            bins[v >> 4] += 1
        return bins
    if kernel == 'matmul':
        n = a
        A, B = x[:n * n], x[n * n:]
        return [sum(A[i * n + k] * B[k * n + j] for k in range(n))
                for i in range(n) for j in range(n)]
    raise ValueError(f'unknown kernel {kernel!r}')


def expected_checksum(kernel, a, b, pattern):
    n_in, n_out = KERNELS[kernel]['io'](a, b)
    out = expected(kernel, a, b, gen_input(pattern, n_in))
    if len(out) != n_out:
        raise AssertionError(f'oracle produced {len(out)} values for {kernel}, expected {n_out}')
    return n_out, checksum(out)