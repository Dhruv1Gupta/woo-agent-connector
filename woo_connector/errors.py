class WooError(Exception):
    """Base error. Messages never contain credentials."""
    status = None

    def __init__(self, message, status=None, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


class ConfigError(WooError):
    pass


class AuthError(WooError):
    pass


class NotFoundError(WooError):
    pass


class RateLimitError(WooError):
    pass


class UpstreamError(WooError):
    pass


class ValidationError(WooError):
    pass
