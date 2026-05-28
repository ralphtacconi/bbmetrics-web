from __future__ import annotations

import csv
import io
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import cosmos as cosmos_db
from app.ai_insights import generate_insights

app = FastAPI(title="BBMetrics Web", version="1.0.0")

BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# In-memory fallback store for when Cosmos DB is not configured
_in_memory_scans: Dict[str, Dict[str, Any]] = {}


def _store_scan(doc: Dict[str, Any]) -> None:
    _in_memory_scans[doc["scan_id"]] = doc
    cosmos_db.upsert_scan(doc)


def _load_scan(scan_id: str) -> Optional[Dict[str, Any]]:
    doc = cosmos_db.get_scan(scan_id)
    if doc:
        return doc
    return _in_memory_scans.get(scan_id)


def _load_recent_scans(limit: int = 20) -> List[Dict[str, Any]]:
    cosmos_list = cosmos_db.list_scans(limit)
    if cosmos_list:
        return cosmos_list
    items = sorted(_in_memory_scans.values(), key=lambda x: x.get("created_at", ""), reverse=True)
    return items[:limit]


def _read_csv_to_dicts(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(dict(row))
    return rows


def _run_scan_background(
        scan_id: str,
        project_key: str,
        repos: List[str],
        pr_start: str,
        pr_end: str,
        bitbucket_base_url: str,
        bitbucket_username: str,
        bitbucket_password: str,
        user_filter: Optional[str],
        pr_states: str,
        output_mode: str,
        enable_diffstat: bool,
        date_field: str,
) -> None:
    doc = _load_scan(scan_id) or {}
    doc["status"] = "running"
    _store_scan(doc)

    try:
        orig_env = {
            "BITBUCKET_BASE_URL": os.environ.get("BITBUCKET_BASE_URL"),
            "BITBUCKET_USERNAME": os.environ.get("BITBUCKET_USERNAME"),
            "BITBUCKET_PASSWORD": os.environ.get("BITBUCKET_PASSWORD"),
        }

        os.environ["BITBUCKET_BASE_URL"] = bitbucket_base_url
        os.environ["BITBUCKET_USERNAME"] = bitbucket_username
        os.environ["BITBUCKET_PASSWORD"] = bitbucket_password

        with tempfile.TemporaryDirectory() as out_dir:
            from bbmetrics_dc.cli import scan as run_scan

            run_scan(
                project_key=project_key,
                out=out_dir,
                user=user_filter or None,
                repos=repos,
                pr_start=pr_start,
                pr_end=pr_end,
                enable_diffstat=enable_diffstat,
                output_mode=output_mode,
                pr_states=pr_states,
                date_field=date_field,
            )

            results: Dict[str, Any] = {
                "prs": _read_csv_to_dicts(os.path.join(out_dir, "prs.csv")),
                "pr_review_metrics": _read_csv_to_dicts(os.path.join(out_dir, "pr_review_metrics.csv")),
                "review_events": _read_csv_to_dicts(os.path.join(out_dir, "pr_review_events.csv")),
                "users_summary": _read_csv_to_dicts(os.path.join(out_dir, "users_summary.csv")),
                "groups_summary": _read_csv_to_dicts(os.path.join(out_dir, "groups_summary.csv")),
            }

        ai_insights = generate_insights(results)
        doc["status"] = "done"
        doc["results"] = results
        # PATCH: ai_insights NUNCA None
        doc["ai_insights"] = ai_insights or {
            "summary": "Nenhum insight de IA foi gerado para este scan.",
            "risk_alerts": [],
            "recommendations": []
        }
        doc["error"] = None
        _store_scan(doc)

    except Exception as exc:
        doc = _load_scan(scan_id) or {}
        doc["status"] = "error"
        doc["error"] = str(exc)
        _store_scan(doc)

    finally:
        for k, v in orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

# ---------------------------------------------------------------------------
# Defining Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "cosmos": cosmos_db.cosmos_available()})


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    scans = _load_recent_scans()
    return templates.TemplateResponse(request, "index.html", {"scans": scans})


@app.get("/scan", response_class=HTMLResponse)
async def scan_form(request: Request) -> HTMLResponse:
    base_url = os.getenv("BITBUCKET_BASE_URL", "")
    return templates.TemplateResponse(request, "scan.html", {"default_base_url": base_url})


@app.post("/scan")
async def start_scan(
    background_tasks: BackgroundTasks,
    request: Request,
    bitbucket_base_url: str = Form(...),
    bitbucket_username: str = Form(...),
    bitbucket_password: str = Form(...),
    project_key: str = Form(...),
    repos: str = Form(...),
    pr_start: str = Form(...),
    pr_end: str = Form(...),
    user_filter: str = Form(""),
    pr_states: str = Form("OPEN,MERGED,DECLINED"),
    output_mode: str = Form("completo"),
    enable_diffstat: bool = Form(False),
    date_field: str = Form("created"),
) -> JSONResponse:
    scan_id = str(uuid.uuid4())
    repos_list = [r.strip() for r in repos.split(",") if r.strip()]

    if not repos_list:
        raise HTTPException(status_code=400, detail="At least one repository is required.")

    doc: Dict[str, Any] = {
        "scan_id": scan_id,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "project_key": project_key,
            "repos": repos_list,
            "pr_start": pr_start,
            "pr_end": pr_end,
            "bitbucket_base_url": bitbucket_base_url,
            "user_filter": user_filter,
            "pr_states": pr_states,
            "output_mode": output_mode,
            "enable_diffstat": enable_diffstat,
            "date_field": date_field,
        },
        "results": None,
        "ai_insights": None,
        "error": None,
    }
    _store_scan(doc)

    background_tasks.add_task(
        _run_scan_background,
        scan_id=scan_id,
        project_key=project_key,
        repos=repos_list,
        pr_start=pr_start,
        pr_end=pr_end,
        bitbucket_base_url=bitbucket_base_url,
        bitbucket_username=bitbucket_username,
        bitbucket_password=bitbucket_password,
        user_filter=user_filter or None,
        pr_states=pr_states,
        output_mode=output_mode,
        enable_diffstat=enable_diffstat,
        date_field=date_field,
    )

    return JSONResponse({"scan_id": scan_id})


@app.get("/results/{scan_id}", response_class=HTMLResponse)
async def scan_results(request: Request, scan_id: str) -> HTMLResponse:
    doc = _load_scan(scan_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Scan not found.")
    import pprint
    pprint.pprint(doc)
    return templates.TemplateResponse(request, "results.html", {"scan": doc})


@app.get("/api/scan/{scan_id}/status")
async def scan_status(scan_id: str) -> JSONResponse:
    doc = _load_scan(scan_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Scan not found.")
    return JSONResponse(
        {
            "scan_id": scan_id,
            "status": doc.get("status", "unknown"),
            "error": doc.get("error"),
        }
    )


@app.get("/api/projects")
async def list_projects_api(
    base_url: str,
    username: str,
    password: str,
) -> JSONResponse:
    try:
        from bbmetrics_dc.client import BitbucketDCClient
        from BBMetrics_UI.bb_api import list_projects

        client = BitbucketDCClient(base_url=base_url, username=username, password=password)
        projects = list_projects(client)
        return JSONResponse([{"key": p.key, "name": p.name} for p in projects])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/repos/{project_key}")
async def list_repos_api(
    project_key: str,
    base_url: str,
    username: str,
    password: str,
) -> JSONResponse:
    try:
        from bbmetrics_dc.client import BitbucketDCClient
        from BBMetrics_UI.bb_api import list_repos_in_project

        client = BitbucketDCClient(base_url=base_url, username=username, password=password)
        repos = list_repos_in_project(client, project_key)
        return JSONResponse([{"slug": r.slug, "name": r.name} for r in repos])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
