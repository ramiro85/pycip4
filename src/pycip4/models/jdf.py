"""JDF (Job Definition Format 1.x) tree-structured document model.

A JDF document is a tree of ``JDF`` process nodes. Each node may carry:

* A ``ResourcePool`` -- the actual resources (``Media``, ``RunList``,
  ``ComponentLink``, custom/dynamic resources, ...) owned by this node or
  shared with ancestors/descendants via ``rRef``.
* A ``ResourceLinkPool`` -- typed references (``Usage="Input"|"Output"``)
  from this process node to resources, by ``rRef``.
* Child ``JDF`` nodes, forming the process tree (e.g. a ``ProcessGroup``
  containing ``RIP``, ``Imposition``, and ``DigitalPrinting`` children).

This module keeps the tree-structured intent/process model strictly
separate from the flat XJDF product/job/set model in
:mod:`pycip4.models.xjdf`, per CIP4's own architectural split between the
two formats.
"""

from __future__ import annotations

from typing import Self, cast

from pycip4.core.exceptions import JDFValidationError
from pycip4.core.types import JDFStatus, ResourceUsage
from pycip4.models.base import (
    CIP4Element,
    CIP4Node,
    generate_id,
    register_node,
    register_suffix_node,
)


@register_node("ResourceLink")
@register_suffix_node("Link")
class ResourceLink(CIP4Element):
    """A ``ResourceLink`` element: a typed reference from a process node to
    a resource living in some (not necessarily the same) ``ResourcePool``.

    Covers both the generic ``<ResourceLink>`` tag and every
    ``{ResourceName}Link`` convention tag (``MediaLink``, ``RunListLink``,
    custom/dynamic resource links, ...) via the suffix registry -- any of
    those are structurally identical for pycip4's purposes.
    """

    XML_TAG = "ResourceLink"

    @property
    def r_ref(self) -> str | None:
        """The ``rRef`` of the resource this link points to."""
        return self.get_attr("rRef")

    @property
    def usage(self) -> ResourceUsage | None:
        """Whether this link is an ``Input`` or ``Output`` to the process."""
        raw = self.get_attr("Usage")
        return ResourceUsage(raw) if raw else None


class Resource(CIP4Element):
    """A generic JDF resource (``Media``, ``RunList``, ``ComponentLink``,
    or any custom/dynamic resource registered via :func:`register_node`).
    """

    @property
    def resource_id(self) -> str | None:
        """The resource's own ``ID``, referenced by ``ResourceLink.rRef``."""
        return self.get_attr("ID")

    @property
    def resource_status(self) -> JDFStatus | None:
        raw = self.get_attr("ResourceStatus")
        return JDFStatus(raw) if raw else None


@register_node("Media")
class Media(Resource):
    """The ``Media`` resource: substrate/stock the job is printed on."""

    XML_TAG = "Media"


@register_node("RunList")
class RunList(Resource):
    """The ``RunList`` resource: ordered list of content (pages/layouts)."""

    XML_TAG = "RunList"


@register_node("ComponentLink")
class ComponentLink(ResourceLink):
    """A link to a ``Component`` resource (finished/intermediate product)."""

    XML_TAG = "ComponentLink"


@register_node("Component")
class Component(Resource):
    """The ``Component`` resource: a physical product (sheet, book, ...)."""

    XML_TAG = "Component"


@register_node("ResourcePool")
class ResourcePool(CIP4Element):
    """Container for the resources owned/exposed by one JDF process node."""

    XML_TAG = "ResourcePool"

    def resources(self) -> list[Resource]:
        """Return every child resource in this pool.

        Every :class:`CIP4Element` already exposes the plain attribute
        accessors ``Resource`` relies on, so this is a safe reinterpretation
        even for custom/vendor resource tags that have no specifically
        registered subclass.
        """
        return cast(list[Resource], self.children)

    def get_resource(self, resource_id: str) -> Resource | None:
        """Find a resource in this pool by its ``ID``."""
        for child in self.children:
            if child.get_attr("ID") == resource_id:
                return cast(Resource, child)
        return None


@register_node("ResourceLinkPool")
class ResourceLinkPool(CIP4Element):
    """Container for the ``ResourceLink`` elements of one JDF process node."""

    XML_TAG = "ResourceLinkPool"

    def links(self) -> list[ResourceLink]:
        """Return every resource link in this pool.

        Every ``*Link``-suffixed tag dispatches to (at least)
        :class:`ResourceLink` via the suffix registry
        (:func:`~pycip4.models.base.register_suffix_node`), so this cast is
        backed by the actual parsing/construction guarantee, not just a hope.
        """
        return cast(list[ResourceLink], self.children)


@register_node("JDF")
class JDFNode(CIP4Node):
    """A single ``JDF`` node within the JDF process tree.

    A JDF document is, itself, just the root ``JDFNode`` of this tree --
    there is no separate "document" wrapper type, mirroring the spec.

    Example:
        >>> root = JDFNode.create_root(job_id="Job-001", job_part_id="JP-1")
        >>> root.types
        ['Product']
    """

    XML_TAG = "JDF"

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    @classmethod
    def create_root(
        cls,
        *,
        job_id: str | None = None,
        job_part_id: str | None = None,
        node_type: str = "Product",
        version: str = "1.6",
        status: JDFStatus = JDFStatus.WAITING,
    ) -> Self:
        """Create a new root ``JDF`` node with mandatory root attributes.

        Args:
            job_id: Unique ``JobID`` for the top-level job. Auto-generated
                if omitted.
            job_part_id: ``JobPartID``, unique within the ``JobID`` scope.
                Auto-generated if omitted.
            node_type: The JDF ``Type`` (e.g. ``"Product"``,
                ``"DigitalPrinting"``, ``"ProcessGroup"``).
            version: JDF schema ``Version`` (``"1.1"`` through ``"1.8"``).
            status: Initial ``Status`` of the node.

        Returns:
            A new, resource-pool-free root node.
        """
        return cls.create(
            "JDF",
            ID=generate_id("N"),
            JobID=job_id or generate_id("Job"),
            JobPartID=job_part_id or generate_id("JP"),
            Type=node_type,
            Version=version,
            Status=status.value,
        )

    # ------------------------------------------------------------------ #
    # Attribute accessors
    # ------------------------------------------------------------------ #

    @property
    def job_id(self) -> str | None:
        return self.get_attr("JobID")

    @property
    def job_part_id(self) -> str | None:
        return self.get_attr("JobPartID")

    @property
    def node_type(self) -> str | None:
        return self.get_attr("Type")

    @property
    def status(self) -> JDFStatus | None:
        raw = self.get_attr("Status")
        return JDFStatus(raw) if raw else None

    @status.setter
    def status(self, value: JDFStatus) -> None:
        self.set_attr("Status", value)

    @property
    def types(self) -> list[str]:
        """The (space-separated) ``Types`` attribute as a list, for combined
        process nodes (e.g. ``Types="Imposition RIP"``). Falls back to a
        single-item list derived from ``Type`` when ``Types`` is absent.
        """
        raw = self.get_attr("Types")
        if raw:
            return raw.split()
        return [self.node_type] if self.node_type else []

    # ------------------------------------------------------------------ #
    # Resource pool / link pool access
    # ------------------------------------------------------------------ #

    @property
    def resource_pool(self) -> ResourcePool | None:
        found = self.find_first("ResourcePool")
        return found  # type: ignore[return-value]

    @property
    def resource_link_pool(self) -> ResourceLinkPool | None:
        found = self.find_first("ResourceLinkPool")
        return found  # type: ignore[return-value]

    def ensure_resource_pool(self) -> ResourcePool:
        """Return this node's ``ResourcePool``, creating an empty one if absent."""
        pool = self.resource_pool
        if pool is None:
            pool = ResourcePool.create("ResourcePool")
            self.children.insert(0, pool)
        return pool

    def ensure_resource_link_pool(self) -> ResourceLinkPool:
        """Return this node's ``ResourceLinkPool``, creating an empty one if absent."""
        pool = self.resource_link_pool
        if pool is None:
            pool = ResourceLinkPool.create("ResourceLinkPool")
            # Convention: ResourceLinkPool follows ResourcePool, precedes child JDF nodes.
            insert_at = 1 if self.resource_pool is not None else 0
            self.children.insert(insert_at, pool)
        return pool

    def add_resource(self, resource: Resource) -> Self:
        """Add a resource to this node's ``ResourcePool`` (creating it if needed)."""
        if resource.get_attr("ID") is None:
            resource.set_attr("ID", generate_id("R"))
        self.ensure_resource_pool().add_child(resource)
        return self

    def link_resource(
        self,
        resource: Resource,
        usage: ResourceUsage,
        *,
        link_tag: str | None = None,
        **extra_attributes: str,
    ) -> Self:
        """Link an already-added resource to this node via a ``ResourceLink``.

        Args:
            resource: The target resource (must already carry an ``ID``,
                typically because it was added via :meth:`add_resource`).
            usage: Whether this node consumes (``Input``) or produces
                (``Output``) the resource.
            link_tag: Explicit link element tag (e.g. ``"MediaLink"``).
                Defaults to ``f"{resource.tag}Link"``, the standard CIP4
                naming convention.
            **extra_attributes: Additional attributes for the link element
                (e.g. ``CombinedProcessIndex``).

        Returns:
            ``self``, for fluent chaining.

        Raises:
            JDFValidationError: If ``resource`` has no ``ID`` to link against.
        """
        if resource.resource_id is None:
            raise JDFValidationError(
                f"Cannot link resource {resource.tag!r} without an ID; "
                "add it via add_resource() first or set an explicit ID.",
            )
        tag = link_tag or f"{resource.tag}Link"
        link = ResourceLink.create(tag, rRef=resource.resource_id, Usage=usage.value)
        for key, value in extra_attributes.items():
            link.set_attr(key, value)
        self.ensure_resource_link_pool().add_child(link)
        return self

    def add_and_link_resource(
        self,
        resource: Resource,
        usage: ResourceUsage,
        *,
        link_tag: str | None = None,
        **extra_attributes: str,
    ) -> Self:
        """Convenience: :meth:`add_resource` followed by :meth:`link_resource`."""
        self.add_resource(resource)
        return self.link_resource(resource, usage, link_tag=link_tag, **extra_attributes)

    def resolve_link(self, link: ResourceLink) -> Resource | None:
        """Resolve a ``ResourceLink`` to its target ``Resource``.

        Searches this node's own pool first, then walks up through
        ancestors is *not* performed here (this model does not track parent
        pointers); callers working with a full document should resolve via
        :meth:`JDFNode.find_resource_by_id` from the document root instead.
        """
        pool = self.resource_pool
        if pool is None or link.r_ref is None:
            return None
        return pool.get_resource(link.r_ref)

    def find_resource_by_id(self, resource_id: str) -> Resource | None:
        """Search this node and every descendant for a resource with the
        given ``ID`` -- the correct way to resolve a ``ResourceLink`` from
        anywhere in the document, since JDF resources may be shared/hoisted
        to an ancestor node's pool.
        """
        if self.resource_pool is not None:
            found = self.resource_pool.get_resource(resource_id)
            if found is not None:
                return found
        for child in self.children:
            if isinstance(child, JDFNode):
                found = child.find_resource_by_id(resource_id)
                if found is not None:
                    return found
        return None

    # ------------------------------------------------------------------ #
    # Process tree navigation
    # ------------------------------------------------------------------ #

    def child_nodes(self) -> list[JDFNode]:
        """Return direct child ``JDF`` process nodes (excludes pools)."""
        return [c for c in self.children if isinstance(c, JDFNode)]

    def add_child_node(self, child: JDFNode) -> Self:
        """Append a child JDF process node and return ``self`` for chaining."""
        self.children.append(child)
        return self

    def find_by_type(self, node_type: str) -> JDFNode | None:
        """Depth-first search for the first descendant (or self) node whose
        ``Type``/``Types`` includes ``node_type``.
        """
        if node_type in self.types:
            return self
        for child in self.child_nodes():
            found = child.find_by_type(node_type)
            if found is not None:
                return found
        return None

    def validate_links(self) -> list[str]:
        """Validate that every ``ResourceLink`` in this subtree resolves to
        an actual resource somewhere in the document.

        Returns:
            A list of human-readable problem descriptions; empty if the
            subtree is fully consistent.
        """
        problems: list[str] = []
        link_pool = self.resource_link_pool
        if link_pool is not None:
            for link in link_pool.links():
                if link.r_ref is None:
                    problems.append(f"{link.tag} on node {self.id_or_type()} has no rRef")
                elif self.find_resource_by_id(link.r_ref) is None:
                    problems.append(
                        f"{link.tag} on node {self.id_or_type()} references "
                        f"unresolved rRef={link.r_ref!r}"
                    )
        for child in self.child_nodes():
            problems.extend(child.validate_links())
        return problems

    def id_or_type(self) -> str:
        """Short diagnostic label: the node's ``ID`` if set, else its type."""
        return self.get_attr("ID") or self.node_type or "JDF"
