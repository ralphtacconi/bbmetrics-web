from __future__ import annotations

import json
import os
from typing import Any, Dict


def _default_insights(metrics: Dict[str, Any]) -> Dict[str, Any]:
    total_prs = int(metrics.get('total_prs', 0) or 0)
    return {
        'summary': f'Scan concluído com {total_prs} PRs analisados.',
        'risk_alerts': [],
        'recommendations': [
            'Configure Azure OpenAI (endpoint + chave) para habilitar insights gerados por IA.'
        ],
    }


def generate_ai_insights(metrics: Dict[str, Any]) -> Dict[str, Any]:
    endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '').strip()
    api_key = os.getenv('AZURE_OPENAI_KEY', '').strip()
    model = os.getenv('AZURE_OPENAI_MODEL', 'gpt-4o')
    api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-08-01-preview')

    if not endpoint or not api_key:
        return _default_insights(metrics)

    try:
        from openai import AzureOpenAI

        client = AzureOpenAI(api_key=api_key, api_version=api_version, azure_endpoint=endpoint)
        prompt = (
            'Você é um especialista em engenharia de software. '
            'Com base nas métricas abaixo, responda APENAS em JSON com o formato '
            '{"summary": string, "risk_alerts": string[], "recommendations": string[]}\n\n'
            f'Métricas: {json.dumps(metrics, ensure_ascii=False)}'
        )
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[{'role': 'user', 'content': prompt}],
        )
        content = (response.choices[0].message.content or '').strip()
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError('AI output is not an object')
        return {
            'summary': parsed.get('summary', ''),
            'risk_alerts': parsed.get('risk_alerts', []),
            'recommendations': parsed.get('recommendations', []),
        }
    except Exception:
        return _default_insights(metrics)
