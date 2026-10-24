"""The `native` command: checked C for any admitted program, and readable refusals."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from axiom.__main__ import main

BLUR = b'''module blur;
shape H = 300;
shape W = 200;
input image: i32[H+2,W+2] in 0..=1023;
let rows[r in 0..H+2,c in 0..W] = (image[r,c]+2*image[r,c+1])+image[r,c+2];
output result[r in 0..H,c in 0..W] = (rows[r,c]+2*rows[r+1,c])+rows[r+2,c];
'''
OVERFLOW = b'''module big;
shape H = 1;
shape W = 1;
input x: i32[1,3000] in 0..=1023;
let t[r in 0..H,c in 0..W] = sum(k in 0..3000: x[0,k]*x[0,k]);
output s[r in 0..H,c in 0..W] = t[r,c];
'''


def run(*argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(list(argv))
    return code, json.loads(out.getvalue())


class NativeCommandTests(unittest.TestCase):
    def test_compiles_checked_parallel_c(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'blur.ax', Path(tmp) / 'blur.c'
            source.write_bytes(BLUR)
            code, result = run('native', str(source), '--out', str(target))
            self.assertEqual(code, 0, result)
            self.assertEqual((result['status'], result['family'], result['parallel']), ('compiled', 'scale-v1', True))
            self.assertEqual((result['input_count'], result['output_count']), (302 * 202, 300 * 200))
            self.assertIn(b'int32_t beryl_kernel(', target.read_bytes())
            # An existing file is never replaced without --force.
            code, result = run('native', str(source), '--out', str(target))
            self.assertEqual((code, result['diagnostic']['code']), (2, 'INVALID_INPUT'))
            self.assertEqual(run('native', str(source), '--out', str(target), '--force')[0], 0)

    def test_overflow_refusal_explains_the_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'big.ax'
            source.write_bytes(OVERFLOW)
            code, result = run('native', str(source), '--out', str(Path(tmp) / 'big.c'))
            self.assertEqual((code, result['status']), (4, 'no_eligible_plan'))
            self.assertIn('adds 3000 terms of up to 1046529 each', result['reason'])
            self.assertIn('at most 2052 terms fit', result['reason'])
            self.assertFalse((Path(tmp) / 'big.c').exists())


if __name__ == '__main__':
    unittest.main()
