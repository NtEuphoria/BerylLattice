"""Every program in docs/window-stencils.md is admitted, proved and correct."""
from pathlib import Path
import re
import unittest

from axiom.frontend import admit_source, parse_source
from axiom.model import Limits
from axiom.reference import evaluate_source
from axiom.runtime import execute_plan
from axiom.selection import select_plan

GUIDE = Path(__file__).resolve().parents[1] / 'docs' / 'window-stencils.md'


class WindowGuideTests(unittest.TestCase):
    def test_guide_programs_run_and_match_the_reference(self):
        programs = re.findall(r'```ax\n(.*?)```', GUIDE.read_text(encoding='utf-8'), re.S)
        self.assertGreaterEqual(len(programs), 4)
        for text in programs:
            source = text.encode('utf-8')
            with self.subTest(module=text.split(';')[0]):
                kernel = admit_source(parse_source(source))
                search = select_plan(kernel, Limits(), 10 ** 7, kernel.objective)
                self.assertIsNotNone(search.selected_plan)
                data = [(i * 2654435761 & 0xFFFFFFFF) >> 22 for i in range(kernel.input_count)]
                initial = [-9] * kernel.output_count
                observed = execute_plan(source, search.selected_plan_bytes, data, initial, Limits())
                self.assertEqual(observed, evaluate_source(kernel.source_module, data, initial))
                self.assertEqual(observed.status.value, 'success')


if __name__ == '__main__':
    unittest.main()
