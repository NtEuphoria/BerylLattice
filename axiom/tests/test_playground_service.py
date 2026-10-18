"""Real demo behavior, independent observation failures, and fixed JSON worker."""
from dataclasses import replace
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from axiom.reference import evaluate_source
from axiom.selection import select_plan
from tests.helpers import stencil_source


class PlaygroundServiceTests(unittest.TestCase):
    def service(self):
        self.assertIsNotNone(importlib.util.find_spec('axiom.playground_service'),
                             'working presentation service is missing')
        return importlib.import_module('axiom.playground_service')

    def request(self, h=5, w=7, cap=64, objective='multiplication_ops', mode='ramp', **fields):
        return dict(source=stencil_source(h, w, cap, objective).decode(), input_mode=mode, **fields)

    def test_examples_are_complete_independent_sources_and_run(self):
        service = self.service()
        examples = service.get_examples()
        self.assertEqual(set(examples), {'examples'})
        self.assertEqual([e['id'] for e in examples['examples']], ['balanced', 'no-scratch', 'small-memory'])
        expected = ['rows2-v1', 'inline-v1', 'inline-v1']
        for example, selected in zip(examples['examples'], expected):
            with self.subTest(example=example['id']):
                self.assertEqual(set(example), {'id', 'title', 'description', 'source'})
                result = service.run_demo(dict(source=example['source'], input_mode='ramp'))
                self.assertEqual(result['status'], 'success')
                self.assertEqual(result['selected']['plan_id'], selected)
        examples['examples'][0]['source'] = 'changed'
        self.assertNotEqual(service.get_examples()['examples'][0]['source'], 'changed')

    def test_ramp_response_binds_selected_metrics_and_every_observation(self):
        result = self.service().run_demo(self.request())
        self.assertEqual(set(result), {'schema_version', 'status', 'backend', 'source_digest',
            'shape', 'objective', 'workspace_cap', 'selected', 'attempts', 'search', 'input',
            'output', 'comparison', 'first_bad_index', 'diagnostic'})
        self.assertEqual(result['schema_version'], 1)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['backend'], 'checked-plan-interpreter-v1')
        self.assertEqual(result['shape'], dict(height=5, width=7, input_height=6, input_width=8))
        self.assertEqual(result['selected']['plan_id'], 'rows2-v1')
        self.assertEqual(result['selected']['multiplication_ops'], 48)
        self.assertEqual(result['selected']['workspace_bytes'], 64)
        self.assertEqual(result['input'], list(range(48)))
        self.assertEqual(result['output'][0], 186)
        self.assertEqual(result['output'][-1], 7634)
        self.assertEqual(len(result['output']), 35)
        self.assertEqual(result['comparison'], {'matches': True, 'cells_compared': 35})
        self.assertEqual(result['search']['termination_reason'], 'completed')
        self.assertEqual(result['search']['work_used'], 12847)
        self.assertIsNone(result['first_bad_index'])
        self.assertIsNone(result['diagnostic'])
        self.assertEqual([(a['plan_id'], a['eligible']) for a in result['attempts']],
                         [('inline-v1', True), ('rows2-v1', True), ('materialize-v1', False)])
        json.dumps(result, allow_nan=False)

    def test_cap_and_objective_change_real_selection_without_changing_output(self):
        service = self.service()
        balanced = service.run_demo(self.request())
        for request in (self.request(cap=0), self.request(objective='plan_workspace_bytes')):
            result = service.run_demo(request)
            self.assertEqual(result['selected']['plan_id'], 'inline-v1')
            self.assertEqual(result['selected']['multiplication_ops'], 140)
            self.assertEqual(result['selected']['workspace_bytes'], 0)
            self.assertEqual(result['output'], balanced['output'])
            self.assertEqual(result['comparison']['matches'], True)

    def test_zero_checkerboard_and_custom_inputs_are_actually_executed(self):
        service = self.service()
        zero = service.run_demo(self.request(mode='zeros'))
        self.assertEqual(zero['output'], [4] * 35)
        checkerboard = service.run_demo(self.request(h=1, w=1, mode='checkerboard'))
        self.assertEqual(checkerboard['input'], [0, 1023, 1023, 0])
        self.assertEqual(checkerboard['output'], [2097154])
        custom = service.run_demo(self.request(h=1, w=1, mode='custom', inputs=[0, 1, 2, 3]))
        self.assertEqual(custom['output'], [30])

    def test_custom_precondition_failure_preserves_all_output_and_matches_oracle(self):
        inputs = [0] * 48
        inputs[47] = 1024
        result = self.service().run_demo(self.request(mode='custom', inputs=inputs))
        self.assertEqual(result['status'], 'input_precondition_failed')
        self.assertEqual(result['first_bad_index'], 47)
        self.assertEqual(result['output'], [-9] * 35)
        self.assertEqual(result['input'], inputs)
        self.assertEqual(result['comparison'], {'matches': True, 'cells_compared': 35})

    def test_precondition_failure_refuses_before_planning(self):
        service = self.service()
        inputs = [0] * 48
        inputs[47] = 1024
        with patch.object(service, 'select_plan', side_effect=AssertionError('must not plan')), \
             patch.object(service, 'execute_plan', side_effect=AssertionError('must not execute')):
            result = service.run_demo(self.request(mode='custom', inputs=inputs))
        self.assertEqual(result['status'], 'input_precondition_failed')
        self.assertEqual(result['first_bad_index'], 47)
        self.assertIsNone(result['selected'])
        self.assertEqual(result['attempts'], [])
        self.assertIsNone(result['search'])
        self.assertEqual(result['output'], [-9] * 35)
        self.assertEqual(result['comparison'], {'matches': True, 'cells_compared': 35})

    def test_precondition_disagreement_takes_the_checked_path(self):
        service = self.service()
        inputs = [0] * 48
        inputs[47] = 1024
        def wrong_index(module, data, initial):
            return replace(evaluate_source(module, data, initial), first_bad_index=0)
        with patch.object(service, 'evaluate_source', wrong_index):
            result = service.run_demo(self.request(mode='custom', inputs=inputs))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['diagnostic']['code'], 'INDEPENDENT_COMPARISON_FAILED')

    def test_malformed_boundary_keeps_precedence_over_range_failure(self):
        service = self.service()
        inputs = [0] * 48
        inputs[3] = 1024
        inputs[40] = 'not an integer'
        result = service.run_demo(self.request(mode='custom', inputs=inputs))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['diagnostic']['code'], 'BOUNDARY_TYPE')

    def test_maximum_shape_runs_and_larger_source_is_rejected(self):
        result = self.service().run_demo(self.request(h=15, w=15, cap=None))
        self.assertEqual(result['status'], 'success')
        self.assertEqual(len(result['input']), 256)
        self.assertEqual(len(result['output']), 225)
        self.assertEqual(result['comparison']['cells_compared'], 225)
        rejected = self.service().run_demo(self.request(h=32, w=32))
        self.assertEqual(rejected['status'], 'error')
        self.assertTrue(rejected['diagnostic']['code'].startswith('UNSUPPORTED_'))
        self.assertNotIn('output', rejected)

    def test_malformed_unsupported_and_overlong_sources_return_stable_diagnostics(self):
        service = self.service()
        for source, code in (('module ;', 'SYNTAX_ERROR'),
                             (self.request()['source'].replace('+1)', '+2)'), 'UNSUPPORTED_PROFILE'),
                             ('x' * 65537, 'SOURCE_BYTES_LIMIT'),
                             ('\ud800', 'INVALID_SOURCE_ENCODING')):
            with self.subTest(code=code):
                result = service.run_demo(dict(source=source, input_mode='ramp'))
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['diagnostic']['code'], code)
                self.assertNotIn('output', result)
        result = service.run_demo(dict(source='// λ\nmodule ;', input_mode='ramp'))
        self.assertEqual(result['diagnostic']['offset'], len('// λ\nmodule '.encode()))

    def test_invalid_unicode_diagnostic_uses_utf8_prefix_byte_offset(self):
        service = self.service()
        for prefix in ('', 'abc', 'λ', 'aλ🙂'):
            with self.subTest(prefix=prefix):
                result = service.run_demo(dict(source=prefix + '\ud800', input_mode='ramp'))
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['diagnostic']['code'], 'INVALID_SOURCE_ENCODING')
                self.assertEqual(result['diagnostic']['offset'], len(prefix.encode('utf-8')))
                self.assertNotIn('output', result)

    def test_exact_request_shape_and_custom_boundary_validation(self):
        service = self.service()
        invalid = [None, [], {}, self.request(extra='forbidden'),
                   dict(source=self.request()['source'], input_mode='wrong'),
                   dict(source=12, input_mode='ramp'), self.request(mode='custom'),
                   self.request(inputs=[]), self.request(mode='custom', inputs=()),
                   self.request(mode=['ramp'])]
        for request in invalid:
            with self.subTest(request=request):
                result = service.run_demo(request)
                self.assertEqual(result['status'], 'error')
                self.assertEqual(result['diagnostic']['code'], 'INVALID_REQUEST')
        for inputs, code in (([0], 'BOUNDARY_LENGTH'),
                             ([False] + [0] * 47, 'BOUNDARY_TYPE'),
                             ([2**31] + [0] * 47, 'BOUNDARY_I32')):
            result = service.run_demo(self.request(mode='custom', inputs=inputs))
            self.assertEqual(result['status'], 'error')
            self.assertEqual(result['diagnostic']['code'], code)

    def test_any_independent_observation_disagreement_is_an_error(self):
        service = self.service()
        def changed_output(module, data, initial):
            result = evaluate_source(module, data, initial)
            return replace(result, output=result.output[:-1] + (result.output[-1] + 1,))
        def changed_input(module, data, initial):
            result = evaluate_source(module, data, initial)
            return replace(result, input_after=result.input_after[:-1] + (999,))
        def changed_status(module, data, initial):
            return replace(evaluate_source(module, data, initial), first_bad_index=0)
        for evaluator in (changed_output, changed_input, changed_status):
            with self.subTest(change=evaluator.__name__), patch.object(service, 'evaluate_source', evaluator):
                result = service.run_demo(self.request())
            self.assertEqual(result['status'], 'error')
            self.assertEqual(result['diagnostic']['code'], 'INDEPENDENT_COMPARISON_FAILED')
            self.assertNotIn('output', result)

    def test_no_eligible_plan_is_reported_without_execution(self):
        service = self.service()
        def no_budget(kernel, limits, total, objective):
            return select_plan(kernel, limits, 0, objective)
        with patch.object(service, 'select_plan', no_budget), \
             patch.object(service, 'execute_plan', side_effect=AssertionError('must not execute')):
            result = service.run_demo(self.request())
        self.assertEqual(result['status'], 'no_eligible_plan')
        self.assertIsNone(result['selected'])
        self.assertIsNone(result['output'])
        self.assertIsNone(result['comparison'])

    def worker(self, raw):
        self.service()
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        completed = subprocess.run([sys.executable, '-m', 'axiom.playground_service'],
            input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertEqual(completed.stderr, b'')
        self.assertEqual(len(completed.stdout.splitlines()), 1)
        return json.loads(completed.stdout)

    def test_fixed_worker_executes_real_request(self):
        result = self.worker(json.dumps(self.request()).encode())
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['selected']['plan_id'], 'rows2-v1')
        self.assertEqual(result['output'][-1], 7634)

    def test_fixed_worker_rejects_duplicate_invalid_and_oversized_json(self):
        for raw in (b'{"source":"x","source":"y"}', b'[]', b'not json',
                    b'{"x":1.2}', b' ' * 131073):
            with self.subTest(raw=raw[:30]):
                result = self.worker(raw)
                self.assertEqual(result['status'], 'error')
                self.assertIn('diagnostic', result)


if __name__ == '__main__':
    unittest.main()
