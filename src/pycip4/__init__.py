"""pycip4 -- modern, high-performance Python tooling for CIP4 print workflows.

Supports JDF (Job Definition Format 1.1-1.8), JMF (Job Messaging Format),
XJDF (Exchange JDF 2.0+), and CIP4 MIME multipart packaging.

Quick start:
    >>> from pycip4 import JDFBuilder, ResourceUsage
    >>> jdf = (
    ...     JDFBuilder()
    ...     .product(job_id="Job-1")
    ...     .digital_printing_process()
    ...     .with_media(dimension="210 297")
    ...     .done()
    ...     .build()
    ... )
    >>> jdf.job_id
    'Job-1'
"""

from __future__ import annotations

from pycip4.builder.jdf_builder import JDFBuilder, ProcessBuilder
from pycip4.core.exceptions import (
    BuilderError,
    CIP4Exception,
    JDFValidationError,
    JMFAckError,
    JMFMessageError,
    MIMEPackagingError,
    RegistryError,
    TransportError,
    XMLParsingError,
    XSDSchemaValidationError,
)
from pycip4.core.types import (
    JDF_NAMESPACE,
    JMF_NAMESPACE,
    XJDF_NAMESPACE,
    JDFStatus,
    JDFVersion,
    JMFAcknowledgeCode,
    JMFMessageFamily,
    JMFMessageType,
    ResourceClass,
    ResourceUsage,
    XJDFVersion,
)
from pycip4.messaging.jmf_client import JMFClient
from pycip4.messaging.jmf_server import JMFServer
from pycip4.models.base import CIP4Element, CIP4Node, register_node
from pycip4.models.jdf import (
    Component,
    ComponentLink,
    JDFNode,
    Media,
    Resource,
    ResourceLink,
    ResourceLinkPool,
    ResourcePool,
    RunList,
)
from pycip4.models.jmf import (
    JMFAcknowledge,
    JMFCommand,
    JMFEnvelope,
    JMFMessage,
    JMFQuery,
    JMFResponse,
    JMFSignal,
    build_acknowledge,
    build_command,
    build_query,
    build_response,
    build_signal,
)
from pycip4.models.xjdf import Parameter, Product, ResourceSet, Set, XJDFNode
from pycip4.parser.schema_validator import SchemaValidator
from pycip4.parser.xml_parser import CIP4Parser, iter_parse_jdf_nodes

__version__ = "0.1.1"

__all__ = [
    "__version__",
    # core
    "CIP4Exception",
    "XMLParsingError",
    "XSDSchemaValidationError",
    "JDFValidationError",
    "JMFMessageError",
    "JMFAckError",
    "MIMEPackagingError",
    "BuilderError",
    "RegistryError",
    "TransportError",
    "JDF_NAMESPACE",
    "JMF_NAMESPACE",
    "XJDF_NAMESPACE",
    "JDFVersion",
    "XJDFVersion",
    "JDFStatus",
    "ResourceUsage",
    "ResourceClass",
    "JMFMessageFamily",
    "JMFMessageType",
    "JMFAcknowledgeCode",
    # models - base
    "CIP4Element",
    "CIP4Node",
    "register_node",
    # models - jdf
    "JDFNode",
    "Resource",
    "ResourceLink",
    "ResourcePool",
    "ResourceLinkPool",
    "Media",
    "RunList",
    "Component",
    "ComponentLink",
    # models - jmf
    "JMFEnvelope",
    "JMFMessage",
    "JMFQuery",
    "JMFCommand",
    "JMFSignal",
    "JMFResponse",
    "JMFAcknowledge",
    "build_query",
    "build_command",
    "build_signal",
    "build_response",
    "build_acknowledge",
    # models - xjdf
    "XJDFNode",
    "Product",
    "ResourceSet",
    "Set",
    "Parameter",
    # parser
    "CIP4Parser",
    "iter_parse_jdf_nodes",
    "SchemaValidator",
    # builder
    "JDFBuilder",
    "ProcessBuilder",
    # messaging
    "JMFClient",
    "JMFServer",
]
