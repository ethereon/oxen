from __future__ import annotations
from collections.abc import Callable

type Subscriber[T] = Callable[[T], None]


class Subscription[T]:
    __slots__ = ('active', 'callback', 'publisher')

    def __init__(self, publisher: Publisher[T], callback: Subscriber[T]):
        self.publisher: Publisher[T] | None = publisher
        self.callback = callback
        self.active = True

    def __call__(self) -> None:
        if self.publisher is None:
            return

        publisher, self.publisher = self.publisher, None
        publisher._unsubscribe(self)


class Publisher[T]:
    def __init__(self):
        self._subs: list[Subscription[T]] = []
        self._publishing = 0
        self._needs_compact = False

    def subscribe(self, callback: Subscriber[T]) -> Subscription[T]:
        subscription = Subscription(self, callback)
        self._subs.append(subscription)
        return subscription

    def publish(self, value: T) -> None:
        """
        Publish a value to all active subscribers.

        It is safe to both subscribe and unsubscribe from within a subscriber callback.
        However, subscriptions added during publishing won't be called until the next publish.
        """
        self._publishing += 1
        end = len(self._subs)

        try:
            # Removals are deferred until after publishing finishes to avoid
            # mutating the list while iterating.
            # New subscriptions during publishing are safe (added past iteration end)
            # but won't be called until the next publish.
            for i in range(end):
                sub = self._subs[i]
                if sub.active:
                    sub.callback(value)
        finally:
            self._publishing -= 1

            if self._publishing == 0 and self._needs_compact:
                # Prune inactive subscriptions
                self._subs = [sub for sub in self._subs if sub.active]
                self._needs_compact = False

    def clear(self) -> None:
        for sub in self._subs:
            sub.active = False
            sub.publisher = None

        if self._publishing:
            self._needs_compact = True
        else:
            self._subs.clear()

    @classmethod
    def clear_all(cls, *publishers: Publisher) -> None:
        for publisher in publishers:
            publisher.clear()

    def _unsubscribe(self, subscription: Subscription[T]) -> None:
        if not subscription.active:
            # Will be pruned during deferred compaction.
            return

        subscription.active = False

        if self._publishing:
            # Defer removal until after publishing finishes to avoid mutating the list while iterating.
            self._needs_compact = True
        else:
            # Safe to eagerly remove.
            self._subs.remove(subscription)


class SubscriptionStore:
    def __init__(self, *subs: Subscription):
        self.subscriptions = subs

    def add(self, *subs: Subscription) -> None:
        self.subscriptions += subs

    def clear(self) -> None:
        subs, self.subscriptions = self.subscriptions, ()
        for sub in subs:
            sub()
