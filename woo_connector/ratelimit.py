import threading
import time


class TokenBucket:
    """Client-side limiter so the agent can't hammer a merchant's store."""

    def __init__(self, rate, capacity=None, clock=time.monotonic, sleep=time.sleep):
        self.rate = max(rate, 0.1)
        self.capacity = capacity or max(1.0, self.rate)
        self.tokens = self.capacity
        self.clock, self.sleep = clock, sleep
        self.last = clock()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = self.clock()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            self.sleep(wait)
