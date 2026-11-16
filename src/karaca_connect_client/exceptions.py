"""Public client exceptions. Never include credentials or response bodies."""


class KaracaError(Exception):
    """Base error for Karaca cloud requests."""


class KaracaAuthError(KaracaError):
    """Authentication failed or credentials need attention."""


class KaracaConnectionError(KaracaError):
    """Connection or response format failed."""


class KaracaServiceError(KaracaError):
    """The service is temporarily unavailable."""


class KaracaRateLimitError(KaracaServiceError):
    """Cloud API request frequency was limited."""


class KaracaDeviceNotFound(KaracaError):
    """No matching device was found."""


class KaracaApiError(KaracaError):
    """Cloud API rejected the request."""
