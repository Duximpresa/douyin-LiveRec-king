from douyin_live_rec_king.services.retry import RetryCoordinator


class FakeTimer:
    created = []

    def __init__(self, delay, callback, args=()):
        self.delay = delay
        self.callback = callback
        self.args = args
        self.cancelled = False
        FakeTimer.created.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback(*self.args)


def test_retry_delays_deduplicate_and_trigger(monkeypatch) -> None:
    FakeTimer.created.clear()
    monkeypatch.setattr("douyin_live_rec_king.services.retry.threading.Timer", FakeTimer)
    calls = []
    coordinator = RetryCoordinator(calls.append)
    assert coordinator.schedule("task", 1) == 5
    assert coordinator.schedule("task", 2) is None
    assert FakeTimer.created[0].delay == 5
    FakeTimer.created[0].fire()
    assert calls == ["task"]
    assert coordinator.schedule("task", 3) == 45


def test_retry_cancel_and_cancel_all(monkeypatch) -> None:
    FakeTimer.created.clear()
    monkeypatch.setattr("douyin_live_rec_king.services.retry.threading.Timer", FakeTimer)
    coordinator = RetryCoordinator(lambda _task: None)
    coordinator.schedule("one", 1)
    assert coordinator.cancel("one")
    coordinator.schedule("two", 2)
    coordinator.cancel_all()
    assert FakeTimer.created[-1].cancelled
    assert coordinator.schedule("three", 1) is None
