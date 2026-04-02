# RPC OpenAPI Generation Guide

This folder contains the source fragments and generator used to build the unified OpenAPI spec consumed by the Docusaurus OpenAPI plugin.

## Why this exists

Our RPC docs are authored as modular OpenRPC-like JSON files (methods, schemas, and content descriptors), but the Docusaurus plugin expects a single OpenAPI document.

The generation flow in this folder solves that mismatch by:
- Keeping authoring modular and maintainable for engineers.
- Producing one deterministic OpenAPI YAML for docs tooling.
- Enforcing consistent JSON-RPC request/response shape and examples.

## What each file represents

- `template.json`
  - Base metadata source (title, version, description, license).
  - Seed information used to build the OpenAPI `info` section.

- `methods/*.json`
  - One file per JSON-RPC method (name, summary/description, params, result, examples).
  - Becomes one OpenAPI path per method, e.g. `POST /eth_blockNumber`.

- `components/schemas/*.json`
  - Reusable schema models referenced by methods and content descriptors.
  - Merged into `components.schemas` in the final OpenAPI file.

- `components/contentDescriptors/*.json`
  - OpenRPC-style descriptor wrappers for parameter/result payloads.
  - Used by the generator to resolve and normalize method request/result definitions.

- `build_openapi.py`
  - Source-of-truth generator script.
  - Reads all JSON fragments and writes the final unified OpenAPI YAML.
  - Adds standard JSON-RPC wrapping, examples, and `x-code-samples`.

- `rootstock-openapi.yaml`
  - Generated artifact.
  - Input consumed by the Docusaurus OpenAPI plugin.
  - Do not hand-edit unless debugging; regenerate from source files instead.

## How to generate the spec

From the repository root:

```bash
python3 doc/rpc/build_openapi.py
```

Expected output:

```text
Wrote /.../doc/rpc/rootstock-openapi.yaml
```

## Recommended team workflow (easy maintainability)

1. Edit only source files:
   - `doc/rpc/template.json`
   - `doc/rpc/methods/*.json`
   - `doc/rpc/components/schemas/*.json`
   - `doc/rpc/components/contentDescriptors/*.json`
2. Regenerate:
   - `python3 doc/rpc/build_openapi.py`
3. Review generated changes in:
   - `doc/rpc/rootstock-openapi.yaml`
4. Verify docs rendering in Docusaurus.
5. Commit both:
   - Source fragment updates
   - Regenerated `rootstock-openapi.yaml`

## What the generator guarantees

For every method file, `build_openapi.py` generates:
- A unique endpoint path (`POST /<method_name>`) for clean sidebar pages.
- JSON-RPC 2.0 request body shape:
  - `jsonrpc`, `method`, `params`, `id`
- Normalized schema references:
  - Resolves references via `schemas` and `contentDescriptors`.
- Realistic request/response examples:
  - Uses method examples when provided.
  - Falls back to schema-derived examples when missing.
- Per-method `x-code-samples`:
  - cURL
  - JavaScript (`fetch`)
  - Python (`requests`)
- Standardized response/parameter wording for consistency.

## Network endpoints in generated spec

The generated OpenAPI includes both servers:
- `https://rpc.testnet.rootstock.io/{apiKey}`
- `https://rpc.mainnet.rootstock.io/{apiKey}`

Static code samples default to testnet:
- `https://rpc.testnet.rootstock.io/YOUR_API_KEY`

## Swagger Editor vs Docusaurus

If you paste the spec into [Swagger Editor](https://editor.swagger.io/), **`x-code-samples` and `x-jsonrpc-params` are vendor extensions**. Standard Swagger UI shows them under **Extensions** as unstructured data; it does **not** render Redoc-style code tabs. That is expected.

The Docusaurus OpenAPI plugin (and Redoc) can interpret `x-code-samples` and present samples in a much friendlier way. Use Swagger Editor mainly to validate structure and refs, not as the final docs UX.

## Troubleshooting

- Missing or incorrect method output:
  - Check `doc/rpc/methods/<method>.json` for `name`, `params`, `result`, `examples`.
- Broken refs:
  - Ensure referenced names exist in `components/schemas` or `components/contentDescriptors`.
- Example quality issues:
  - Prefer explicit examples in method JSON; generator fallbacks are heuristic.
- YAML formatting concerns:
  - Regenerate with `python3 doc/rpc/build_openapi.py` (do not manually reformat generated YAML with generic dumpers).
- `x-code-samples` looks like a blob in Swagger UI:
  - Expected for vendor extensions; see **Swagger Editor vs Docusaurus** above. Regenerating also emits multiline `source: |` blocks for readability in YAML and slightly clearer extension previews.

## Ownership note

Treat `build_openapi.py` plus JSON fragments as the maintainable source layer, and `rootstock-openapi.yaml` as the reproducible build artifact for docs.
