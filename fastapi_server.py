import os
import sqlite3
import json
import inspect
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, create_model, Field

from odata_mcp_lib import ODataMCPBridge

DB_PATH = os.getenv("SERVICE_DB_PATH", "shared.sqlite")
SERVICE_NAME = os.getenv("SERVICE_NAME")

if not SERVICE_NAME:
    raise RuntimeError("SERVICE_NAME environment variable is required")

conn = sqlite3.connect(DB_PATH)
row = conn.execute(
    "SELECT base_url, metadata, description FROM services WHERE name=?",
    (SERVICE_NAME,)
).fetchone()
conn.close()
if not row:
    raise RuntimeError(f"Service '{SERVICE_NAME}' not found in database")

base_url, metadata_xml, description = row

bridge = ODataMCPBridge(
    base_url,
    metadata_xml=metadata_xml,
    hint=description,
    verbose=False,
)

app = FastAPI(title=f"OData MCP API - {SERVICE_NAME}", description=description)


def _eval_type(type_hint: str):
    namespace = {"Optional": Optional, "str": str, "int": int, "float": float, "bool": bool}
    try:
        return eval(type_hint, namespace, namespace)
    except Exception:
        return Optional[str]


for tool_name, func in bridge.all_registered_tools.items():
    params = bridge.tool_param_defs.get(tool_name, [])
    fields: Dict[str, tuple] = {}
    for p in params:
        t = _eval_type(p["type_hint"])
        default = ... if p["required"] else None
        fields[p["name"]] = (t, Field(default=default, description=p.get("description")))
    ParamModel = create_model(f"{tool_name.capitalize()}Params", **fields)

    async def endpoint(payload: ParamModel, _f=func):
        try:
            result = await _f(**payload.dict(exclude_none=True))
            try:
                return json.loads(result)
            except Exception:
                return {"result": result}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    app.post(f"/{tool_name}", name=tool_name)(endpoint)

