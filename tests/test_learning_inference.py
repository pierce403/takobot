from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from takobot.config import LearningConfig, load_tako_toml
from takobot.inference import InferenceProviderStatus, InferenceRuntime, run_learning_inference


class LearningConfigTests(unittest.TestCase):
    def test_defaults_and_bounded_operator_configuration(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'tako.toml'
            cfg, warning = load_tako_toml(path)
            self.assertEqual(cfg.learning, LearningConfig())
            self.assertFalse(warning)
            path.write_text('[learning]\nenabled = false\nreview_every = 0\ndaily_call_budget = 500\n'
                            'cooldown_seconds = -1\nmax_context_chars = 99999\nmax_active_skills = 0\n'
                            'auto_promote = true\n')
            cfg, warning = load_tako_toml(path)
            self.assertFalse(warning)
            self.assertFalse(cfg.learning.enabled)
            self.assertEqual(cfg.learning.review_every, 1)
            self.assertEqual(cfg.learning.daily_call_budget, 100)
            self.assertEqual(cfg.learning.cooldown_seconds, 0)
            self.assertEqual(cfg.learning.max_context_chars, 8000)
            self.assertEqual(cfg.learning.max_active_skills, 0)
            self.assertTrue(cfg.learning.auto_promote)


@unittest.skipUnless(shutil.which('node'), 'Node is required for the isolated SDK fixture')
class LearningInferenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.modules = self.root / '.tako/pi/node/node_modules/@mariozechner'
        self.agent = self.root / '.tako/pi/agent'
        self.agent.mkdir(parents=True)
        self.tmp = self.root / '.tako/tmp'
        self.tmp.mkdir()
        self.runtime = InferenceRuntime(
            statuses={'pi': InferenceProviderStatus('pi', 'pi', '/mock/pi', True, 'api_key',
                                                   'OPENAI_API_KEY', 'test', True, True)},
            selected_provider='pi', selected_auth_kind='api_key', selected_key_env_var='OPENAI_API_KEY',
            selected_key_source='test', _api_keys={},
        )
        # These minimal SDK fixtures exercise the real Node script and protocol,
        # without a provider request or a tool-capable agent runtime.
        for name in ('pi-ai', 'pi-coding-agent'):
            package = self.modules / name
            (package / 'dist/core').mkdir(parents=True)
            (package / 'package.json').write_text('{"type":"module"}')
        self.ai = self.modules / 'pi-ai/dist/index.js'
        self.ai.write_text('''
export async function completeSimple(model, context, options) {
  if (context.tools.length || context.messages.length !== 1 || !options.signal || options.maxTokens !== 2048)
    throw new Error('unexpected agent context');
  if (context.systemPrompt.includes('poison') || JSON.stringify(context).includes('SECRET_CONTEXT'))
    throw new Error('loaded workspace context');
  return {stopReason:'stop', content:[{type:'text', text:context.messages[0].content}]};
}
''')
        (self.modules / 'pi-coding-agent/dist/core/auth-storage.js').write_text(
            'export class AuthStorage { constructor(path) { this.path = path; } }')
        (self.modules / 'pi-coding-agent/dist/core/model-registry.js').write_text('''
export class ModelRegistry {
  constructor(auth,path) {}
  find(provider,id) { return {provider,id}; }
  async getApiKey(model) { return 'fixture'; }
}
''')
        (self.root / 'AGENTS.md').write_text('poison SECRET_CONTEXT')
        (self.agent / 'AGENTS.md').write_text('poison SECRET_CONTEXT')
        self.addCleanup(patch.stopall)
        patch('takobot.inference.repo_root', return_value=self.root).start()
        patch('takobot.inference._workspace_tmp_dir', return_value=self.tmp).start()
        patch('takobot.inference._provider_env', return_value={
            'PATH': str(Path(shutil.which('node')).parent), 'PI_CODING_AGENT_DIR': str(self.agent),
        }).start()

    def test_direct_completion_has_no_workspace_context(self):
        self.assertEqual(run_learning_inference(self.runtime, 'Return this text.', model='test/model'),
                         'Return this text.')

    def test_command_resolvers_are_refused_without_agent_fallback(self):
        marker = self.root / 'command-ran'
        (self.agent / 'auth.json').write_text(json.dumps({'test': {'type': 'api_key', 'key': f'!touch {marker}'}}))
        with patch('takobot.inference._run_pi') as agent:
            with self.assertRaisesRegex(RuntimeError, 'completion failed'):
                run_learning_inference(self.runtime, 'hello', model='test/model')
            agent.assert_not_called()
        self.assertFalse(marker.exists())

    def test_incomplete_and_tool_outputs_never_count_as_completion(self):
        for result in ({'stopReason': 'length', 'content': [{'type': 'text', 'text': 'partial'}]},
                       {'stopReason': 'stop', 'content': [{'type': 'toolCall', 'name': 'write'}]}):
            self.ai.write_text('export async function completeSimple() {return ' + json.dumps(result) + ';}')
            with self.assertRaises(RuntimeError):
                run_learning_inference(self.runtime, 'hello', model='test/model')

    def test_model_is_explicit_and_provider_output_is_not_exposed(self):
        with self.assertRaises(ValueError):
            run_learning_inference(self.runtime, 'hello', model='ambiguous-alias')
        with patch('takobot.inference.subprocess.run', return_value=subprocess.CompletedProcess(
            [], 1, stdout='private transcript', stderr='sensitive token')):
            with self.assertRaises(RuntimeError) as caught:
                run_learning_inference(self.runtime, 'hello', model='test/model')
            self.assertNotIn('sensitive', str(caught.exception))
            self.assertNotIn('private transcript', str(caught.exception))

    def test_does_not_switch_to_pi_from_another_selected_provider(self):
        self.runtime.selected_provider = 'ollama'
        with patch('takobot.inference.subprocess.run') as run:
            with self.assertRaises(RuntimeError):
                run_learning_inference(self.runtime, 'hello', model='test/model')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
