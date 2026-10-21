"""Publishing never pushes dirty/default branches or failed checks."""

import subprocess
import unittest
from unittest.mock import patch

from tools import publish


class PublishingTests(unittest.TestCase):
    def setUp(self):
        output = patch('builtins.print')
        output.start()
        self.addCleanup(output.stop)

    def test_default_branch_is_rejected(self):
        with (
            patch.object(publish, 'git_output', return_value='main'),
            patch.object(publish.subprocess, 'run') as run,
        ):
            self.assertEqual(publish.main(), 1)
            run.assert_not_called()

    def test_dirty_branch_is_rejected(self):
        with (
            patch.object(
                publish, 'git_output', side_effect=['codex/change', ' M tracked.py']
            ),
            patch.object(publish.subprocess, 'run') as run,
        ):
            self.assertEqual(publish.main(), 1)
            run.assert_not_called()

    def test_failed_check_prevents_push(self):
        with (
            patch.object(
                publish, 'git_output', side_effect=['codex/change', '', 'origin-url']
            ),
            patch.object(
                publish.subprocess,
                'run',
                side_effect=subprocess.CalledProcessError(1, 'check'),
            ) as run,
        ):
            self.assertEqual(publish.main(), 1)
            self.assertEqual(run.call_count, 1)
            self.assertNotEqual(run.call_args.args[0][0], 'git')

    def test_push_is_last_and_preserves_feature_branch(self):
        with (
            patch.object(
                publish, 'git_output', side_effect=['codex/change', '', 'origin-url']
            ),
            patch.object(publish.subprocess, 'run') as run,
        ):
            self.assertEqual(publish.main(), 0)
            self.assertEqual(run.call_count, 5)
            self.assertEqual(
                run.call_args_list[-1].args[0],
                ['git', 'push', '--set-upstream', 'origin', 'codex/change'],
            )
