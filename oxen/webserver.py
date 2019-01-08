import errno
import logging
import socket

from pathlib import Path

import tornado
import tornado.log
import tornado.platform.asyncio
import tornado.web
import tornado.websocket

from .color import status_ok
from .stream import StringStream
from .task import TaskEvent


class DashboardHandler(tornado.web.RequestHandler):
    def initialize(self, session):
        self.session = session

    def get(self):
        self.render('app.html', session=self.session)


class TaskInfoHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, session):
        self.session = session

    def open(self):
        self.session.task_status_monitor.subscribe(self.on_task_status_update)
        self.send_task_info()

    def on_task_status_update(self, _):
        self.send_task_info()

    def send_task_info(self):
        self.write_message({'tasks': [self.get_task_info(task) for task in self.session.tasks]})

    def get_task_info(self, task):
        return {
            'id': task.id,
            'name': task.name,
            'status': task.get_status().value,
            'actions': [action.name for action in task.get_actions()],
        }

    def on_close(self):
        self.session.task_status_monitor.unsubscribe(self.on_task_status_update)


class TaskOutputHandler(tornado.websocket.WebSocketHandler):
    def initialize(self, session):
        self.session = session
        self.task = None
        self.stream = None

    def open(self, task_id):
        self.task = self.session.get_task_by_id(int(task_id))
        self.stream = StringStream.from_task(self.task)
        self.task.events.subscribe(self.on_task_event)
        self.send_output_to_client()

    def on_close(self):
        self.unsubscribe()

    def on_task_event(self, event):
        if event == TaskEvent.OUTPUT_UPDATED:
            self.send_output_to_client()

    def send_output_to_client(self):
        new_fragment = self.stream.read()
        if new_fragment is None:
            return
        try:
            self.write_message(new_fragment)
        except tornado.websocket.WebSocketClosedError:
            self.unsubscribe()

    def unsubscribe(self):
        if self.task is not None:
            self.task.events.unsubscribe(self.on_task_event)


class TaskActionHandler(tornado.web.RequestHandler):
    def initialize(self, session):
        self.session = session

    def post(self):
        payload = tornado.escape.json_decode(self.request.body)
        task = self.session.get_task_by_id(payload['task'])
        result = task.perform_action(payload['action'])
        self.write(result or 'OK')


class WebApp(tornado.web.Application):
    def __init__(self, session):
        static_path = Path(__file__).parent / 'client' / 'static'
        template_path = static_path / 'templates'
        session_dict = {'session': session}

        handlers = [
            (
                r'/',
                DashboardHandler,
                session_dict
            ),
            (
                r'/tasks',
                TaskInfoHandler,
                session_dict
            ),
            (
                r'/task-output/(.*)',
                TaskOutputHandler,
                session_dict
            ),
            (
                r'/task-action',
                TaskActionHandler,
                session_dict
            ),
            (
                r'/static/(.*)',
                tornado.web.StaticFileHandler,
                {'path': str(static_path)}
            ),
        ]

        super().__init__(handlers, template_path=str(template_path))

    def get_port_candidates(self, preferred_port, max_distance=10):
        for dist in range(max_distance):
            yield preferred_port + dist
            if 0 > dist > preferred_port:
                yield preferred_port - dist

    def listen(self, port, address):
        for port in self.get_port_candidates(preferred_port=port):
            try:
                server = super().listen(port=port, address=address)
                break
            except socket.error as err:
                if err.errno == errno.EADDRINUSE:
                    continue
                raise
        status_ok('Listening', f'http://{address or "localhost"}:{port}/')
        return server

    @classmethod
    def setup(cls):
        # Install the Tornado I/O loop singleton
        tornado.platform.asyncio.AsyncIOMainLoop().install()
        tornado.log.enable_pretty_logging()
        logging.getLogger().setLevel(logging.WARNING)
