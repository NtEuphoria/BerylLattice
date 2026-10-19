"""Real demo behavior, independent observation failures, and fixed JSON worker."""
from dataclasses import replace
import base64
from hashlib import sha256
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from axiom.frontend import parse_source
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

    def compiled_service(self):
        service = self.service()
        for name in ('compiled_request_source', 'prepare_compiled_demo',
                     'compiled_request_inputs', 'finish_compiled_demo'):
            self.assertTrue(callable(getattr(service, name, None)),
                            f'compiled presentation entry {name} is missing')
        return service

    def compiled_observation(self, request):
        module = parse_source(request['source'].encode())
        if request['input_mode'] == 'custom':
            data = request['inputs']
        else:
            data = self.service().compiled_request_inputs(request)['input']
        initial = self.service().compiled_request_inputs(request)['initial_output']
        expected = evaluate_source(module, data, initial)
        return dict(status=0 if expected.first_bad_index is None else expected.first_bad_index + 1,
                    input=list(expected.input_after), output=list(expected.output))

    def test_compiled_source_validation_echoes_exact_source_without_preparation(self):
        service = self.compiled_service()
        service.prepare_compiled_demo('module ;')
        for source in (self.request()['source'], '// λ🙂\nmodule ;', ''):
            request = dict(source=source, input_mode='ramp')
            with patch.object(service, 'compile_wasm_source', side_effect=AssertionError('validation only')), \
                 patch.object(service, 'parse_source', side_effect=AssertionError('validation only')):
                self.assertEqual(service.compiled_request_source(request),
                                 {'status': 'valid', 'source': source})
        self.assertEqual(service.compiled_request_inputs(self.request())['diagnostic']['code'],
                         'NOT_PREPARED')

    def test_compiled_source_validation_matches_legacy_schema_and_encoding_errors(self):
        service = self.compiled_service()
        request = self.request()
        invalid = [None, [], {}, dict(request, extra='forged'), dict(request, input_mode='wrong'),
                   dict(request, source=12), dict(request, inputs=[]),
                   dict(request, input_mode='custom'),
                   dict(request, input_mode='custom', inputs=()),
                   dict(request, source='aλ🙂\ud800'), dict(request, source='x' * 65537)]
        expected = [service.run_demo(value) for value in invalid]
        with patch.object(service, 'compile_wasm_source', side_effect=AssertionError('validation only')), \
             patch.object(service, 'parse_source', side_effect=AssertionError('validation only')):
            for value, error in zip(invalid, expected):
                with self.subTest(request=repr(value)[:60]):
                    self.assertEqual(service.compiled_request_source(value), error)

    def test_compiled_preparation_binds_fresh_module_and_selection_metadata(self):
        service = self.compiled_service()
        request = self.request()
        legacy = service.run_demo(request)
        prepared = service.prepare_compiled_demo(request['source'])
        self.assertEqual(prepared['status'], 'prepared')
        self.assertEqual(prepared['schema_version'], 2)
        self.assertEqual(prepared['search']['policy_id'], 'ranked-proof-v1')
        self.assertTrue(prepared['search']['portfolio_optimal'])
        self.assertIsNotNone(prepared['lowering']['hint_digest'])
        skipped = prepared['attempts'][0]
        self.assertEqual(skipped['state'], 'not_checked_worse_rank')
        self.assertIsNone(skipped['eligible'])
        self.assertEqual(skipped['multiplication_ops'], 140)
        self.assertEqual(skipped['workspace_bytes'], 0)
        module_bytes = base64.b64decode(prepared['wasm_base64'], validate=True)
        self.assertTrue(module_bytes.startswith(b'\0asm\x01\0\0\0'))
        self.assertEqual(prepared['module_digest'], sha256(module_bytes).hexdigest())
        self.assertEqual(prepared['source_digest'], sha256(request['source'].encode()).hexdigest())
        self.assertEqual(prepared['plan_digest'], prepared['selected']['plan_digest'])
        for field in ('shape', 'objective', 'workspace_cap', 'selected'):
            self.assertEqual(prepared[field], legacy[field])
        self.assertEqual((prepared['input_count'], prepared['output_count']), (48, 35))
        self.assertGreaterEqual(prepared['input_offset'], 0)
        self.assertGreaterEqual(prepared['output_offset'], prepared['input_offset'] + 4 * 48)
        self.assertGreaterEqual(prepared['memory_bytes'], prepared['output_offset'] + 4 * 35)

    def test_compiled_preparation_is_reused_for_changing_inputs_and_fresh_comparison(self):
        service = self.compiled_service()
        request = self.request(h=1, w=1)
        service.prepare_compiled_demo(request['source'])
        requests = [self.request(h=1, w=1, mode='zeros'),
                    self.request(h=1, w=1, mode='custom', inputs=[0, 1, 2, 3]),
                    self.request(h=1, w=1, mode='checkerboard')]
        observations = [self.compiled_observation(item) for item in requests]
        with patch.object(service, 'parse_source', side_effect=AssertionError('must retain source')), \
             patch.object(service, 'select_plan', side_effect=AssertionError('must retain selection')), \
             patch.object(service, 'compile_wasm_source', side_effect=AssertionError('must retain module')), \
             patch.object(service, 'execute_plan', side_effect=AssertionError('compiled path')), \
             patch.object(service, 'evaluate_source', wraps=evaluate_source) as evaluator:
            results = [service.finish_compiled_demo(item, observation)
                       for item, observation in zip(requests, observations)]
        self.assertEqual([result['output'] for result in results], [[4], [30], [2097154]])
        self.assertEqual(evaluator.call_count, len(requests))
        for result in results:
            self.assertEqual(result['backend'], 'checked-plan-wasm-v2')
            self.assertEqual(result['comparison'], {'matches': True, 'cells_compared': 1})
            self.assertNotIn('wasm_base64', result)
            self.assertEqual(result['schema_version'], 2)
            self.assertIn('lowering', result)

    def test_compiled_source_identity_and_preparation_replacement_are_private(self):
        service = self.compiled_service()
        request = self.request(h=1, w=1)
        service.prepare_compiled_demo('module ;')
        self.assertEqual(service.compiled_request_inputs(request)['diagnostic']['code'], 'NOT_PREPARED')
        self.assertEqual(service.finish_compiled_demo(request, {})['diagnostic']['code'], 'NOT_PREPARED')
        prepared = service.prepare_compiled_demo(request['source'])
        selected_id = prepared['selected']['plan_id']
        observation = self.compiled_observation(request)
        changed = dict(request, source=request['source'] + '\n')
        for result in (service.compiled_request_inputs(changed),
                       service.finish_compiled_demo(changed, observation)):
            self.assertEqual(result['diagnostic']['code'], 'PREPARED_SOURCE_MISMATCH')
        prepared['selected']['plan_id'] = 'forged'
        prepared['shape']['height'] = 99
        self.assertEqual(service.finish_compiled_demo(request, observation)['selected']['plan_id'],
                         selected_id)
        replacement = self.request(h=1, w=1, cap=0)
        self.assertEqual(service.prepare_compiled_demo(replacement['source'])['status'], 'prepared')
        self.assertEqual(service.compiled_request_inputs(request)['diagnostic']['code'],
                         'PREPARED_SOURCE_MISMATCH')
        for bad_source in ('module ;', None, '\ud800', 'x' * 65537):
            with self.subTest(source=repr(bad_source)[:20]):
                service.prepare_compiled_demo(replacement['source'])
                self.assertEqual(service.prepare_compiled_demo(bad_source)['status'], 'error')
                self.assertEqual(service.compiled_request_inputs(replacement)['diagnostic']['code'],
                                 'NOT_PREPARED')

    def test_compiled_requests_reject_exact_shape_and_scalar_boundary_errors(self):
        service = self.compiled_service()
        request = self.request(h=1, w=1)
        service.prepare_compiled_demo(request['source'])
        invalid = [None, [], {}, dict(request, module_digest='forged'),
                   dict(request, input_mode='other'), dict(request, source=12),
                   dict(request, inputs=[]), dict(request, input_mode='custom')]
        for item in invalid:
            with self.subTest(request=item):
                self.assertEqual(service.compiled_request_inputs(item)['diagnostic']['code'],
                                 'INVALID_REQUEST')
                self.assertEqual(service.finish_compiled_demo(item, {})['diagnostic']['code'],
                                 'INVALID_REQUEST')
        for inputs, code in (([0], 'BOUNDARY_LENGTH'), ([False, 0, 0, 0], 'BOUNDARY_TYPE'),
                             ([0.5, 0, 0, 0], 'BOUNDARY_TYPE'), (['1', 0, 0, 0], 'BOUNDARY_TYPE'),
                             ([2**31, 0, 0, 0], 'BOUNDARY_I32'),
                             ([-2**31 - 1, 0, 0, 0], 'BOUNDARY_I32')):
            item = dict(request, input_mode='custom', inputs=inputs)
            with self.subTest(inputs=inputs):
                self.assertEqual(service.compiled_request_inputs(item)['diagnostic']['code'], code)
                self.assertEqual(service.finish_compiled_demo(item, {})['diagnostic']['code'], code)
        custom = dict(request, input_mode='custom', inputs=[0, 1, 2, 3])
        ready = service.compiled_request_inputs(custom)
        self.assertEqual(ready, dict(status='ready', input=[0, 1, 2, 3], initial_output=[-9]))
        ready['input'][0] = 99
        self.assertEqual(custom['inputs'][0], 0)

    def test_compiled_preconditions_compare_first_bad_and_preserve_every_sentinel(self):
        service = self.compiled_service()
        request = self.request()
        service.prepare_compiled_demo(request['source'])
        for index in (0, 24, 47):
            for value in (-2**31, 1024, 2**31 - 1):
                inputs = [0] * 48
                inputs[index] = value
                inputs[-1] = value
                item = dict(request, input_mode='custom', inputs=inputs)
                with self.subTest(index=index, value=value):
                    self.assertEqual(service.compiled_request_inputs(item)['status'], 'ready')
                    observation = self.compiled_observation(item)
                    self.assertEqual(observation['status'], index + 1)
                    result = service.finish_compiled_demo(item, observation)
                    self.assertEqual(result['status'], 'input_precondition_failed')
                    self.assertEqual(result['first_bad_index'], index)
                    self.assertEqual(result['input'], inputs)
                    self.assertEqual(result['output'], [-9] * 35)
                    self.assertEqual(result['comparison'], {'matches': True, 'cells_compared': 35})

    def test_compiled_observation_requires_exact_fields_lists_and_i32_scalars(self):
        service = self.compiled_service()
        request = self.request(h=1, w=1)
        service.prepare_compiled_demo(request['source'])
        observation = self.compiled_observation(request)
        malformed = [None, [], {}, dict(observation, extra=1),
                     dict(observation, input=tuple(observation['input'])),
                     dict(observation, output=tuple(observation['output']))]
        for value in malformed:
            self.assertEqual(service.finish_compiled_demo(request, value)['diagnostic']['code'],
                             'INVALID_REQUEST')
        for field in ('status', 'input', 'output'):
            for value, code in ((False, 'BOUNDARY_TYPE'), (1.0, 'BOUNDARY_TYPE'),
                                (2**31, 'BOUNDARY_I32'), (-2**31 - 1, 'BOUNDARY_I32')):
                changed = dict(observation)
                changed[field] = value if field == 'status' else [value] + observation[field][1:]
                with self.subTest(field=field, value=value):
                    self.assertEqual(service.finish_compiled_demo(request, changed)['diagnostic']['code'],
                                     code)
        for field in ('input', 'output'):
            changed = dict(observation, **{field: observation[field] + [0]})
            self.assertEqual(service.finish_compiled_demo(request, changed)['diagnostic']['code'],
                             'BOUNDARY_LENGTH')

    def test_compiled_observations_and_fresh_reference_disagreements_fail_independently(self):
        service = self.compiled_service()
        request = self.request(h=1, w=1)
        service.prepare_compiled_demo(request['source'])
        observation = self.compiled_observation(request)
        for changed in (dict(observation, input=[999] + observation['input'][1:]),
                        dict(observation, output=[observation['output'][0] + 1]),
                        dict(observation, status=1), dict(observation, status=-1),
                        dict(observation, status=5)):
            result = service.finish_compiled_demo(request, changed)
            self.assertEqual(result['diagnostic']['code'], 'INDEPENDENT_COMPARISON_FAILED')
            self.assertNotIn('output', result)
        def changed_output(module, data, initial):
            expected = evaluate_source(module, data, initial)
            return replace(expected, output=(expected.output[0] + 1,))
        with patch.object(service, 'evaluate_source', changed_output):
            result = service.finish_compiled_demo(request, observation)
        self.assertEqual(result['diagnostic']['code'], 'INDEPENDENT_COMPARISON_FAILED')

    def test_compiled_preparation_no_eligible_plan_or_compiler_failure_clears_context(self):
        service = self.compiled_service()
        request = self.request()
        service.prepare_compiled_demo(request['source'])
        from axiom import source_compilation
        from axiom.compilation_selection import _select_ranked
        def no_budget(context, total):
            return _select_ranked(context, 0)
        with patch.object(source_compilation, '_select_ranked', no_budget):
            prepared = service.prepare_compiled_demo(request['source'])
        self.assertEqual(prepared['status'], 'no_eligible_plan')
        self.assertNotIn('wasm_base64', prepared)
        self.assertEqual(service.compiled_request_inputs(request)['diagnostic']['code'], 'NOT_PREPARED')
        service.prepare_compiled_demo(request['source'])
        with patch.object(service, 'compile_wasm_source', side_effect=RuntimeError('/private/path')):
            prepared = service.prepare_compiled_demo(request['source'])
        self.assertEqual(prepared['diagnostic']['code'], 'INTERNAL_ERROR')
        self.assertNotIn('/private/path', json.dumps(prepared))
        self.assertEqual(service.compiled_request_inputs(request)['diagnostic']['code'], 'NOT_PREPARED')

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
