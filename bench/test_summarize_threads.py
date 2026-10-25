"""summarize.py compares only equal thread counts and lists every loss."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import summarize  # noqa: E402

HEADER = dict(type='run', run_id='test', git_revision='0' * 40, git_branch='test', git_dirty=False,
              platform='test', cpu_count=8, versions={}, label='', threads=4)


def result(impl, ns, threads, kernel='sq2x2'):
    record = dict(type='result', kernel=kernel, tier='m', pattern='hash', impl=impl, status='ok',
                  ns_median=ns, a=255, b=255, threads=threads)
    if impl == 'axiom-native':
        record.update(plan=dict(id='direct-v1', multiplication_ops=4), axiom_compile_ns=1, cc_ns=1)
    return record


def summary(records):
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / 'run.jsonl'
        log.write_text('\n'.join(json.dumps(r) for r in [HEADER, *records]), encoding='utf-8')
        return summarize.report(*summarize.load(log))


def row(text, kernel):
    return next(line for line in text.splitlines() if line.startswith(f'| {kernel} | m |'))


class ThreadSummaryTests(unittest.TestCase):
    def test_mixed_thread_counts_are_not_compared(self):
        text = summary([result('c-mt', 100, 4), result('axiom-native', 50, 7)])
        self.assertIn('threads differ', row(text, 'sq2x2'))
        self.assertNotIn('0.5x', row(text, 'sq2x2'))

    def test_equal_thread_counts_are_compared(self):
        text = summary([result('c-mt', 100, 4), result('axiom-native', 50, 4)])
        self.assertIn('(0.5x)', row(text, 'sq2x2'))
        self.assertIn('Threads: 4', text)

    def test_ratios_use_the_base_with_the_same_thread_count(self):
        text = summary([result('c', 300, 1), result('c-mt', 100, 4), result('axiom-native', 50, 4)])
        cells = row(text, 'sq2x2').split('|')
        self.assertEqual(cells[4].strip(), '300 ns')           # c: its own base
        self.assertEqual(cells[5].strip(), '100 ns')           # c-mt: the 4-thread base
        self.assertEqual(cells[6].strip(), '50 ns (0.5x)')     # against c-mt, not c

    def test_losses_are_listed(self):
        text = summary([result('c', 100, 1), result('axiom-native', 150, 1),
                        result('c', 100, 1, 'box3x3'), result('axiom-native', 40, 1, 'box3x3')])
        losses = text.split('## Losses', 1)[1].split('\n## ', 1)[0]
        self.assertIn('sq2x2 m hash', losses)
        self.assertIn('1.5x', losses)
        self.assertNotIn('box3x3', losses)


if __name__ == '__main__':
    unittest.main()
