"""Validation of CIP4 documents against official XSD schemas.

pycip4 does not bundle the (large, multi-file, versioned) official CIP4
XSD schema sets -- callers point :class:`SchemaValidator` at a local copy
of the schema they need (downloaded once from https://www.cip4.org/ or
vendored in the consuming application) via its root ``.xsd`` file path or
URL. Schemas are compiled once and cached per path for the lifetime of the
validator instance.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from lxml import etree

from pycip4.core.exceptions import XMLParsingError, XSDSchemaValidationError
from pycip4.models.base import CIP4Element


def _iter_error_log(error_log: etree._ErrorLog) -> list[Any]:
    """Iterate an ``lxml`` error log.

    ``lxml-stubs`` ships ``_ErrorLog`` as an empty stub with no ``__iter__``,
    even though it is iterable at runtime; this centralizes the one cast
    needed to work around that gap.
    """
    return cast(list[Any], error_log)


@lru_cache(maxsize=16)
def _load_schema(schema_path: str) -> etree.XMLSchema:
    """Compile and cache an ``XMLSchema`` for a given root ``.xsd`` path."""
    try:
        schema_doc = etree.parse(schema_path)
        return etree.XMLSchema(schema_doc)
    except etree.XMLSchemaParseError as exc:
        raise XSDSchemaValidationError(
            f"Failed to compile XSD schema at {schema_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise XSDSchemaValidationError(
            f"Could not read XSD schema at {schema_path}: {exc}"
        ) from exc


class SchemaValidator:
    """Validates CIP4 XML documents against an official (or custom) XSD.

    Example:
        >>> validator = SchemaValidator("/schemas/JDF.xsd")  # doctest: +SKIP
        >>> validator.validate(my_jdf_node)  # doctest: +SKIP
    """

    def __init__(self, schema_path: str | Path) -> None:
        """Args:
        schema_path: Filesystem path to the schema's root ``.xsd`` file.
            Imported/included sub-schemas are resolved relative to it by
            ``lxml`` automatically.
        """
        self._schema_path = str(schema_path)

    @property
    def schema(self) -> etree.XMLSchema:
        """The compiled (and cached) ``lxml`` schema object."""
        return _load_schema(self._schema_path)

    def validate(self, document: CIP4Element | str | bytes) -> None:
        """Validate a document, raising on any schema violation.

        Args:
            document: A pycip4 model instance (serialized on the fly), or
                raw XML as a string/bytes.

        Raises:
            XSDSchemaValidationError: If the document does not conform to
                the schema. The exception's ``errors`` attribute lists
                every individual violation found.
            XMLParsingError: If ``document`` is not well-formed XML.
        """
        element = self._to_element(document)
        if not self.schema.validate(element):
            errors = [str(err) for err in _iter_error_log(self.schema.error_log)]
            raise XSDSchemaValidationError(
                f"Document failed validation against schema {self._schema_path}",
                errors=errors,
            )

    def is_valid(self, document: CIP4Element | str | bytes) -> bool:
        """Non-raising check: ``True`` if ``document`` conforms to the schema."""
        element = self._to_element(document)
        return bool(self.schema.validate(element))

    def iter_errors(self, document: CIP4Element | str | bytes) -> list[str]:
        """Return every validation error message without raising."""
        element = self._to_element(document)
        if self.schema.validate(element):
            return []
        return [str(err) for err in _iter_error_log(self.schema.error_log)]

    @staticmethod
    def _to_element(document: CIP4Element | str | bytes) -> etree._Element:
        if isinstance(document, CIP4Element):
            return document.to_xml_element()
        try:
            raw = document.encode("utf-8") if isinstance(document, str) else document
            parser = etree.XMLParser(resolve_entities=False, no_network=True)
            return etree.fromstring(raw, parser=parser)
        except etree.XMLSyntaxError as exc:
            raise XMLParsingError(f"Malformed XML passed to schema validator: {exc}") from exc
