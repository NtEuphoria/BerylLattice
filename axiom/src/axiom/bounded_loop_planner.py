"""Untrusted compact scheduling intent matching the unchanged finite planner.

This generator imports neither correspondence nor checking. Hoisted constants,
producer grouping and stage/consume/refill order are preserved as primitives.
"""
from .bounded_loop_model import FORMAT_VERSION, IndexExpr, IndexTerm, Loop, LoopProgram, Primitive
from .model import AdmittedKernel


def make_loop_program(kernel, schedule):
    if type(kernel) is not AdmittedKernel:
        raise TypeError('expected AdmittedKernel')
    if type(schedule) is not str or schedule not in ('inline-v1', 'rows2-v1', 'materialize-v1'):
        raise ValueError('unsupported bounded schedule')
    h, w = kernel.height, kernel.width
    if type(h) is not int or type(w) is not int or h < 1 or w < 1 or (h+1)*(w+1) > 256:
        raise ValueError('bounded schedule retains the 256-input boundary')
    stride = w+1

    def index(row, offset=0, column_offset=0, *, scratch=False):
        parity = scratch and schedule == 'rows2-v1'
        if type(row) is int:
            r = row+offset
            constant = (r % 2 if parity else r)*stride+column_offset
            return IndexExpr(constant, (IndexTerm(1, 'c'),))
        return IndexExpr(column_offset, (IndexTerm(stride, row, offset, parity), IndexTerm(1, 'c')))

    def produce(prefix, row, row_offset=0, col_offset=0):
        return (Primitive('input_load', prefix+'load', index=index(row,row_offset,col_offset)),
                Primitive('add', prefix+'inc', (prefix+'load','one')),
                Primitive('mul', prefix+'value', (prefix+'inc',prefix+'inc')))

    def consume(row, *, inline=False):
        body = []
        for prefix, ro, co in (('a',0,0),('b',0,1),('d',1,0),('e',1,1)):
            if inline:
                body.extend(produce(prefix,row,ro,co))
            else:
                body.append(Primitive('scratch_load',prefix+'value',index=index(row,ro,co,scratch=True)))
        body.extend((Primitive('add','ab',('avalue','bvalue')),
                     Primitive('add','abd',('ab','dvalue')),
                     Primitive('add','total',('abd','evalue')),
                     Primitive('output_store',operands=('total',),
                               index=IndexExpr(row*w if type(row) is int else 0,
                                               (IndexTerm(1,'c'),) if type(row) is int else
                                               (IndexTerm(w,row),IndexTerm(1,'c'))))))
        return Loop('c',0,w,tuple(body))

    def stage(row, offset=0):
        return Loop('c',0,stride,produce('p',row,offset)+(Primitive(
            'scratch_store',operands=('pvalue',),index=index(row,offset,scratch=True)),))

    body = [Primitive('const','one',value=1)]
    if schedule == 'inline-v1':
        capacity = 0
        body.append(Loop('r',0,h,(consume('r',inline=True),)))
    elif schedule == 'materialize-v1':
        capacity = (h+1)*stride
        body.extend((Loop('s',0,h+1,(stage('s'),)),Loop('r',0,h,(consume('r'),))))
    else:
        capacity = 2*stride
        body.extend((Loop('s',0,2,(stage('s'),)),
                     Loop('r',0,h-1,(consume('r'),stage('r',2))),
                     consume(h-1)))
    return LoopProgram(FORMAT_VERSION,kernel.source_digest,kernel.semantic_digest,
                       h,w,capacity,tuple(body),schedule)
