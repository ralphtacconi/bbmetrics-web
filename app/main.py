from __future__ import annotations

import csv
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from BBMetrics_UI.bb_api import list_projects, list_repos_in_project
from app.ai_insights import generate_ai_insights
from app.cosmos import CosmosStore
from bbmetrics_dc.client import BitbucketDCClient

app = FastAPI(title='BBMetrics Web')
store = CosmosStore()

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'
SCAN_TMP_DIR = Path('/tmp/bbmetrics_scans')
SCAN_TMP_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


def _scan_params_without_secret(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'base_url': payload.get('base_url'),
        'project_key': payload.get('project_key'),
        'repos': payload.get('repos', []),
        'pr_start': payload.get('pr_start'),
        'pr_end': payload.get('pr_end'),
        'output_mode': payload.get('output_mode'),
        'pr_states': payload.get('pr_states'),
        'date_field': payload.get('date_field'),
        'include_comment_text': bool(payload.get('include_comment_text')),
        'enable_diffstat': bool(payload.get('enable_diffstat')),
        'username': payload.get('username'),
    }


def _read_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _metrics_from_results(results: Dict[str, Any]) -> Dict[str, Any]:
    prs = results.get('prs', [])
    open_prs = sum(1 for p in prs if (p.get('state') or '').upper() == 'OPEN')
    merged_prs = sum(1 for p in prs if (p.get('state') or '').upper() == 'MERGED')
    declined_prs = sum(1 for p in prs if (p.get('state') or '').upper() == 'DECLINED')
    comments_total = 0
    for p in prs:
        try:
            comments_total += int(p.get('comments_total', 0) or 0)
        except Exception:
            pass
    return {
        'total_prs': len(prs),
        'open_prs': open_prs,
        'merged_prs': merged_prs,
        'declined_prs': declined_prs,
        'total_comments': comments_total,
    }


def _run_scan_background(scan_id: str, payload: Dict[str, Any]) -> None:
    doc = store.get_scan(scan_id)
    if not doc:
        return

    doc['status'] = 'running'
    store.upsert_scan(doc)

    out_dir = SCAN_TMP_DIR / scan_id
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        '-m',
        'bbmetrics_dc.cli',
        '--project-key',
        payload['project_key'],
        '--out',
        str(out_dir),
        '--pr-start',
        payload['pr_start'],
        '--pr-end',
        payload['pr_end'],
        '--output-mode',
        payload.get('output_mode', 'completo'),
        '--pr-states',
        payload.get('pr_states', 'OPEN,MERGED,DECLINED'),
        '--date-field',
        payload.get('date_field', 'created'),
    ]

    for repo in payload.get('repos', []):
        cmd.extend(['--repos', repo])
    if payload.get('include_comment_text'):
        cmd.append('--include-comment-text')
    if payload.get('enable_diffstat'):
        cmd.append('--enable-diffstat')

    env = os.environ.copy()
    env['BITBUCKET_BASE_URL'] = payload['base_url']
    env['BITBUCKET_USERNAME'] = payload['username']
    env['BITBUCKET_PASSWORD'] = payload['password']

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        results = {
            'prs': _read_csv(out_dir / 'prs.csv'),
            'review_events': _read_csv(out_dir / 'pr_review_events.csv'),
            'review_metrics': _read_csv(out_dir / 'pr_review_metrics.csv'),
            'commits': _read_csv(out_dir / 'commits.csv'),
            'users_summary': _read_csv(out_dir / 'users_summary.csv'),
            'groups_summary': _read_csv(out_dir / 'groups_summary.csv'),
            'stdout': proc.stdout,
        }
        metrics = _metrics_from_results(results)
        ai = generate_ai_insights(metrics)
        doc.update({'status': 'done', 'results': results, 'ai_insights': ai, 'error': None})
        store.upsert_scan(doc)
    except subprocess.CalledProcessError as exc:
        doc.update(
            {
                'status': 'error',
                'error': (exc.stderr or exc.stdout or str(exc))[:8000],
                'results': {},
                'ai_insights': None,
            }
        )
        store.upsert_scan(doc)
    except Exception as exc:
        doc.update({'status': 'error', 'error': repr(exc), 'results': {}, 'ai_insights': None})
        store.upsert_scan(doc)


def _get_credentials(
    base_url: Optional[str],
    username: Optional[str],
    password: Optional[str],
) -> tuple[str, str, str]:
    final_base_url = (base_url or os.getenv('BITBUCKET_BASE_URL', '')).strip()
    final_username = (username or os.getenv('BITBUCKET_USERNAME', '')).strip()
    final_password = (password or os.getenv('BITBUCKET_PASSWORD', '')).strip()

    if not final_base_url or not final_username or not final_password:
        raise HTTPException(status_code=400, detail='Missing Bitbucket credentials or base URL')
    return final_base_url, final_username, final_password


@app.get('/health')
def health() -> Dict[str, str]:
    return {'status': 'ok'}


@app.get('/')
def dashboard(request: Request):
    scans = store.list_recent_scans(limit=30)
    return templates.TemplateResponse('dashboard.html', {'request': request, 'scans': scans})


@app.get('/scan')
def scan_form(request: Request):
    defaults = {
        'base_url': os.getenv('BITBUCKET_BASE_URL', ''),
        'username': os.getenv('BITBUCKET_USERNAME', ''),
    }
    return templates.TemplateResponse('scan.html', {'request': request, 'defaults': defaults})


@app.post('/scan')
def start_scan(
    background_tasks: BackgroundTasks,
    base_url: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    project_key: str = Form(...),
    repos: str = Form(...),
    pr_start: str = Form(...),
    pr_end: str = Form(...),
    output_mode: str = Form('completo'),
    pr_states: str = Form('OPEN,MERGED,DECLINED'),
    date_field: str = Form('created'),
    include_comment_text: bool = Form(False),
    enable_diffstat: bool = Form(False),
):
    scan_id = str(uuid.uuid4())
    repo_list = [r.strip() for r in repos.split(',') if r.strip()]

    payload = {
        'base_url': base_url.strip(),
        'username': username.strip(),
        'password': password,
        'project_key': project_key.strip(),
        'repos': repo_list,
        'pr_start': pr_start.strip(),
        'pr_end': pr_end.strip(),
        'output_mode': output_mode.strip(),
        'pr_states': pr_states.strip(),
        'date_field': date_field.strip(),
        'include_comment_text': include_comment_text,
        'enable_diffstat': enable_diffstat,
    }

    doc = {
        'id': scan_id,
        'scan_id': scan_id,
        'status': 'queued',
        'created_at': store.now_iso(),
        'params': _scan_params_without_secret(payload),
        'results': {},
        'ai_insights': None,
        'error': None,
    }
    store.upsert_scan(doc)
    background_tasks.add_task(_run_scan_background, scan_id, payload)

    return RedirectResponse(url=f'/results/{scan_id}', status_code=303)


@app.get('/results/{scan_id}')
def results_page(request: Request, scan_id: str):
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail='Scan not found')
    return templates.TemplateResponse('results.html', {'request': request, 'scan': scan})


@app.get('/api/scan/{scan_id}/status')
def scan_status(scan_id: str):
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(status_code=404, detail='Scan not found')
    return {
        'scan_id': scan['scan_id'],
        'status': scan['status'],
        'error': scan.get('error'),
        'created_at': scan.get('created_at'),
        'ai_insights': scan.get('ai_insights'),
        'results': scan.get('results', {}),
    }


@app.get('/api/projects')
def api_projects(
    base_url: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
    password: Optional[str] = Query(default=None),
):
    b, u, p = _get_credentials(base_url, username, password)
    client = BitbucketDCClient(base_url=b, username=u, password=p)
    return [{'key': x.key, 'name': x.name} for x in list_projects(client)]


@app.get('/api/repos/{project_key}')
def api_repos(
    project_key: str,
    base_url: Optional[str] = Query(default=None),
    username: Optional[str] = Query(default=None),
    password: Optional[str] = Query(default=None),
):
    b, u, p = _get_credentials(base_url, username, password)
    client = BitbucketDCClient(base_url=b, username=u, password=p)
    return [{'slug': x.slug, 'name': x.name} for x in list_repos_in_project(client, project_key)]
