import * as React from 'react';
import { TaskListView } from './task-list-view';
import { AppState, appStateManager } from './app-state';
import { TaskView } from './task-view';

type AppViewProps = {};

interface AppViewState extends AppState {}

export class AppView extends React.Component<AppViewProps, AppViewState> {
    componentDidMount() {
        appStateManager.addSubscriber(this);
    }

    componentWillUnmount() {
        appStateManager.removeSubscriber(this);
    }

    onNewState(state: AppState) {
        this.setState(state);
    }

    render() {
        if (this.state == null) {
            return <p>Loading...</p>;
        }
        return (
            <React.Fragment>
                <TaskListView tasks={this.state.tasks} selectedTask={this.state.selectedTask} />
                {this.state.selectedTask && <TaskView task={this.state.selectedTask} />}
            </React.Fragment>
        );
    }
}
