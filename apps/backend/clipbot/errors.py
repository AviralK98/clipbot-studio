class Blocked(RuntimeError):
    """Configuration or human reconciliation needed; never silently retry."""


class Ambiguous(Blocked):
    """An external mutation may have succeeded. Reconcile before retrying."""


class Deferred(RuntimeError):
    def __init__(self, seconds=60, message="Waiting for provider"):
        super().__init__(message)
        self.seconds = seconds


class Transient(RuntimeError):
    def __init__(self, message="Temporary provider failure", retry_after=60):
        super().__init__(message)
        self.retry_after = retry_after
