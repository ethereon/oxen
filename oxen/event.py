class EventEmitter:
    """
    A simple pub-sub helper.
    """

    def __init__(self):
        self.subscribers = set()

    def subscribe(self, subscriber):
        self.subscribers.add(subscriber)

    def unsubscribe(self, subscriber, ignore_missing=False):
        try:
            self.subscribers.remove(subscriber)
        except KeyError:
            if not ignore_missing:
                raise

    def publish(self, event):
        # Clone the current subscribers since a subscriber
        # might mutate the subscription in response to a published event.
        for subscriber in set(self.subscribers):
            subscriber(event)

    def is_subscriber(self, handler):
        return handler in self.subscribers
