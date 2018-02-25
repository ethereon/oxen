import asyncio
import functools
import pathlib
import sys

from collections import OrderedDict

from .color import status_ok
from .event import EventEmitter
from .task import TaskEvent
from .webserver import WebApp


class TaskStatusMonitor(EventEmitter):
    """
    Re-publishes status changes from a collection of tasks.
    """

    def add(self, task):
        task.events.subscribe(functools.partial(self.on_task_event, task=task))

    def on_task_event(self, event, *, task):
        if event == TaskEvent.STATUS_CHANGED:
            self.publish(task)


class Session:
    """
    Manages the execution and monitoring of a collection of tasks.
    """

    def __init__(self, name=None):
        self.name = name
        self.id_to_tasks = OrderedDict()
        self.webserver = WebApp(session=self)
        self.task_status_monitor = TaskStatusMonitor()

    def add_task(self, task):
        self.id_to_tasks[task.id] = task

    def __iadd__(self, task):
        self.add_task(task)
        return self

    def start_tasks(self, loop):
        for task in self.tasks:
            task.loop = loop
            task.start()
            self.task_status_monitor.add(task)
            status_ok('Started', task.name)

    def get_task_by_id(self, task_id):
        return self.id_to_tasks[task_id]

    def start(self, *, port=4242, address=''):
        WebApp.setup()
        loop = asyncio.get_event_loop()
        # Register all tasks
        self.start_tasks(loop)
        # Setup webserver
        self.webserver.listen(port=port, address=address)
        loop.run_forever()

    @property
    def tasks(self):
        return self.id_to_tasks.values()
