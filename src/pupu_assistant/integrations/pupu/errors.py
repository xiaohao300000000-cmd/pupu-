class PupuClientError(RuntimeError):
    """Base class for sanitized Pupu client failures."""


class SignaturePolicyViolation(PupuClientError):
    """The returned signature mode did not meet the route policy."""


class PupuTransportError(PupuClientError):
    """Base class for network transport failures."""


class PupuTimeoutError(PupuTransportError):
    """The Pupu request timed out."""


class PupuTlsError(PupuTransportError):
    """TLS negotiation or verification failed."""


class PupuNetworkError(PupuTransportError):
    """A non-TLS network failure occurred."""


class PupuHttpStatusError(PupuClientError):
    """Pupu returned a non-successful HTTP status."""


class PupuResponseDecodeError(PupuClientError):
    """Pupu returned a response that was not valid JSON."""


class PupuBusinessError(PupuClientError):
    """Pupu returned a non-zero business error code."""
