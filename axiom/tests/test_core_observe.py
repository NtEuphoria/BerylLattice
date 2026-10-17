import unittest
from dataclasses import FrozenInstanceError
from axiom.core_observe import Observation, ObservationError, decode_observation
from axiom.frontend import admit_source, parse_source
from tests.helpers import stencil_source


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.kernel = admit_source(parse_source(stencil_source(1, 1)))
        self.good = b'-1\n0\n1\n2\n3\n30\nok  1 test, 0 assertions\n'

    def test_complete_exact_observation(self):
        result = decode_observation(self.good, self.kernel)
        self.assertEqual(result, Observation(-1, (0, 1, 2, 3), (30,)))
        with self.assertRaises(FrozenInstanceError):
            result.status = 1

    def test_rejects_noncanonical_or_partial_payload(self):
        bad = [self.good[:-1], self.good + b'\n', self.good + b'diagnostic\n',
               self.good.replace(b'30\n', b''), self.good.replace(b'30\n', b'30\n0\n'),
               self.good.replace(b'30\n', b'2147483648\n'), self.good.replace(b'30\n', b'-2147483649\n'),
               self.good.replace(b'30\n', b'+30\n'), self.good.replace(b'30\n', b'030\n'),
               self.good.replace(b'30\n', b'30 \n'), self.good.replace(b'30\n', b'3.0\n'),
               self.good.replace(b'\n', b'\r\n'), self.good.replace(b'ok  1', b'ok 1'),
               self.good.replace(b'0 assertions', b'1 assertions'), b'\xff' + self.good]
        for stdout in bad:
            with self.subTest(stdout=stdout), self.assertRaises(ObservationError):
                decode_observation(stdout, self.kernel)

    def test_i32_endpoints_and_all_h5_w7_cells(self):
        kernel = admit_source(parse_source(stencil_source(5, 7)))
        scalars = [-1] + [-2147483648] * 48 + [2147483647] * 35
        payload = ''.join(f'{n}\n' for n in scalars).encode() + b'ok  1 test, 0 assertions\n'
        result = decode_observation(payload, kernel)
        self.assertEqual(len(result.input), 48)
        self.assertEqual(result.output, (2147483647,) * 35)
