from __future__ import annotations

from collections import defaultdict
from statistics import mean, median
from typing import Dict, Iterable, List, Optional, Set


def _safe_int(v) -> int:
    try:
        return int(v or 0)
    except Exception:
        return 0


def _safe_float(v) -> float:
    try:
        if v is None:
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _norm_repo(repo_slug: str) -> str:
    s = (repo_slug or "").strip()
    return s or "UNKNOWN"


def _append_if_number_allow_zero(xs: List[float], v) -> None:
    """
    Opção B:
      - Ignora None / vazio / parse inválido
      - Aceita 0 como valor válido (pode acontecer review/approval instantâneo)
      - Ignora negativos (dados ruins)
    """
    if v is None:
        return
    try:
        fv = float(v)
    except Exception:
        return
    if fv < 0:
        return
    xs.append(fv)


def _fmt_avg_or_blank(values: List[float]) -> object:
    """
    Retorna:
      - "" se não houver dados
      - float arredondado caso haja dados
    """
    if not values:
        return ""
    return round(mean(values), 3)


def _fmt_median_or_blank(values: List[float]) -> object:
    if not values:
        return ""
    return round(median(values), 3)


def _calc_user_row(uid: str, group: str, repo: str, a: Dict, *, diffstat_enabled: bool) -> Dict:
    prs = int(a.get("prs_opened_count") or 0)
    commits = int(a.get("commits_count") or 0)

    avg_pr_time_open = round(mean(a["_pr_time_open_minutes"]), 3) if a["_pr_time_open_minutes"] else 0.0
    med_pr_time_open = round(median(a["_pr_time_open_minutes"]), 3) if a["_pr_time_open_minutes"] else 0.0
    avg_pr_comments_total = round(mean(a["_pr_comments_total"]), 3) if a["_pr_comments_total"] else 0.0
    avg_pr_commits_total = round(mean(a["_pr_commits_total"]), 3) if a["_pr_commits_total"] else 0.0

    avg_commits_per_pr = round((commits / prs), 3) if prs else 0.0

    # diffstat-dependent
    if diffstat_enabled:
        avg_lines_changed_per_commit: object = round((a["lines_changed"] / commits), 3) if commits else 0.0
        lines_added: object = int(a["lines_added"])
        lines_removed: object = int(a["lines_removed"])
        lines_changed: object = int(a["lines_changed"])
        files_changed: object = int(a["files_changed"])
    else:
        avg_lines_changed_per_commit = "NA"
        lines_added = "NA"
        lines_removed = "NA"
        lines_changed = "NA"
        files_changed = "NA"

    # review/approval times (Opção B => blank when no data)
    avg_time_to_first_review = _fmt_avg_or_blank(a["_time_to_first_review_minutes"])
    med_time_to_first_review = _fmt_median_or_blank(a["_time_to_first_review_minutes"])

    avg_time_to_first_approval = _fmt_avg_or_blank(a["_time_to_first_approval_minutes"])
    med_time_to_first_approval = _fmt_median_or_blank(a["_time_to_first_approval_minutes"])

    return {
        "user": uid,
        "group": group,
        "repo": repo,
        # averages first
        "avg_pr_time_open_minutes": avg_pr_time_open,
        "median_pr_time_open_minutes": med_pr_time_open,
        "avg_pr_comments_total": avg_pr_comments_total,
        "avg_pr_commits_total": avg_pr_commits_total,
        "avg_commits_per_pr": avg_commits_per_pr,
        "avg_lines_changed_per_commit": avg_lines_changed_per_commit,
        "avg_time_to_first_review_minutes": avg_time_to_first_review,
        "median_time_to_first_review_minutes": med_time_to_first_review,
        "avg_time_to_first_approval_minutes": avg_time_to_first_approval,
        "median_time_to_first_approval_minutes": med_time_to_first_approval,
        # totals
        "prs_opened_count": prs,
        "commits_count": commits,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "lines_changed": lines_changed,
        "files_changed": files_changed,
        # counts of PRs that had metrics available
        "prs_with_review_time_count": int(a["prs_with_review_time_count"]),
        "prs_with_approval_time_count": int(a["prs_with_approval_time_count"]),
        "diffstat_enabled": "1" if diffstat_enabled else "0",
    }


def summarize_users_by_repo(
    commit_rows: Iterable[Dict],
    pr_rows: Iterable[Dict],
    pr_review_metrics_rows: Iterable[Dict],
    *,
    user_to_group: Optional[Dict[str, str]] = None,
    selected_repos: Optional[Set[str]] = None,
    diffstat_enabled: bool = True,
) -> List[Dict]:
    user_to_group = user_to_group or {}
    selected_repos = {(r or "").strip() for r in (selected_repos or set()) if (r or "").strip()}

    agg = defaultdict(
        lambda: {
            "prs_opened_count": 0,
            "commits_count": 0,
            "lines_added": 0,
            "lines_removed": 0,
            "lines_changed": 0,
            "files_changed": 0,
            "_pr_time_open_minutes": [],
            "_pr_comments_total": [],
            "_pr_commits_total": [],
            "_time_to_first_review_minutes": [],
            "_time_to_first_approval_minutes": [],
            "prs_with_review_time_count": 0,
            "prs_with_approval_time_count": 0,
        }
    )

    # commits => (author, repo)
    for r in commit_rows:
        uid = r.get("author") or "UNKNOWN"
        repo = _norm_repo(r.get("repo_slug") or "")
        if selected_repos and repo not in selected_repos:
            continue

        a = agg[(uid, repo)]
        a["commits_count"] += 1

        # if diffstat disabled, commit rows may have "NA"; ignore them in totals
        if diffstat_enabled:
            a["lines_added"] += _safe_int(r.get("lines_added"))
            a["lines_removed"] += _safe_int(r.get("lines_removed"))
            a["lines_changed"] += _safe_int(r.get("lines_changed"))
            a["files_changed"] += _safe_int(r.get("files_changed"))

    # PRs => (author, repo)
    for r in pr_rows:
        uid = r.get("author") or "UNKNOWN"
        repo = _norm_repo(r.get("repo_slug") or "")
        if selected_repos and repo not in selected_repos:
            continue

        a = agg[(uid, repo)]
        a["prs_opened_count"] += 1
        a["_pr_time_open_minutes"].append(_safe_float(r.get("time_open_minutes")))
        a["_pr_comments_total"].append(_safe_float(r.get("comments_total")))
        a["_pr_commits_total"].append(_safe_float(r.get("commits_count_total") or r.get("commits_count_kept")))

    # review metrics => (author, repo)
    for r in pr_review_metrics_rows:
        uid = (r.get("author") or "").strip() or "UNKNOWN"
        repo = _norm_repo(r.get("repo_slug") or "")
        if selected_repos and repo not in selected_repos:
            continue

        a = agg[(uid, repo)]

        t_review = r.get("time_to_first_review_minutes")
        t_approval = r.get("time_to_first_approval_minutes")

        before_review_len = len(a["_time_to_first_review_minutes"])
        before_approval_len = len(a["_time_to_first_approval_minutes"])

        _append_if_number_allow_zero(a["_time_to_first_review_minutes"], t_review)
        _append_if_number_allow_zero(a["_time_to_first_approval_minutes"], t_approval)

        if len(a["_time_to_first_review_minutes"]) > before_review_len:
            a["prs_with_review_time_count"] += 1
        if len(a["_time_to_first_approval_minutes"]) > before_approval_len:
            a["prs_with_approval_time_count"] += 1

    out: List[Dict] = []
    for (uid, repo), a in agg.items():
        group = user_to_group.get(uid, "")
        out.append(_calc_user_row(uid, group, repo, a, diffstat_enabled=diffstat_enabled))

    out.sort(key=lambda x: (x["group"], x["user"], x["repo"]))
    return out


def summarize_groups_by_repo(
    users_summary_rows_by_repo: Iterable[Dict],
    *,
    selected_repos: Optional[Set[str]] = None,
    diffstat_enabled: bool = True,
) -> List[Dict]:
    selected_repos = {(r or "").strip() for r in (selected_repos or set()) if (r or "").strip()}

    agg = defaultdict(
        lambda: {
            "users_count_in_scan": 0,
            "prs_opened_count": 0,
            "commits_count": 0,
            "lines_added": 0,
            "lines_removed": 0,
            "lines_changed": 0,
            "files_changed": 0,
            "_time_open_weighted_sum": 0.0,
            "_time_open_weight": 0.0,
            "_median_time_open_list": [],
            "_review_time_list": [],
            "_approval_time_list": [],
            "prs_with_review_time_count": 0,
            "prs_with_approval_time_count": 0,
        }
    )

    for r in users_summary_rows_by_repo:
        g = (r.get("group") or "").strip()
        repo = _norm_repo(r.get("repo") or "")
        if not g:
            continue
        if selected_repos and repo not in selected_repos:
            continue

        a = agg[(g, repo)]
        a["users_count_in_scan"] += 1

        prs = _safe_int(r.get("prs_opened_count"))
        a["prs_opened_count"] += prs
        a["commits_count"] += _safe_int(r.get("commits_count"))

        # diffstat dependent: could be NA
        if diffstat_enabled:
            a["lines_added"] += _safe_int(r.get("lines_added"))
            a["lines_removed"] += _safe_int(r.get("lines_removed"))
            a["lines_changed"] += _safe_int(r.get("lines_changed"))
            a["files_changed"] += _safe_int(r.get("files_changed"))

        avg_time_open = _safe_float(r.get("avg_pr_time_open_minutes"))
        a["_time_open_weighted_sum"] += avg_time_open * prs
        a["_time_open_weight"] += prs
        a["_median_time_open_list"].append(_safe_float(r.get("median_pr_time_open_minutes")))

        # These are already averaged per user; for group graph we keep simple mean of users' averages.
        # Also: they can be "" so append_if_number_allow_zero handles parse and allows 0.
        _append_if_number_allow_zero(a["_review_time_list"], r.get("avg_time_to_first_review_minutes"))
        _append_if_number_allow_zero(a["_approval_time_list"], r.get("avg_time_to_first_approval_minutes"))

        a["prs_with_review_time_count"] += _safe_int(r.get("prs_with_review_time_count"))
        a["prs_with_approval_time_count"] += _safe_int(r.get("prs_with_approval_time_count"))

    out: List[Dict] = []
    for (g, repo), a in agg.items():
        users = int(a["users_count_in_scan"] or 0)
        prs = int(a["prs_opened_count"] or 0)

        avg_prs_per_user = round((prs / users), 3) if users else 0.0
        avg_time_open = round((a["_time_open_weighted_sum"] / a["_time_open_weight"]), 3) if a["_time_open_weight"] else 0.0
        med_time_open = round(median(a["_median_time_open_list"]), 3) if a["_median_time_open_list"] else 0.0

        # Opção B => blank when no data
        avg_review = _fmt_avg_or_blank(a["_review_time_list"])
        med_review = _fmt_median_or_blank(a["_review_time_list"])
        avg_approval = _fmt_avg_or_blank(a["_approval_time_list"])
        med_approval = _fmt_median_or_blank(a["_approval_time_list"])

        if diffstat_enabled:
            lines_added: object = int(a["lines_added"])
            lines_removed: object = int(a["lines_removed"])
            lines_changed: object = int(a["lines_changed"])
            files_changed: object = int(a["files_changed"])
        else:
            lines_added = "NA"
            lines_removed = "NA"
            lines_changed = "NA"
            files_changed = "NA"

        out.append(
            {
                "group": g,
                "repo": repo,
                "avg_prs_per_user": avg_prs_per_user,
                "avg_pr_time_open_minutes": avg_time_open,
                "median_pr_time_open_minutes": med_time_open,
                "avg_time_to_first_review_minutes": avg_review,
                "median_time_to_first_review_minutes": med_review,
                "avg_time_to_first_approval_minutes": avg_approval,
                "median_time_to_first_approval_minutes": med_approval,
                "users_count_in_scan": users,
                "prs_opened_count": prs,
                "commits_count": int(a["commits_count"]),
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "lines_changed": lines_changed,
                "files_changed": files_changed,
                "prs_with_review_time_count": int(a["prs_with_review_time_count"]),
                "prs_with_approval_time_count": int(a["prs_with_approval_time_count"]),
                "diffstat_enabled": "1" if diffstat_enabled else "0",
            }
        )

    out.sort(key=lambda x: (x["group"], x["repo"]))
    return out