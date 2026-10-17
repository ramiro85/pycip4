"""Shared type aliases, namespace constants, and enumerations for pycip4.

This module centralizes the XML namespace URIs and CIP4-defined vocabularies
(message types, resource usages, ...) so every other module references the
same single source of truth rather than hard-coding strings.
"""

from __future__ import annotations

from enum import Enum, StrEnum
from typing import Final

# --------------------------------------------------------------------------
# XML namespace URIs
# --------------------------------------------------------------------------
#: JDF 1.x / JMF namespace (stable across JDF 1.1 through 1.8).
JDF_NAMESPACE: Final[str] = "http://www.CIP4.org/JDFSchema_1_1"

#: XJDF 2.x namespace.
XJDF_NAMESPACE: Final[str] = "http://www.CIP4.org/JDFSchema_2_0"

#: JMF shares the JDF namespace -- the root element name (``JMF``) is what
#: distinguishes a messaging envelope from a job ticket, not the namespace.
JMF_NAMESPACE: Final[str] = JDF_NAMESPACE

#: XML Schema Instance namespace, used for ``xsi:type`` / ``xsi:schemaLocation``.
XSI_NAMESPACE: Final[str] = "http://www.w3.org/2001/XMLSchema-instance"

#: Default namespace prefix map used when serializing JDF/JMF documents.
#: The ``None`` key binds the default (unprefixed) namespace, per ``lxml``'s
#: ``nsmap`` convention.
JDF_NSMAP: Final[dict[str | None, str]] = {
    None: JDF_NAMESPACE,
    "xsi": XSI_NAMESPACE,
}

#: Default namespace prefix map used when serializing XJDF documents.
XJDF_NSMAP: Final[dict[str | None, str]] = {
    None: XJDF_NAMESPACE,
    "xsi": XSI_NAMESPACE,
}

# --------------------------------------------------------------------------
# MIME content types (CIP4 §7 packaging conventions)
# --------------------------------------------------------------------------
MIME_TYPE_JDF: Final[str] = "application/vnd.cip4-jdf+xml"
MIME_TYPE_JMF: Final[str] = "application/vnd.cip4-jmf+xml"
MIME_TYPE_XJDF: Final[str] = "application/vnd.cip4-xjdf+xml"
MIME_TYPE_PRINTTALK: Final[str] = "application/vnd.cip4-printtalk+xml"


class JDFVersion(StrEnum):
    """Supported JDF major.minor schema versions."""

    V1_1 = "1.1"
    V1_2 = "1.2"
    V1_3 = "1.3"
    V1_4 = "1.4"
    V1_5 = "1.5"
    V1_6 = "1.6"
    V1_7 = "1.7"
    V1_8 = "1.8"


class XJDFVersion(StrEnum):
    """Supported XJDF major.minor schema versions."""

    V2_0 = "2.0"
    V2_1 = "2.1"
    V2_2 = "2.2"


class JDFStatus(StrEnum):
    """Values of the JDF ``Status`` attribute (ICS §6)."""

    WAITING = "Waiting"
    READY = "Ready"
    IN_PROGRESS = "InProgress"
    PART_WAITING = "PartWaiting"
    SUSPENDED = "Suspended"
    CLEANUP = "Cleanup"
    DONE = "Done"
    ABORTED = "Aborted"
    CANCELLED = "Cancelled"


class ResourceUsage(StrEnum):
    """``Usage`` attribute of a JDF ``ResourceLink``."""

    INPUT = "Input"
    OUTPUT = "Output"


class ResourceClass(StrEnum):
    """``Class`` attribute shared by JDF resources and links."""

    CONSUMABLE = "Consumable"
    HANDLING = "Handling"
    IMPLEMENTATION = "Implementation"
    INTENT = "Intent"
    PARAMETER = "Parameter"
    PLACEHOLDER = "Placeholder"
    QUANTITY = "Quantity"


class JMFMessageFamily(StrEnum):
    """The five JMF message families (JMF §3.2)."""

    COMMAND = "Command"
    QUERY = "Query"
    RESPONSE = "Response"
    SIGNAL = "Signal"
    ACKNOWLEDGE = "Acknowledge"


class JMFMessageType(StrEnum):
    """Common JMF ``Type`` values.

    Not exhaustive by design -- unrecognized types are still accepted by
    :class:`~pycip4.models.jmf.JMFMessage` since ``Type`` is an open string
    vocabulary extensible by vendors and future ICS revisions.
    """

    KNOWN_DEVICES = "KnownDevices"
    STATUS = "Status"
    STATUS_SIGNAL = "Status"
    SUBMIT_QUEUE_ENTRY = "SubmitQueueEntry"
    QUEUE_STATUS = "QueueStatus"
    RESOURCE = "Resource"
    NOTIFICATION = "Notification"
    STOP_PERSISTENT_CHANNEL = "StopPersistentChannel"
    PIPE_PULL = "PipePull"


class JMFAcknowledgeCode(int, Enum):
    """Common ``ReturnCode`` values for JMF ``Acknowledge`` messages."""

    OK = 0
    GENERAL_ERROR = 1
    FORMAT_ERROR = 100
    PERMISSION_DENIED = 101
    DEVICE_NOT_FOUND = 102
    UNKNOWN_MESSAGE_TYPE = 103
