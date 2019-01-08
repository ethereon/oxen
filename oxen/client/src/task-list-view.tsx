import * as React from 'react';
import { Task } from './task';
import { AppState, appStateManager } from './app-state';

interface TaskListViewItemProps {
    task: Task;
    isSelected: boolean;
}

class TaskListViewItem extends React.PureComponent<TaskListViewItemProps> {
    activateTask() {
        appStateManager.selectTask(this.props.task);
    }

    render() {
        return (
            <button className="task-item" onClick={() => this.activateTask()}>
                <span className={`status-indicator status-${this.props.task.status}`} />
                <span className="title">{this.props.task.name}</span>
            </button>
        );
    }
}

interface TaskListViewProps extends AppState {}

export class TaskListView extends React.PureComponent<TaskListViewProps> {
    render() {
        return (
            <div id="task-list">
                {this.props.tasks.map(task => (
                    <TaskListViewItem key={task.id} task={task} isSelected={false} />
                ))}
            </div>
        );
    }
}
