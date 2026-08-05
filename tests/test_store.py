import unittest

from oxen.store import TaskOutputChange, TaskStatusChange, TaskStore
from oxen.task import Task, TaskStatus


class FakeTask(Task):
    async def run(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class TaskStoreTest(unittest.TestCase):
    def test_adds_tasks_and_selects_the_first(self) -> None:
        first = FakeTask('first')
        second = FakeTask('second')
        store = TaskStore(first, second)

        self.assertEqual(store.tasks, [first, second])
        self.assertIs(store.selected_task, first)

    def test_publishes_add_and_selection_changes(self) -> None:
        store = TaskStore()
        first = FakeTask('first')
        second = FakeTask('second')
        added: list[Task] = []
        selected: list[Task | None] = []
        store.on_task_added.subscribe(added.append)
        store.on_selected_task_change.subscribe(selected.append)

        store.add(first, second)
        store.select(second)
        store.selected_task = None

        self.assertEqual(added, [first, second])
        self.assertEqual(selected, [first, second, None])

    def test_forwards_task_status_and_output_changes(self) -> None:
        task = FakeTask('task')
        store = TaskStore(task)
        statuses: list[TaskStatusChange] = []
        outputs: list[TaskOutputChange] = []
        store.on_task_status_change.subscribe(statuses.append)
        store.on_task_output_change.subscribe(outputs.append)

        task.status = TaskStatus.RUNNING
        task.output.append('hello')

        self.assertEqual(statuses, [TaskStatusChange(task, TaskStatus.RUNNING)])
        self.assertEqual(outputs, [TaskOutputChange(task, 'hello')])

    def test_rejects_duplicate_and_unregistered_tasks(self) -> None:
        task = FakeTask('task')
        other = FakeTask('other')
        store = TaskStore(task)

        with self.assertRaises(ValueError):
            store.add(task)
        with self.assertRaises(ValueError):
            store.select(other)


if __name__ == '__main__':
    unittest.main()
