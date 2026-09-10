# datahub-linkml-ingestor

Convert XSD schemas into [LinkML](https://linkml.io/) and ingest them into
[DataHub](https://datahubproject.io/) as dataset metadata — schema fields,
structured properties, and semantic mappings (exact/close matches to an
external ontology).

The example schema bundled in this repo (`PrikladOsobaAdresaWS-v1.0.xsd`) is a
synthetic query-by-identifier web-service schema modelled on the structure of
typical Slovak public-administration web services (person + address data),
used purely as a realistic worked example of the pipeline. It is not derived
from any real government-registry schema.

## Pipeline

```
  .xsd  --[xsdToLinkml.py]-->  LinkML .yaml  --[datahub_mcp_generator.py]-->  DataHub MCPs  --[main.py]-->  DataHub
```

1. **`xsdToLinkml.py`** parses an XSD schema (elements, complexTypes,
   sequences, choices, attributes, attributeGroups, simpleContent/
   complexContent extension) into a LinkML schema: classes, slots,
   inheritance (`is_a`), mixins, required/multivalued cardinality, and
   `exact_mappings`/`close_mappings` sourced from `Class`/`ObjectProperty`/
   `DataProperty` appinfo annotations.
2. **`datahub_mcp_generator.py`** (`DatahubMCPGenerator`, a LinkML
   `Generator`) turns a LinkML schema into a stream of DataHub
   `MetadataChangeProposalWrapper` objects: dataset description, schema
   fields (via DataHub's JSON Schema translator), structured properties
   per dataset/field (cardinality, exact/close mappings, and any custom
   annotations declared in a properties-definition file), and global tags
   derived from LinkML slot keywords.
3. **`main.py`** wires the two together and emits the generated MCPs to a
   running DataHub instance over its REST API.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python 3.10+.

## Usage

### 1. XSD → LinkML

```bash
python xsdToLinkml.py PrikladOsobaAdresaWS-v1.0.xsd linkml/priklad/PrikladOsobaAdresaWS-v1.0.yaml
```

`xsdToLinkml.py` only emits `classes:`/`types:` — it does not add the
schema-level `id:`/`name:`/`title:`/`version:` header LinkML requires. Add
that by hand before using the file with `main.py` (see the top of
`linkml/priklad/PrikladOsobaAdresaWS-v1.0.yaml` for the pattern to follow).

### 2. LinkML → DataHub

```bash
cp .env.example .env   # then edit DATAHUB_GMS_SERVER if not running locally
export $(cat .env | xargs)

python main.py linkml/priklad/PrikladOsobaAdresaWS-v1.0.yaml \
  --platform WebService \
  --properties-definition structured_properties/sk.gov.data-props.yml
```

`DATAHUB_GMS_SERVER` defaults to `http://localhost:8080` if unset.

## Repository layout

| Path | Purpose |
|---|---|
| `xsdToLinkml.py` | XSD → LinkML conversion |
| `datahub_mcp_generator.py` | LinkML → DataHub MCP generator |
| `main.py` | CLI entry point: generates and emits MCPs |
| `linkml/` | Example LinkML schemas, including the synthetic `priklad` web-service schema |
| `structured_properties/` | Structured property definitions used during MCP generation |
| `business-glossary/` | Example DataHub business glossary linking terms to ontology URIs |
| `mce/` | Example DataHub bootstrap metadata (platforms, sample entities) |
| `tests/` | Unit tests (pytest) |

## Testing

```bash
pytest -v
```

Tests cover the XSD→LinkML parser (against a small synthetic fixture schema
covering every supported XSD construct) and the pure-logic parts of the
DataHub MCP generator — no running DataHub instance required.

## License

MIT — see [LICENSE](LICENSE).
