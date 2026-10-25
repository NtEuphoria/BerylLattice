"""run.py refuses comparisons whose thread counts would not be equal and recorded."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402


class ThreadArgumentTests(unittest.TestCase):
    def test_parallel_baselines_need_threads(self):
        self.assertIn('--threads', run.thread_error(['c', 'c-mt', 'axiom-native'], None, 8))
        self.assertIn('--threads', run.thread_error(['rust-mt'], None, 8))

    def test_threads_above_the_cpu_count_are_refused(self):
        # beryl's pool caps itself at the CPU count, so a larger N would be recorded falsely.
        self.assertIn('8', run.thread_error(['axiom-native'], 9, 8))

    def test_valid_settings_pass(self):
        self.assertIsNone(run.thread_error(['c', 'rust', 'axiom-native'], None, 8))
        self.assertIsNone(run.thread_error(['c-mt', 'axiom-native'], 4, 8))
        self.assertIsNone(run.thread_error(['c', 'axiom-native'], 1, 8))

    def test_default_impls_leave_out_the_parallel_baselines(self):
        self.assertNotIn('c-mt', run.DEFAULT_IMPLS)
        self.assertNotIn('rust-mt', run.DEFAULT_IMPLS)
        self.assertIn('axiom-native', run.DEFAULT_IMPLS)


if __name__ == '__main__':
    unittest.main()
