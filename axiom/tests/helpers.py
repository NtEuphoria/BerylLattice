"""Literal source fixtures, independent of all compiler and execution modules."""


def stencil_source(h: int, w: int, cap: int | None = 64,
                   objective: str = 'multiplication_ops') -> bytes:
    requirement = '' if cap is None else f'require plan_workspace_bytes <= {cap};\n'
    return (f'''module demo;
shape H = {h};
shape W = {w};
input image: i32[H+1,W+1] in 0..=1023;
let p[r in 0..H+1,c in 0..W+1] =
  (image[r,c]+1)*(image[r,c]+1);
output result[r in 0..H,c in 0..W] =
  ((p[r,c]+p[r,c+1])+p[r+1,c])+p[r+1,c+1];
{requirement}prefer {objective};
''').encode('utf-8')
