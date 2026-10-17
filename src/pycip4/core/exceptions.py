"""Domain-specific exception hierarchy for pycip4.

All exceptions raised by this library derive from :class:`CIP4Exception`,
allowing callers to catch every pycip4-originated failure with a single
``except CIP4Exception`` clause while still being able to narrow to a
specific failure mode when needed.

Example:
    >>> try:
    ...     raise JDFValidationError("JobID is required on JDF root node")
    ... except CIP4Exception as exc:
    ...     print(f"pycip4 failure: {exc}")
    pycip4 failure: JobID is required on JDF root node
"""

from __future__ import annotations

from typing import Any


class CIP4Exception(Exception):
    """Base class for every exception raised by pycip4.

    Attributes:
        message: Human-readable description of the failure.
        context: Arbitrary structured data useful for diagnostics (e.g. the
            offending XPath, node ID, or raw XML snippet).
    """

    def __init__(self, message: str, *, context: dict[str, Any] | None = None) -> None:
        self.message = message
        self.context = context or {}
        super().__init__(message)

    def __str__(self) -> str:
        if self.context:
            ctx = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
            return f"{self.message} ({ctx})"
        return self.message


class XMLParsingError(CIP4Exception):
    """Raised when raw XML cannot be parsed into an lxml element tree."""


class XSDSchemaValidationError(CIP4Exception):
    """Raised when a document fails validation against a CIP4 XSD schema.

    Attributes:
        errors: The individual ``lxml`` schema error log entries, rendered
            as strings, in document order.
    """

    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.errors = errors or []
        super().__init__(message, context=context)

    def __str__(self) -> str:
        base = super().__str__()
        if self.errors:
            formatted = "\n  - " + "\n  - ".join(self.errors)
            return f"{base}{formatted}"
        return base


class JDFValidationError(CIP4Exception):
    """Raised when a JDF/XJDF document violates library- or domain-level
    integrity rules that are not necessarily expressible in the XSD alone
    (e.g. a ResourceLink pointing to a non-existent Resource, or a missing
    mandatory Intent resource for a given process usage).
    """


class JMFMessageError(CIP4Exception):
    """Raised for structural problems with a JMF message (malformed
    Envelope/Body, unknown message Type, or missing required elements).
    """


class JMFAckError(CIP4Exception):
    """Raised when a JMF message is acknowledged with a non-zero ReturnCode.

    Attributes:
        return_code: The integer ``ReturnCode`` reported by the responder.
        ack_text: The human-readable ``Text`` accompanying the return code,
            if any.
    """

    def __init__(
        self,
        message: str,
        *,
        return_code: int,
        ack_text: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.return_code = return_code
        self.ack_text = ack_text
        super().__init__(message, context=context)


class MIMEPackagingError(CIP4Exception):
    """Raised when a CIP4 MIME multipart package cannot be built or parsed."""


class BuilderError(CIP4Exception):
    """Raised when a fluent builder is used in an invalid order or state
    (e.g. calling ``.build()`` before a mandatory resource has been attached).
    """


class RegistryError(CIP4Exception):
    """Raised by the extensibility registry for unknown or conflicting
    resource/intent/vendor-extension registrations.
    """


class TransportError(CIP4Exception):
    """Raised for network/transport-level failures in the JMF client or
    server (connection refused, timeout, non-2xx HTTP status, etc.).
    """
