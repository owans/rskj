#!/usr/bin/env python3
"""Generate doc/rpc/rootstock-openapi.yaml from OpenRPC-like JSON fragments."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METHODS_DIR = ROOT / "methods"
SCHEMAS_DIR = ROOT / "components" / "schemas"
CD_DIR = ROOT / "components" / "contentDescriptors"
OUT = ROOT / "rootstock-openapi.yaml"
TEMPLATE = ROOT / "template.json"

CODE_SAMPLE_BASE = "https://rpc.testnet.rootstock.io/YOUR_API_KEY"

STD_PARAMS_DESC = "Ordered JSON array of positional parameters for this method."
STD_RESPONSE_DESC = (
    "Successful JSON-RPC 2.0 response over HTTP. "
    "The return value is in `result`. "
    "On failure, nodes typically still respond with HTTP 200 and an `error` object instead of `result`."
)
RPC_NOTE = (
    "\n\nSend a **JSON-RPC 2.0** request (`jsonrpc`, `method`, `params`, `id`) as in the example below."
)


def load_json(p: Path) -> dict:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    template = load_json(TEMPLATE)

    schemas: dict = {}
    for p in sorted(SCHEMAS_DIR.glob("*.json")):
        data = load_json(p)
        for k, v in data.items():
            schemas[k] = v

    content_descriptors: dict = {}
    for p in sorted(CD_DIR.glob("*.json")):
        data = load_json(p)
        for k, v in data.items():
            content_descriptors[k] = v

    ref_schema_re = re.compile(r"^#/components/schemas/([^/]+)$")
    ref_cd_re = re.compile(r"^#/components/contentDescriptors/([^/]+)$")

    def deref_ref_obj(obj):
        if isinstance(obj, dict) and "$ref" in obj:
            ref = obj["$ref"]
            m = ref_schema_re.match(ref)
            if m:
                return schemas.get(m.group(1), {"type": "object"})
            m = ref_cd_re.match(ref)
            if m:
                cd = content_descriptors.get(m.group(1), {})
                if isinstance(cd, dict):
                    return cd.get("schema", {"type": "object"})
        return obj

    def example_from_schema(schema, depth=0):
        if depth > 4:
            return None
        if schema is None:
            return None
        if isinstance(schema, dict) and "$ref" in schema:
            target = deref_ref_obj(schema)
            return example_from_schema(target, depth + 1)
        if not isinstance(schema, dict):
            return None
        if "example" in schema:
            return schema["example"]
        if "value" in schema and "type" not in schema and "properties" not in schema:
            return schema["value"]
        if "enum" in schema and schema["enum"]:
            return schema["enum"][0]
        if "oneOf" in schema and schema["oneOf"]:
            return example_from_schema(schema["oneOf"][0], depth + 1)
        if "anyOf" in schema and schema["anyOf"]:
            return example_from_schema(schema["anyOf"][0], depth + 1)
        t = schema.get("type")
        if t == "string" or (t is None and ("pattern" in schema or "format" in schema)):
            title = str(schema.get("title", "")).lower()
            desc = str(schema.get("description", "")).lower()
            txt = f"{title} {desc}"
            if "address" in txt:
                return "0x0000000000000000000000000000000000000000"
            if "hash" in txt or "keccak" in txt:
                return "0x" + "0" * 64
            if "blocknumbertag" in title or "tag" in txt:
                return "latest"
            if "hex" in title or "integer" in txt or "nonce" in txt:
                return "0x1"
            return "0x"
        if t in ("integer", "number"):
            return 1
        if t == "boolean":
            return True
        if t == "array":
            item = schema.get("items", {"type": "string"})
            return [example_from_schema(item, depth + 1)]
        if t == "object" or "properties" in schema:
            out = {}
            props = schema.get("properties", {})
            required = schema.get("required", [])
            keys = list(props.keys())
            for k in keys:
                if required and k not in required and len(out) >= 5:
                    continue
                out[k] = example_from_schema(props[k], depth + 1)
            return out
        return None

    def normalize_schema(obj):
        if isinstance(obj, dict):
            new = {}
            for k, v in obj.items():
                if k == "$ref" and isinstance(v, str):
                    m = ref_cd_re.match(v)
                    if m:
                        cd = content_descriptors.get(m.group(1), {})
                        sch = cd.get("schema", {"type": "object"})
                        return normalize_schema(sch)
                new[k] = normalize_schema(v)
            return new
        if isinstance(obj, list):
            return [normalize_schema(x) for x in obj]
        return obj

    def yaml_quote(s):
        return json.dumps(s, ensure_ascii=True)

    # YAML 1.1 (used by Swagger Editor and others) treats bare keys like Null/true/false
    # as language null/boolean, which breaks OpenAPI component names such as schema "Null".
    YAML_AMBIGUOUS_MAP_KEYS = frozenset(
        (
            "null",
            "Null",
            "NULL",
            "~",
            "true",
            "True",
            "false",
            "False",
            "yes",
            "Yes",
            "no",
            "No",
            "on",
            "On",
            "off",
            "Off",
        )
    )

    def yaml_map_key(k: object) -> str:
        ks = str(k)
        if ks in YAML_AMBIGUOUS_MAP_KEYS:
            return yaml_quote(ks)
        # Quote numeric keys (e.g. HTTP 200) so YAML 1.1 keeps them as strings for OpenAPI validators.
        if ks.isdigit():
            return yaml_quote(ks)
        return ks

    def to_yaml(obj, indent=0):
        sp = "  " * indent
        if obj is None:
            return "null"
        if isinstance(obj, bool):
            return "true" if obj else "false"
        if isinstance(obj, (int, float)) and not isinstance(obj, bool):
            return str(obj)
        if isinstance(obj, str):
            return yaml_quote(obj)
        if isinstance(obj, list):
            if not obj:
                return "[]"
            lines = []
            for item in obj:
                if isinstance(item, (dict, list)):
                    lines.append(sp + "- " + to_yaml(item, indent + 1).lstrip())
                else:
                    lines.append(sp + "- " + to_yaml(item, indent + 1))
            return "\n".join(lines)
        if isinstance(obj, dict):
            if not obj:
                return "{}"
            lines = []
            for k, v in obj.items():
                key = yaml_map_key(k)
                if str(k) == "source" and isinstance(v, str) and "\n" in v:
                    lines.append(f"{sp}{key}: |")
                    body = sp + "  "
                    for line in v.split("\n"):
                        lines.append(f"{body}{line}")
                    continue
                if isinstance(v, (dict, list)):
                    if (isinstance(v, list) and not v) or (isinstance(v, dict) and not v):
                        lines.append(f"{sp}{key}: {to_yaml(v, indent + 1)}")
                    else:
                        nested = to_yaml(v, indent + 1)
                        lines.append(f"{sp}{key}:\n{nested}")
                else:
                    lines.append(f"{sp}{key}: {to_yaml(v, indent + 1)}")
            return "\n".join(lines)
        return yaml_quote(str(obj))

    base_desc = (template.get("info") or {}).get("description", "").strip()
    info_suffix = "Use the **Servers** section to pick Testnet or Mainnet and set your API key."
    if base_desc and info_suffix not in base_desc:
        if base_desc.endswith((".", "!", "?")):
            info_description = f"{base_desc} {info_suffix}"
        else:
            info_description = f"{base_desc}. {info_suffix}"
    else:
        info_description = base_desc or info_suffix

    openapi = {
        "openapi": "3.0.3",
        "info": {
            "title": template.get("info", {}).get("title", "RSKj JSON-RPC API"),
            "version": template.get("info", {}).get("version", "1.0.0"),
            "description": info_description,
        },
        "servers": [
            {
                "url": "https://rpc.testnet.rootstock.io/{apiKey}",
                "description": "Rootstock Testnet JSON-RPC (replace apiKey with your API key)",
                "variables": {
                    "apiKey": {
                        "default": "YOUR_API_KEY",
                        "description": "API key segment from the Rootstock RPC dashboard",
                    }
                },
            },
            {
                "url": "https://rpc.mainnet.rootstock.io/{apiKey}",
                "description": "Rootstock Mainnet JSON-RPC (replace apiKey with your API key)",
                "variables": {
                    "apiKey": {
                        "default": "YOUR_API_KEY",
                        "description": "API key segment from the Rootstock RPC dashboard",
                    }
                },
            },
        ],
        "paths": {},
        "components": {"schemas": {}},
    }
    if template.get("info", {}).get("license"):
        openapi["info"]["license"] = template["info"]["license"]

    for name, schema in schemas.items():
        openapi["components"]["schemas"][name] = normalize_schema(schema)

    for mp in sorted(METHODS_DIR.glob("*.json")):
        m = load_json(mp)
        method_name = m.get("name", mp.stem)
        summary = (m.get("summary") or method_name).strip()
        desc_raw = (m.get("description") or "").strip()

        if desc_raw and desc_raw != summary:
            if "jsonrpc" in desc_raw.lower() or "JSON-RPC" in desc_raw:
                operation_description = desc_raw
            else:
                operation_description = desc_raw + RPC_NOTE
        else:
            operation_description = f"**`{method_name}`** - {summary}" + RPC_NOTE

        params_desc = []
        params_schema_variants = []
        for p in m.get("params", []):
            desc = None
            if "$ref" in p:
                ref = p["$ref"]
                mc = ref_cd_re.match(ref)
                if mc:
                    desc = content_descriptors.get(mc.group(1), {}).copy()
            else:
                desc = p.copy()
            if desc is None:
                desc = {"name": "param", "required": True, "schema": {"type": "string"}}
            if "schema" not in desc:
                if "$ref" in desc:
                    desc["schema"] = {"$ref": desc["$ref"]}
                else:
                    desc["schema"] = {"type": "string"}
            params_desc.append(desc)
            params_schema_variants.append(normalize_schema(desc.get("schema", {"type": "string"})))

        params_items = {"oneOf": params_schema_variants} if params_schema_variants else {}

        req_schema = {
            "type": "object",
            "required": ["jsonrpc", "method", "params", "id"],
            "properties": {
                "jsonrpc": {"type": "string", "enum": ["2.0"]},
                "method": {"type": "string", "enum": [method_name]},
                "params": {
                    "type": "array",
                    "description": STD_PARAMS_DESC,
                    "minItems": len(params_desc),
                    "maxItems": len(params_desc),
                },
                "id": {"oneOf": [{"type": "integer"}, {"type": "string"}], "example": 1},
            },
        }
        if params_items:
            req_schema["properties"]["params"]["items"] = params_items
        else:
            # OpenAPI / JSON Schema validators require `items` when type is array (even if maxItems is 0).
            req_schema["properties"]["params"]["items"] = {}

        ex = (m.get("examples") or [{}])[0]
        req_params = []
        for i, pd in enumerate(params_desc):
            val = None
            ex_params = ex.get("params", []) if isinstance(ex, dict) else []
            if i < len(ex_params):
                item = ex_params[i]
                if isinstance(item, dict):
                    if "value" in item:
                        val = item["value"]
                    elif "$ref" in item:
                        refobj = deref_ref_obj(item)
                        if isinstance(refobj, dict) and "value" in refobj:
                            val = refobj["value"]
                        else:
                            val = example_from_schema(refobj)
            if val is None:
                val = example_from_schema(pd.get("schema", {"type": "string"}))
            req_params.append(val)

        result_schema = {"type": "object"}
        result = m.get("result", {})
        if isinstance(result, dict):
            if "$ref" in result:
                mc = ref_cd_re.match(result["$ref"])
                if mc:
                    result_schema = normalize_schema(
                        content_descriptors.get(mc.group(1), {}).get("schema", {"type": "object"})
                    )
                else:
                    result_schema = normalize_schema(result)
            elif "schema" in result:
                result_schema = normalize_schema(result["schema"])

        result_val = None
        if isinstance(ex, dict):
            ex_res = ex.get("result")
            if isinstance(ex_res, dict):
                if "value" in ex_res:
                    result_val = ex_res["value"]
                elif "$ref" in ex_res:
                    refobj = deref_ref_obj(ex_res)
                    if isinstance(refobj, dict) and "value" in refobj:
                        result_val = refobj["value"]
                    else:
                        result_val = example_from_schema(refobj)
        if result_val is None:
            result_val = example_from_schema(result_schema)

        req_example = {"jsonrpc": "2.0", "method": method_name, "params": req_params, "id": 1}
        res_example = {"jsonrpc": "2.0", "id": 1, "result": result_val}

        req_json = json.dumps(req_example, ensure_ascii=True)

        body_json = json.dumps(req_example, ensure_ascii=True)
        x_samples = [
            {
                "lang": "cURL",
                "label": "cURL",
                "source": (
                    f"curl -X POST {CODE_SAMPLE_BASE} \\\n"
                    f"  -H 'Content-Type: application/json' \\\n"
                    f"  -d '{req_json}'"
                ),
            },
            {
                "lang": "JavaScript",
                "label": "JavaScript (fetch)",
                "source": (
                    f"const response = await fetch('{CODE_SAMPLE_BASE}', {{\n"
                    f"  method: 'POST',\n"
                    f"  headers: {{ 'Content-Type': 'application/json' }},\n"
                    f"  body: JSON.stringify({body_json})\n"
                    f"}});\n"
                    f"const data = await response.json();\n"
                    f"console.log(data);"
                ),
            },
            {
                "lang": "Python",
                "label": "Python (requests)",
                "source": (
                    "import requests\n\n"
                    f"payload = {body_json}\n"
                    f"response = requests.post('{CODE_SAMPLE_BASE}', json=payload, timeout=30)\n"
                    "print(response.json())"
                ),
            },
        ]

        tag = method_name.split("_", 1)[0] if "_" in method_name else "rpc"
        path = f"/{method_name}"

        operation = {
            "tags": [tag],
            "operationId": method_name,
            "summary": summary,
            "description": operation_description,
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": req_schema,
                        "example": req_example,
                    }
                },
            },
            "responses": {
                # String keys: some OpenAPI validators reject numeric YAML keys for HTTP status codes.
                "200": {
                    "description": STD_RESPONSE_DESC,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["jsonrpc", "id", "result"],
                                "properties": {
                                    "jsonrpc": {"type": "string", "enum": ["2.0"]},
                                    "id": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
                                    "result": result_schema,
                                },
                            },
                            "example": res_example,
                        }
                    },
                }
            },
            "x-code-samples": x_samples,
            "x-jsonrpc-params": [
                {
                    "name": pd.get("name", f"param{i + 1}"),
                    "description": pd.get("description", ""),
                    "required": bool(pd.get("required", False)),
                    "schema": normalize_schema(pd.get("schema", {"type": "string"})),
                }
                for i, pd in enumerate(params_desc)
            ],
        }

        openapi["paths"][path] = {"post": operation}

    OUT.write_text(to_yaml(openapi) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
