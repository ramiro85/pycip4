"""Fluent builder for assembling complete JDF job tickets.

:class:`JDFBuilder` lets callers construct a non-trivial JDF document --
root node, a process node (e.g. ``DigitalPrinting``), its resources
(``Media``, ``RunList``), and the ``ResourceLink``s wiring it all together
-- through chained, descriptive method calls instead of hand-assembling
``CIP4Element`` trees or raw XML strings.

Example:
    >>> jdf = (
    ...     JDFBuilder()
    ...     .product(job_id="Job-42", descriptive_name="Brochure run")
    ...     .digital_printing_process()
    ...     .with_media(dimension="210 297", media_type="Paper", weight=90)
    ...     .with_run_list(url="run.pdf")
    ...     .done()
    ...     .build()
    ... )
    >>> jdf.find_by_type("DigitalPrinting") is not None
    True
"""

from __future__ import annotations

from typing import Self

from pycip4.core.exceptions import BuilderError
from pycip4.core.types import JDFStatus, ResourceUsage
from pycip4.models.jdf import Component, JDFNode, Media, Resource, RunList

__all__ = ["JDFBuilder", "ProcessBuilder"]


class ProcessBuilder:
    """Fluent sub-builder scoped to a single JDF process node.

    Returned by :meth:`JDFBuilder.digital_printing_process` (and friends);
    collects resources onto *that* process node specifically, then hands
    control back to the parent :class:`JDFBuilder` via :meth:`done`.
    """

    def __init__(self, parent: JDFBuilder, node: JDFNode) -> None:
        self._parent = parent
        self._node = node

    @property
    def node(self) -> JDFNode:
        """The underlying JDF process node being configured."""
        return self._node

    def with_media(
        self,
        *,
        dimension: str,
        media_type: str = "Paper",
        weight: float | None = None,
        usage: ResourceUsage = ResourceUsage.INPUT,
        **extra_attributes: str,
    ) -> Self:
        """Attach a ``Media`` resource, linked with the given usage.

        Args:
            dimension: ``Dimension`` attribute, e.g. ``"210 297"`` (mm, w h).
            media_type: ``MediaType`` attribute (``"Paper"``, ``"Film"``, ...).
            weight: Optional substrate weight in gsm (``Weight`` attribute).
            usage: Whether this process consumes (default) or produces the
                media.
            **extra_attributes: Additional ``Media`` attributes
                (e.g. ``Coatings``, ``Grain``).

        Returns:
            ``self``, for continued chaining on this process node.
        """
        media = Media.create("Media", Dimension=dimension, MediaType=media_type, **extra_attributes)
        if weight is not None:
            media.set_attr("Weight", weight)
        self._node.add_and_link_resource(media, usage)
        return self

    def with_run_list(
        self,
        *,
        url: str | None = None,
        usage: ResourceUsage = ResourceUsage.INPUT,
        **extra_attributes: str,
    ) -> Self:
        """Attach a ``RunList`` resource (the content to be processed).

        Args:
            url: If given, wraps the URL in a nested ``LayoutElement``/
                ``RunListURL``-free simple form: a single attribute on the
                RunList itself (``URL``) -- sufficient for the common case
                of "one file, no page-level overrides". Callers needing
                full per-page ``LayoutElement`` structures should build the
                ``RunList`` resource directly and pass it to
                :meth:`with_resource`.
            usage: Whether this process consumes (default) or produces the
                run list.
            **extra_attributes: Additional ``RunList`` attributes.

        Returns:
            ``self``, for continued chaining on this process node.
        """
        attrs = dict(extra_attributes)
        if url is not None:
            attrs["URL"] = url
        run_list = RunList.create("RunList", **attrs)
        self._node.add_and_link_resource(run_list, usage)
        return self

    def with_component(
        self,
        *,
        usage: ResourceUsage = ResourceUsage.OUTPUT,
        **attributes: str,
    ) -> Self:
        """Attach a ``Component`` resource (the physical output product)."""
        component = Component.create("Component", **attributes)
        self._node.add_and_link_resource(component, usage, link_tag="ComponentLink")
        return self

    def with_resource(
        self,
        resource: Resource,
        usage: ResourceUsage,
        *,
        link_tag: str | None = None,
        **link_attributes: str,
    ) -> Self:
        """Attach an arbitrary pre-built resource (custom/dynamic/vendor)."""
        self._node.add_and_link_resource(resource, usage, link_tag=link_tag, **link_attributes)
        return self

    def status(self, status: JDFStatus) -> Self:
        """Set this process node's ``Status``."""
        self._node.status = status
        return self

    def sub_process(self, node_type: str, **attributes: str) -> ProcessBuilder:
        """Nest a child process node under this one and return a builder
        scoped to the new child (for multi-stage workflows, e.g.
        RIP -> Imposition -> DigitalPrinting).
        """
        child = JDFNode.create(
            "JDF",
            Type=node_type,
            Status=JDFStatus.WAITING.value,
            **attributes,
        )
        self._node.add_child_node(child)
        return ProcessBuilder(self._parent, child)

    def done(self) -> JDFBuilder:
        """Return to the parent :class:`JDFBuilder` to continue assembly."""
        return self._parent


class JDFBuilder:
    """Fluent, top-level builder for a complete JDF job ticket.

    Usage is always: start with :meth:`product` (establishes the root
    node), then attach one or more process nodes (e.g.
    :meth:`digital_printing_process`), configure each via the returned
    :class:`ProcessBuilder`, and finish with :meth:`build`.
    """

    def __init__(self) -> None:
        self._root: JDFNode | None = None

    def product(
        self,
        *,
        job_id: str | None = None,
        job_part_id: str | None = None,
        descriptive_name: str | None = None,
        version: str = "1.6",
        **extra_attributes: str,
    ) -> Self:
        """Start the job ticket: create the root ``Product`` JDF node.

        Args:
            job_id: Unique ``JobID``; auto-generated if omitted.
            job_part_id: Unique ``JobPartID``; auto-generated if omitted.
            descriptive_name: Human-readable ``DescriptiveName`` for the job.
            version: JDF schema ``Version``.
            **extra_attributes: Additional root-node attributes.

        Returns:
            ``self``, for chaining into a process-node method next.
        """
        self._root = JDFNode.create_root(
            job_id=job_id, job_part_id=job_part_id, node_type="Product", version=version
        )
        if descriptive_name:
            self._root.set_attr("DescriptiveName", descriptive_name)
        for key, value in extra_attributes.items():
            self._root.set_attr(key, value)
        return self

    def _require_root(self) -> JDFNode:
        if self._root is None:
            raise BuilderError(
                "JDFBuilder.product() must be called before attaching processes"
            )
        return self._root

    def process(self, node_type: str, **attributes: str) -> ProcessBuilder:
        """Attach a generic child process node of the given ``Type``.

        Returns:
            A :class:`ProcessBuilder` scoped to the new process node.
        """
        root = self._require_root()
        node = JDFNode.create(
            "JDF", Type=node_type, Status=JDFStatus.WAITING.value, **attributes
        )
        root.add_child_node(node)
        return ProcessBuilder(self, node)

    def digital_printing_process(self, **attributes: str) -> ProcessBuilder:
        """Convenience for :meth:`process` with ``Type="DigitalPrinting"``."""
        return self.process("DigitalPrinting", **attributes)

    def rip_process(self, **attributes: str) -> ProcessBuilder:
        """Convenience for :meth:`process` with ``Type="RIP"``."""
        return self.process("RIP", **attributes)

    def imposition_process(self, **attributes: str) -> ProcessBuilder:
        """Convenience for :meth:`process` with ``Type="Imposition"``."""
        return self.process("Imposition", **attributes)

    def cutting_process(self, **attributes: str) -> ProcessBuilder:
        """Convenience for :meth:`process` with ``Type="Cutting"``."""
        return self.process("Cutting", **attributes)

    def build(self) -> JDFNode:
        """Finalize and return the assembled root ``JDFNode``.

        Raises:
            BuilderError: If :meth:`product` was never called, or the
                resulting document fails basic link-integrity checks.
        """
        root = self._require_root()
        problems = root.validate_links()
        if problems:
            raise BuilderError(
                "Assembled JDF document has unresolved resource links",
                context={"problems": problems},
            )
        return root

    def to_xml_string(self, *, pretty_print: bool = True) -> str:
        """Build and immediately serialize to an XML string."""
        return self.build().to_xml_string(pretty_print=pretty_print)
