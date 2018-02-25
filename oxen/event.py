class EventEmitter:
    """
    A simple pub-sub helper.
    """

    def __init__(self):
        self.subscribers = set()

    def subscribe(self, subscriber):
        self.subscribers.add(subscriber)

    def unsubscribe(self, subscriber):
        self.subscribers.remove(subscriber)

    def publish(self, event):
        # Clone the current subscribers since a subscriber
        # might mutate the subscription in response to a published event.
        for subscriber in set(self.subscribers):
            subscriber(event)
