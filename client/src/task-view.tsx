import * as React from 'react';
import { Task } from './task';
import AnsiUp from 'ansi_up';

interface TaskViewProps {
    task: Task;
}

type TaskViewState = {
    connectedTask: Task;
};

export class TaskView extends React.Component<TaskViewProps, TaskViewState> {
    taskOutputContainer: HTMLElement;
    webSocket: WebSocket;
    ansiMarkup: AnsiUp;

    componentDidMount() {
        this.connect();
    }

    componentWillUnmount() {
        this.disconnect();
    }

    componentDidUpdate(prevProps: TaskViewProps, prevState: TaskViewState) {
        if (
            this.state &&
            this.state.connectedTask != null &&
            this.state.connectedTask !== this.task
        ) {
            this.disconnect();
            this.connect();
        }
    }

    connect() {
        if (this.webSocket) {
            return;
        }
        const webSocket = new WebSocket(`ws://${window.location.host}/task-output/${this.task.id}`);
        webSocket.onopen = () => {
            this.taskOutputContainer.innerHTML = '';
            this.ansiMarkup = new AnsiUp();
        };
        webSocket.onmessage = msg => {
            this.taskOutputContainer.insertAdjacentHTML(
                'beforeend',
                this.ansiMarkup.ansi_to_html(msg.data)
            );
            this.taskOutputContainer.scrollTop = this.taskOutputContainer.scrollHeight;
        };
        webSocket.onclose = msg => {
            if (this.webSocket === webSocket) {
                this.disconnect();
            }
        };
        this.webSocket = webSocket;
        this.setState({ connectedTask: this.task });
    }

    disconnect() {
        if (this.webSocket && this.webSocket.readyState != this.webSocket.CLOSED) {
            this.webSocket.close();
        }
        if (this.webSocket != null) {
            this.webSocket = null;
        }
        if (this.state.connectedTask != null) {
            this.setState({ connectedTask: null });
        }
    }

    get isConnected() {
        return this.webSocket != null;
    }

    get task() {
        return this.props.task;
    }

    performAction(action: string) {
        const payload = {
            task: this.task.id,
            action
        };
        fetch('/task-action', {
            method: 'POST',
            body: JSON.stringify(payload),
            headers: new Headers({
                'Content-Type': 'application/json'
            })
        });
    }

    render() {
        return (
            <div className="task-view">
                <div className="task-status">
                    <span className="info">{this.task.name}</span>
                    <span className="status"> &mdash; {this.task.status}</span>
                </div>
                <pre
                    key={this.task.id}
                    ref={elem => (this.taskOutputContainer = elem)}
                    className={
                        'task-output' + (this.isConnected ? '' : ' task-output-disconnected')
                    }
                />
                <div className="task-actions">
                    <button onClick={() => (this.isConnected ? this.disconnect() : this.connect())}>
                        {this.isConnected ? 'Disconnect' : 'Connect'}
                    </button>
                    {this.task.actions.map(action => (
                        <button key={action} onClick={() => this.performAction(action)}>
                            {action}
                        </button>
                    ))}
                </div>
            </div>
        );
    }
}
