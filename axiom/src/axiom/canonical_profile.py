"""The normalized profile of the original squared 2x2 stencil.

Canonical admission compares a source profile to this exact record; the
frontend and the v2 source profiles both use it.
"""


def _canonical_profile():
    integer = lambda value: ['integer', value]
    name = lambda value: ['name', value]
    add = lambda a, b: ['+', a, b]
    row, col = name('axis0'), name('axis1')
    height, width = name('shape0'), name('shape1')
    read = lambda tensor, r, c: ['read', tensor, [r, c]]
    increment = add(read('input0', row, col), integer(1))
    consumer = add(add(add(read('producer0', row, col),
                           read('producer0', row, add(col, integer(1)))),
                       read('producer0', add(row, integer(1)), col)),
                   read('producer0', add(row, integer(1)), add(col, integer(1))))
    return {'inputs': [['i32', [add(height, integer(1)), add(width, integer(1))], [0, 1023]]],
            'equations': [
                [[[integer(0), add(height, integer(1))], [integer(0), add(width, integer(1))]], ['*', increment, increment]],
                [[[integer(0), height], [integer(0), width]], consumer],
            ]}
