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

    async def assert_stops(self, task: Shell) -> None:
        runner = asyncio.create_task(task.run())

        try:
            async with asyncio.timeout(2):
                while 'ready' not in task.output.get_output():
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
