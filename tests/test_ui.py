import unittest

from oxen.task import Task, TaskStatus
from oxen.ui import normalize_task_layout


class FakeTask(Task):
    async def _execute(self) -> TaskStatus:
        return TaskStatus.COMPLETED


class TaskLayoutTest(unittest.TestCase):
    def test_normalizes_layout_and_collects_unique_tasks(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')

        layout, tasks = normalize_task_layout([(first, second), [first]])

        self.assertEqual(layout, [(first, second), [first]])
        self.assertEqual(tasks, [first, second])

    def test_rejects_invalid_layouts(self) -> None:
        with self.assertRaisesRegex(ValueError, 'must not be empty'):
            normalize_task_layout([])
        with self.assertRaisesRegex(TypeError, 'must be a Task, list, or tuple'):
            normalize_task_layout([[object()]])

        recursive: list = []
        recursive.append(recursive)
        with self.assertRaisesRegex(ValueError, 'contains a recursive container'):
            normalize_task_layout(recursive)


if __name__ == '__main__':
    unittest.main()
