import os
import json
import time
import traceback
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from google_client import GoogleTasksClient
from sync_engine import SyncEngine

app = FastAPI(title="Google Tasks Multi-Sync", version="1.0.2")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

client = GoogleTasksClient()
sync_engine = SyncEngine(client)

# Read options from Home Assistant Addon options.json if available
options_file = "/data/options.json"
sync_interval = 15
auto_sync = True
if os.path.exists(options_file):
    try:
        with open(options_file, "r", encoding="utf-8") as f:
            opts = json.load(f)
            sync_interval = opts.get("sync_interval_minutes", 15)
            auto_sync = opts.get("auto_sync_enabled", True)
    except Exception:
        pass

if auto_sync:
    sync_engine.sync_interval = sync_interval * 60
    sync_engine.start_periodic_sync()

# Global error catching middleware
@app.middleware("http")
async def catch_exceptions_middleware(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        err_msg = traceback.format_exc()
        print("EXCEPTION CAUGHT:\n", err_msg)
        return HTMLResponse(content=f"<pre style='color:#f85149;background:#0d1117;padding:20px;font-family:monospace;'>500 Internal Error:\n{err_msg}</pre>", status_code=500)

# --- Web UI Routes ---

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def index(request: Request):
    root_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    index_file = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace("{{ root_path }}", root_path)
        html = html.replace("{{ sync_interval }}", str(sync_interval))
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Google Tasks Multi-Sync</h1><p>index.html not found.</p>")

# --- API Endpoints ---

@app.get("/api/status")
async def get_status():
    accounts = client.get_accounts()
    return {
        "total_accounts": len(accounts),
        "accounts": [
            {
                "id": k,
                "name": v.get("name"),
                "email": v.get("email"),
                "updated_at": v.get("updated_at")
            }
            for k, v in accounts.items()
        ],
        "is_syncing": sync_engine.is_syncing,
        "last_sync_time": sync_engine.last_sync_time,
        "last_sync_status": sync_engine.last_sync_status,
        "logs": sync_engine.logs[:50]
    }

@app.post("/api/sync/now")
async def trigger_sync():
    result = sync_engine.run_sync()
    return result

@app.get("/api/json/export")
async def export_json(account_id: Optional[str] = None):
    data = sync_engine.export_full_json(account_id)
    return JSONResponse(content=data)

class ImportPayload(BaseModel):
    json_data: Dict[str, Any]
    target_accounts: Optional[List[str]] = None

@app.post("/api/json/import")
async def import_json(payload: ImportPayload):
    try:
        res = sync_engine.import_full_json(payload.json_data, payload.target_accounts)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/json/validate")
async def validate_json(payload: Dict[str, Any] = Body(...)):
    lists = payload.get("lijsten") or payload.get("tasks") or []
    return {
        "valid": True,
        "lists_count": len(lists) if isinstance(lists, list) else 0,
        "message": f"Geldige JSON structuur gevonden met {len(lists)} elementen."
    }

# --- Captain & Task Manager API ---

@app.get("/api/tasks/all")
async def get_all_tasks():
    try:
        tasks = sync_engine.get_all_tasks()
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/divider/tasks")
async def get_divider_tasks():
    try:
        tasks = sync_engine.get_captain_fixed_tasks()
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CreateTaskPayload(BaseModel):
    title: str
    list_title: str
    sublist_name: Optional[str] = None
    notes: Optional[str] = ""
    due: Optional[str] = None

@app.post("/api/tasks/create")
async def create_task(payload: CreateTaskPayload):
    try:
        res = sync_engine.create_single_task(
            title=payload.title,
            list_title=payload.list_title,
            sublist_name=payload.sublist_name,
            notes=payload.notes or "",
            due=payload.due
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

class BatchReassignPayload(BaseModel):
    moves: List[Dict[str, Any]]

@app.post("/api/tasks/reassign")
async def reassign_tasks(payload: BatchReassignPayload):
    try:
        res = sync_engine.reassign_tasks_batch(payload.moves)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ApplyDivisionPayload(BaseModel):
    roy_tasks: List[Dict[str, Any]]
    karen_tasks: List[Dict[str, Any]]

@app.post("/api/divider/apply")
async def apply_divider_tasks(payload: ApplyDivisionPayload):
    try:
        res = sync_engine.apply_captain_division(payload.roy_tasks, payload.karen_tasks)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Account Management ---

@app.get("/api/accounts")
async def list_accounts():
    accounts = client.get_accounts()
    return {
        "accounts": [
            {"id": k, "name": v.get("name"), "email": v.get("email")}
            for k, v in accounts.items()
        ]
    }

class AddAccountPayload(BaseModel):
    name: str
    email: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: str

@app.post("/api/accounts/add")
async def add_account(payload: AddAccountPayload):
    acc_id = payload.email.replace("@", "_at_").replace(".", "_")
    token_data = {
        "type": "authorized_user",
        "client_id": payload.client_id,
        "client_secret": payload.client_secret,
        "refresh_token": payload.refresh_token
    }
    client.save_account(acc_id, payload.email, payload.name, token_data)
    
    token = client.get_access_token(acc_id)
    if not token:
        client.delete_account(acc_id)
        raise HTTPException(status_code=400, detail="Kon niet authenticeren met Google. Controleer de refresh token.")
    
    return {"success": True, "account_id": acc_id}

@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str):
    client.delete_account(account_id)
    return {"success": True}

@app.get("/api/oauth/config")
async def get_oauth_config():
    cfg = client.get_client_config()
    return {
        "has_client_secret": bool(cfg),
        "client_id": cfg.get("client_id") if cfg else None
    }

@app.post("/api/oauth/save_secret")
async def save_oauth_secret(secret_json: Dict[str, Any] = Body(...)):
    client.save_client_config(secret_json)
    return {"success": True}
