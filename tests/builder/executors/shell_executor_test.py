import unittest.mock as mock
from unittest import TestCase

from solrorbit.builder.executors.local_shell_executor import LocalShellExecutor
from solrorbit.exceptions import ExecutorError


class LocalShellExecutorTests(TestCase):
    def setUp(self):
        self.executor = LocalShellExecutor()
        self.host = None
        self.command = None

    @mock.patch("solrorbit.utils.process.run_subprocess_with_output")
    def test_command_with_output(self, run_subprocess_with_output):
        run_subprocess_with_output.return_value = ["test", "output"]

        output = self.executor.execute(self.host, self.command, output=True)
        self.assertEqual(output, ["test", "output"])

    @mock.patch("solrorbit.utils.process.run_subprocess_with_logging")
    def test_command_with_logging_success(self, run_subprocess_with_logging):
        run_subprocess_with_logging.return_value = 0

        self.executor.execute(self.host, self.command)

    @mock.patch("solrorbit.utils.process.run_subprocess_with_logging")
    def test_command_with_logging_failure(self, run_subprocess_with_logging):
        run_subprocess_with_logging.return_value = 86

        with self.assertRaises(ExecutorError):
            self.executor.execute(self.host, self.command)
