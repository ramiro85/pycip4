# pycip4

A modern, high-performance Python 3.11+ library for CIP4 print-workflow
automation: **JDF** (Job Definition Format 1.1-1.8), **JMF** (Job Messaging
Format), **XJDF** (Exchange JDF 2.0+), and CIP4 **MIME multipart** packaging.

- **Fast XML**: built on `lxml` (parsing, XPath, XSD validation, streaming
  `iterparse` for huge job tickets).
- **Typed models**: every element is a `pydantic` v2 model with typed
  convenience accessors layered over a generic, extensible node core.
- **Fluent builders**: assemble complete JDF job tickets -- processes,
  resources, resource links -- without touching raw XML.
- **Async messaging**: an `aiohttp`-based JMF server and an `httpx`-based
  JMF client for Query/Command/Signal/Response/Acknowledge exchange.
- **Extensible by design**: register custom resources, dynamic intents, or
  vendor namespaces via a decorator-based registry -- no monkey-patching.
- **100% typed**: passes `mypy --strict`.

## Install

```bash
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Quick start

### Build a JDF job ticket

```python
from pycip4 import JDFBuilder, ResourceUsage

jdf = (
    JDFBuilder()
    .product(job_id="Job-42", descriptive_name="Brochure run")
    .digital_printing_process()
        .with_media(dimension="210 297", media_type="Paper", weight=90)
        .with_run_list(url="run.pdf")
        .with_component(usage=ResourceUsage.OUTPUT, ComponentType="Sheet")
        .done()
    .build()
)

print(jdf.to_xml_string())
assert jdf.validate_links() == []  # every ResourceLink resolves
```

### Parse any CIP4 document

```python
from pycip4 import CIP4Parser

node = CIP4Parser().parse_file("job.jdf")  # auto-detects JDF / JMF / XJDF
```

### Stream a huge JDF file

```python
from pycip4 import iter_parse_jdf_nodes

for node in iter_parse_jdf_nodes("huge_job.jdf"):
    print(node.job_id, node.node_type)
```

### Run a JMF responder

```python
from pycip4 import JMFServer
from pycip4.messaging.jmf_server import known_devices_handler_factory

server = JMFServer(device_id="Press-01")
server.on_query("KnownDevices")(
    known_devices_handler_factory("Press-01", "Idle", "DigitalPrinting")
)

@server.on_command("SubmitQueueEntry")
async def submit(message, request):
    return {"QueueEntryID": "QE-001"}

server.run(host="0.0.0.0", port=8080)
```

### Query a JMF device

```python
import asyncio
from pycip4 import JMFClient

async def main():
    async with JMFClient("http://press.local:8080/jmf") as client:
        response = await client.query("KnownDevices")
        print(response.get_attr("DeviceID"), response.get_attr("DeviceStatus"))

asyncio.run(main())
```

### Validate against an official XSD

```python
from pycip4 import SchemaValidator

validator = SchemaValidator("/path/to/JDF.xsd")
validator.validate(jdf)  # raises XSDSchemaValidationError on violation
```

## Architecture

```
src/pycip4/
├── core/
│   ├── exceptions.py   # CIP4Exception hierarchy
│   └── types.py        # namespaces, MIME types, enums
├── models/
│   ├── base.py          # CIP4Element / CIP4Node + extensibility registry
│   ├── jdf.py            # tree-structured JDF: resources, links, process tree
│   ├── jmf.py             # Query/Command/Response/Signal/Acknowledge envelopes
│   └── xjdf.py            # flat XJDF: Product/ResourceSet/Set/Parameter
├── parser/
│   ├── xml_parser.py       # CIP4Parser + streaming iter_parse_jdf_nodes
│   └── schema_validator.py # XSD validation via lxml.etree.XMLSchema
├── builder/
│   └── jdf_builder.py       # fluent JDFBuilder / ProcessBuilder
├── messaging/
│   ├── jmf_client.py          # async httpx-based JMF client
│   └── jmf_server.py           # async aiohttp-based JMF responder
└── utils/
    └── mime.py                  # CIP4 MIME multipart build/parse
```

**JDF vs. XJDF** are modeled as deliberately separate subsystems
(`models/jdf.py` vs. `models/xjdf.py`): JDF's recursive process tree with
`ResourcePool`/`ResourceLinkPool` indirection is structurally nothing like
XJDF's flat `Product`/`ResourceSet`/`Parameter` shape, and conflating them
would reintroduce the exact ambiguity CIP4 designed XJDF to remove.

**Extensibility** runs through `pycip4.models.base.register_node` (exact
tag match) and `register_suffix_node` (tag-suffix fallback, used for JDF's
open-ended `*Link` family). Register a class for a proprietary vendor
resource or namespace and the parser will dispatch to it automatically --
no core code changes required:

```python
from pycip4.models.base import CIP4Element, register_node

@register_node("AcmeCustomResource", namespace="urn:acme:vendor")
class AcmeCustomResource(CIP4Element):
    ...
```

## Development

```bash
pip install -e ".[dev]"
pytest                    # run the test suite
mypy src/pycip4 tests/       # strict type checking
ruff check src/pycip4 tests/ # linting
black src/pycip4 tests/      # formatting
```

## Standards coverage

| Format | Versions  | Notes                                               |
|--------|-----------|-----------------------------------------------------|
| JDF    | 1.1 - 1.8 | Tree-structured process/resource model              |
| JMF    | 1.x       | Query, Command, Response, Signal, Acknowledge       |
| XJDF   | 2.0 - 2.2 | Flat Product/Set/Parameter/ResourceSet model        |
| MIME   | --        | `application/vnd.cip4-{jdf,jmf,xjdf}+xml` packaging |

pycip4 does not bundle official CIP4 XSD schemas (large, versioned,
multi-file) -- point `SchemaValidator` at a local copy for strict
conformance checking.

## License

Apache-2.0
