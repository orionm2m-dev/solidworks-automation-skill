"""仅模拟原生传输；被测模块自己的状态机、验证和磁盘证据保持真实。"""
class NativeBoundary:
    def __init__(self, *args, **kwargs):
        self.callbacks = kwargs
        self.attempted = self.returned = self.claimed = False
    def _check(self):
        for name in ('verify_evidence', 'verify_owned_process', 'check_events'):
            self.callbacks[name]()
    def __enter__(self):
        self._check()
        return self
    def __exit__(self, *args):
        self._check()
    def summary(self):
        return dict(invalid=False, native_call_attempted=self.attempted,
                    native_call_returned=self.returned, claimed=self.claimed)
    def typed(self, obj, name):
        return obj
    def read(self, obj, name, *args):
        if isinstance(obj, list):
            return len(obj) if name == 'Count' else obj[args[0]]
        return obj[name]
    def dispatch_once(self, invoke, persist_pending):
        self._check()
        persist_pending()
        self.claimed = self.attempted = True
        result = invoke()
        self.returned = True
        self._check()
        return result


class EventSession:
    def __init__(self, *args):
        self.active = False
    def __enter__(self):
        self.active = True
        return self
    def __exit__(self, *args):
        self.active = False
    def summary(self):
        return dict(subscribed=True, active=self.active, disconnected=not self.active,
                    event_count=0, overflow=False, callback_errors=[], disconnect_errors=[])
