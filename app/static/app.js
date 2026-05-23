// BBMetrics Web — app.js
// Handles scan form submission, project/repo loading, and status polling.

// ─── Project / Repo loading ────────────────────────────────────────────────

async function loadProjects() {
    const btn = document.getElementById('load-projects-btn');
    const errEl = document.getElementById('projects-error');
    const baseUrl = document.getElementById('bb_base_url').value.trim();
    const username = document.getElementById('bb_username').value.trim();
    const password = document.getElementById('bb_password').value;

    if (!baseUrl || !username || !password) {
        showError(errEl, 'Please fill in Base URL, Username, and Password first.');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Loading...';
    hideError(errEl);

    try {
        const params = new URLSearchParams({ base_url: baseUrl, username, password });
        const resp = await fetch(`/api/projects?${params}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || 'Failed to load projects');
        }
        const projects = await resp.json();

        const select = document.getElementById('project_select');
        select.innerHTML = '<option value="">— select a project —</option>';
        projects.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.key;
            opt.textContent = `${p.key} — ${p.name}`;
            select.appendChild(opt);
        });

        btn.textContent = `${projects.length} projects loaded ✓`;
    } catch (e) {
        showError(errEl, e.message);
        btn.textContent = 'Retry';
    } finally {
        btn.disabled = false;
    }
}

async function onProjectChange(projectKey) {
    const input = document.getElementById('project_key_input');
    input.value = projectKey;

    if (!projectKey) return;

    const baseUrl = document.getElementById('bb_base_url').value.trim();
    const username = document.getElementById('bb_username').value.trim();
    const password = document.getElementById('bb_password').value;

    const container = document.getElementById('repos-checkboxes');
    container.innerHTML = '<p class="text-slate-500 text-sm italic animate-pulse">Loading repos...</p>';

    try {
        const params = new URLSearchParams({ base_url: baseUrl, username, password });
        const resp = await fetch(`/api/repos/${encodeURIComponent(projectKey)}?${params}`);
        if (!resp.ok) throw new Error('Failed to load repos');
        const repos = await resp.json();

        container.innerHTML = '';
        repos.forEach(r => {
            const label = document.createElement('label');
            label.className = 'flex items-center gap-2 py-1 cursor-pointer hover:text-white text-slate-300 text-sm';
            label.innerHTML = `
                <input type="checkbox" value="${r.slug}" onchange="updateReposFromCheckboxes()"
                       class="rounded border-slate-600 bg-slate-900 text-brand-600 focus:ring-brand-500">
                <span>${r.name} <span class="text-slate-500 text-xs">(${r.slug})</span></span>
            `;
            container.appendChild(label);
        });
    } catch (e) {
        container.innerHTML = `<p class="text-red-400 text-sm">${e.message}</p>`;
    }
}

function updateReposFromCheckboxes() {
    const checkboxes = document.querySelectorAll('#repos-checkboxes input[type=checkbox]:checked');
    const slugs = Array.from(checkboxes).map(cb => cb.value);
    document.getElementById('repos_hidden').value = slugs.join(',');
    document.getElementById('repos_manual').value = slugs.join(', ');
}

function updateReposHidden() {
    const manual = document.getElementById('repos_manual').value;
    document.getElementById('repos_hidden').value = manual;
}

function selectAllRepos() {
    document.querySelectorAll('#repos-checkboxes input[type=checkbox]')
        .forEach(cb => { cb.checked = true; });
    updateReposFromCheckboxes();
}

function clearAllRepos() {
    document.querySelectorAll('#repos-checkboxes input[type=checkbox]')
        .forEach(cb => { cb.checked = false; });
    document.getElementById('repos_hidden').value = '';
    document.getElementById('repos_manual').value = '';
}

// ─── Scan form submission ──────────────────────────────────────────────────

let _pollInterval = null;

async function submitScan(event) {
    event.preventDefault();

    const form = document.getElementById('scan-form');
    const btn = document.getElementById('submit-btn');

    // Make sure repos_hidden has something (fall back to manual input)
    const reposHidden = document.getElementById('repos_hidden');
    const reposManual = document.getElementById('repos_manual');
    if (!reposHidden.value && reposManual.value) {
        reposHidden.value = reposManual.value;
    }

    if (!reposHidden.value.trim()) {
        alert('Please select or enter at least one repository.');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Starting...';

    try {
        const formData = new FormData(form);

        // Sync enable_diffstat as form value
        const diffstatCb = document.getElementById('enable_diffstat');
        if (!diffstatCb.checked) {
            formData.delete('enable_diffstat');
            formData.set('enable_diffstat', 'false');
        }

        const resp = await fetch('/scan', {
            method: 'POST',
            body: formData,
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || 'Failed to start scan');
        }

        const { scan_id } = await resp.json();

        // Show progress UI
        document.getElementById('scan-form-container').classList.add('hidden');
        document.getElementById('progress-container').classList.remove('hidden');
        document.getElementById('current-scan-id').textContent = scan_id;
        document.getElementById('progress-stage').textContent = 'Scan iniciado...';

        startPolling(scan_id);
    } catch (e) {
        alert('Error: ' + e.message);
        btn.disabled = false;
        btn.innerHTML = `<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
        </svg> Start Scan`;
    }
}

function startPolling(scanId) {
    if (_pollInterval) clearInterval(_pollInterval);

    let fakeProgress = 5;
    const progressBar = document.getElementById('progress-bar');
    const stageEl = document.getElementById('progress-stage');

    _pollInterval = setInterval(async () => {
        try {
            const resp = await fetch(`/api/scan/${scanId}/status`);
            const data = await resp.json();

            // Advance fake progress bar
            if (fakeProgress < 90) {
                fakeProgress = Math.min(90, fakeProgress + Math.random() * 8);
            }
            progressBar.style.width = fakeProgress + '%';

            if (data.status === 'running') {
                stageEl.textContent = 'Processando PRs...';
            } else if (data.status === 'done') {
                clearInterval(_pollInterval);
                progressBar.style.width = '100%';
                stageEl.textContent = 'Concluído! Redirecionando...';
                setTimeout(() => {
                    window.location.href = `/results/${scanId}`;
                }, 800);
            } else if (data.status === 'error') {
                clearInterval(_pollInterval);
                progressBar.style.width = '100%';
                progressBar.classList.replace('bg-brand-600', 'bg-red-600');
                stageEl.textContent = 'Erro: ' + (data.error || 'Unknown error');
            }
        } catch (e) {
            // Network error, keep polling
        }
    }, 2000);
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function showError(el, msg) {
    if (!el) return;
    el.textContent = msg;
    el.classList.remove('hidden');
}

function hideError(el) {
    if (!el) return;
    el.textContent = '';
    el.classList.add('hidden');
}
