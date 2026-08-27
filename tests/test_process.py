import asyncio
import os
import shlex
import sys
import unittest

from oxen import Shell
from oxen.task import TaskStatus


@unittest.skipUnless(os.name == 'posix', 'process groups are POSIX-specific')
class ShellProcessGroupTest(unittest.IsolatedAsyncioTestCase):
    async def test_stop_terminates_a_long_running_pipeline(self) -> None:
        python = shlex.quote(sys.executable)
        child_code = 'import sys, time; sys.stdin.read(); print("ready", flush=True); time.sleep(60)'
        command = f'printf input | {python} -u -c {shlex.quote(child_code)}'
        task = Shell(command)
        await self.assert_stops(task)

    async def test_stop_force_kills_a_pipeline_child_that_ignores_terminate(self) -> None:
        python = shlex.quote(sys.executable)
        child_code = 'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready", flush=True); time.sleep(60)'
        command = f'printf input | {python} -u -c {shlex.quote(child_code)}'
        task = Shell(command, terminate_timeout=0.1)

        await self.assert_stops(task)

    async def test_pty_streams_line_buffered_pipeline_output(self) -> None:
        command = "(printf 'error\\n'; sleep 60) | grep error"
        task = Shell(command, pty=True, terminate_timeout=0.1)

        await self.assert_stops(task, expected_output='error')

    async def test_pty_merges_terminal_stdout_and_stderr(self) -> None:
        python = shlex.quote(sys.executable)
        child_code = 'import sys; print(sys.stdout.isatty()); print(sys.stderr.isatty(), file=sys.stderr)'
        task = Shell(f'{python} -c {shlex.quote(child_code)}', pty=True)

        await task.run()

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.output.text.count('True'), 2)

    async def test_pty_rejects_custom_output_streams(self) -> None:
        task = Shell('true', pty=True, stdout=asyncio.subprocess.PIPE)

        with self.assertRaisesRegex(ValueError, 'custom stdout'):
            await task.run()

    async def assert_stops(self, task: Shell, expected_output: str = 'ready') -> None:
        runner = asyncio.create_task(task.run())

        try:
            async with asyncio.timeout(2):
                while expected_output not in task.output.text:
                    await asyncio.sleep(0.01)

            async with asyncio.timeout(2):
                await task.stop()
                await runner

            self.assertEqual(task.status, TaskStatus.STOPPED)
        finally:
            if not runner.done():
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
