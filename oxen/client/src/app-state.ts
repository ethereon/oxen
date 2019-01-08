import { Task } from './task';

export interface AppState {
    tasks: Array<Task>;
    selectedTask: Task;
}

export interface AppStateSubscriber {
    onNewState: (state: AppState) => void;
}

export class AppStateManager {
    private lastKnownState: AppState;
    private subscribers = new Set<AppStateSubscriber>();
    private webSocket: WebSocket;

    constructor() {
        this.lastKnownState = {
            tasks: [],
            selectedTask: null
        };
        this.webSocket = new WebSocket(`ws://${window.location.host}/tasks`);
        this.webSocket.onmessage = msg => {
            const payload = JSON.parse(msg.data);
            this.setTasks(payload.tasks);
        };
    }

    addSubscriber(subscriber: AppStateSubscriber) {
        this.subscribers.add(subscriber);
        if (this.lastKnownState) {
            subscriber.onNewState(this.lastKnownState);
        }
    }

    removeSubscriber(subscriber: AppStateSubscriber) {
        this.subscribers.delete(subscriber);
    }

    setTasks(tasks: Array<Task>) {
        const newState = Object.assign({}, this.lastKnownState, { tasks });

        // Establish the selected task
        if (newState.tasks.length === 0) {
            // No tasks
            newState.selectedTask = null;
        } else if (this.lastKnownState.selectedTask == null) {
            // No previously selected task
            newState.selectedTask = newState.tasks[0];
        } else {
            // Restore previously selected task if possible
            const selectedTask = newState.tasks.find(
                task => task.id == this.lastKnownState.selectedTask.id
            );
            newState.selectedTask = selectedTask || newState.tasks[0];
        }
        this.setState(newState);
    }

    selectTask(task: Task) {
        this.setState(Object.assign({}, this.lastKnownState, { selectedTask: task }));
    }

    setState(state: AppState) {
        this.lastKnownState = state;
        this.subscribers.forEach(subscriber => subscriber.onNewState(this.lastKnownState));
    }
}

export const appStateManager = new AppStateManager();
