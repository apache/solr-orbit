import subprocess

from solrorbit.builder.executors.shell_executor import ShellExecutor
from solrorbit.exceptions import ExecutorError
from solrorbit.utils import process


class LocalShellExecutor(ShellExecutor):
    # pylint: disable=arguments-differ
    def execute(self, host, command, output=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=None, detach=False):
        if output:
            return process.run_subprocess_with_output(command)
        else:
            if process.run_subprocess_with_logging(command, stdout=stdout, stderr=stderr, env=env, detach=detach):
                raise ExecutorError(f"Command: \"{command}\" returned a non-zero exit code")
