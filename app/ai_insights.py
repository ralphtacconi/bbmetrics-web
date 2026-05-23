from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def generate_insights(results: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Generate AI insights from scan results using Azure OpenAI.
    Returns None (graceful degradation) if OpenAI is not configured.
    """
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.getenv("AZURE_OPENAI_KEY", "")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    if not endpoint or not api_key:
        return None

    try:
        from openai import AzureOpenAI  # type: ignore

        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version="2024-02-01",
        )

        prs: List[Dict] = results.get("prs", [])
        users: List[Dict] = results.get("users_summary", [])

        summary_lines = [
            f"Total PRs analisados: {len(prs)}",
            f"Total de desenvolvedores: {len(users)}",
        ]

        if prs:
            avg_time = _safe_avg([_safe_float(r.get("time_open_minutes")) for r in prs])
            if avg_time:
                summary_lines.append(f"Tempo médio de PR aberto: {avg_time:.1f} minutos ({avg_time/60:.1f} horas)")

        if users:
            top_user = max(users, key=lambda u: _safe_int(u.get("prs_opened_count", 0)), default=None)
            if top_user:
                summary_lines.append(
                    f"Desenvolvedor mais ativo: {top_user.get('user','N/A')} "
                    f"com {top_user.get('prs_opened_count',0)} PRs"
                )

        context = "\n".join(summary_lines)

        prompt = f"""Você é um especialista em engenharia de software e code review.
Analise as seguintes métricas de pull requests do Bitbucket e forneça insights em português:

{context}

Forneça:
1. Um resumo executivo (2-3 frases)
2. Até 3 alertas de risco (ex: PRs com tempo alto de espera, falta de revisores)
3. Até 3 recomendações para melhorar o processo de code review

Responda em JSON com campos: summary (string), risk_alerts (lista de strings), recommendations (lista de strings)."""

        response = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        import json

        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    except Exception:
        return None


def _safe_float(v) -> float:
    try:
        if v is None or v == "" or v == "NA":
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _safe_int(v) -> int:
    try:
        if v is None or v == "" or v == "NA":
            return 0
        return int(v)
    except Exception:
        return 0


def _safe_avg(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v > 0]
    if not vals:
        return None
    return sum(vals) / len(vals)
