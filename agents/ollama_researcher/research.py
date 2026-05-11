#!/usr/bin/env python3
"""
Dream Squad — Ollama Researcher (Regional)
Pesquisa regional via requests direto à API Ollama + web fetch em sites configurados.
Foco em Ilhéus/Itabuna, BA. Falha silenciosa por fonte.
"""

import os
import re
import sys
import json
import yaml
import argparse
import requests
from datetime import datetime
from pathlib import Path

from agents.utils.paths import load_profile
from agents.utils.logging_config import get_logger
from agents.utils.retry import with_retry
from agents.utils.validators import PesquisaOllama, validate_yaml_output
from agents.utils.query_rotation import select_queries, build_query_context, format_query, OLLAMA_TEMPLATES
from agents.utils.seasonality import seasonal_context
from agents.utils.text_utils import strip_fences

logger = get_logger(__name__)

ROOT = Path(__file__).parent.parent.parent
_WEB_FETCH_MAX_CHARS = 6000
_OLLAMA_CHAT_TIMEOUT = 120

_SYNTHESIS_PROMPT = """\
Você é o Agente de Pesquisa Regional do sistema Dream Squad.

CONTEXTO DO CLIENTE:
- client_id: {client_id}
- Nicho: {niche}
- Localização: {location}
- Público-alvo: {audience}
- Data atual: {date}
- Período sazonal: {seasonal}

RESULTADOS COLETADOS:
{search_results}

TAREFA:
Com base nos resultados acima, identifique notícias, eventos e tendências REGIONAIS de \
Ilhéus/Itabuna relevantes para este nicho e público-alvo.
Aplique o critério de conexão indireta: o tema não precisa ser sobre o nicho diretamente \
— precisa ter um ângulo que conecta com o nicho ou com o público-alvo.
Priorize resultados concretos (notícias com data, evento específico) sobre resultados genéricos.
Descarte resultados sem relação possível.

Retorne SOMENTE o YAML abaixo, sem texto adicional, sem code fences:

pesquisa_ollama_regional:
  client_id: "{client_id}"
  nicho: "{niche}"
  data_pesquisa: "{date}"
  resultados:
    - tema: "nome do tema"
      titulo: "Título da notícia ou evento"
      descricao: >
        Resumo em 3-4 linhas do conteúdo e conexão com o nicho.
      url_fonte: "https://..."
      data_hora: "YYYY-MM-DD"
      relevancia_nicho: 8
      origem: "ollama"
      sinal_friccao: ""          # preencher quando houver tensão/polarização
      sinal_transformacao: ""    # preencher quando houver mudança de comportamento
      sinal_timing: ""          # preencher: trending_now | weekly_news | evergreen
"""


def _load_search_sites() -> list[str]:
    sites_file = ROOT / "build" / "web_search_sites.txt"
    if not sites_file.exists():
        logger.warning("web_search_sites.txt não encontrado em build/")
        return []
    return [
        line.strip()
        for line in sites_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _build_queries(client_profile: dict, max_queries: int = 3) -> list[tuple[str, str]]:
    context = build_query_context(client_profile)
    selected = select_queries(OLLAMA_TEMPLATES, max_queries, client_profile.get("client_id", ""))
    return [(axis, format_query(tpl, context)) for axis, tpl in selected]


def _web_search_via_ollama(api_base: str, api_key: str, model: str, query: str, max_results: int = 5) -> str:
    """Executa busca web via API Ollama (requests direto). Modelo com acesso à internet retorna resultados."""
    url = f"{api_base.rstrip('/')}/api/chat"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    prompt = (
        f"Você tem acesso à internet. Faça uma busca web sobre: '{query}'. "
        f"Retorne até {max_results} resultados com título, URL, data e resumo de 2-3 linhas de cada um. "
        f"Formato: Título | URL | Data | Resumo. Se não encontrar nada, diga 'Nenhum resultado encontrado'."
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=_OLLAMA_CHAT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")
    except Exception as e:
        logger.warning("web_search via Ollama falhou para '%s': %s", query, e)
        return ""


def _web_fetch_via_requests(site_url: str, max_chars: int = _WEB_FETCH_MAX_CHARS) -> str:
    """Busca conteúdo HTML de uma URL via requests direto."""
    try:
        resp = requests.get(
            site_url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
        )
        resp.raise_for_status()
        text = resp.text
        # Strip tags HTML básicos
        text = re.sub(r"<script.*?>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style.*?>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as e:
        logger.warning("web_fetch falhou para '%s': %s", site_url, e)
        return ""


def _ollama_chat(api_base: str, api_key: str, model: str, messages: list[dict]) -> str:
    """Chama /api/chat da Ollama via requests direto. Retorna o conteúdo da mensagem."""
    url = f"{api_base.rstrip('/')}/api/chat"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=_OLLAMA_CHAT_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "")


def _write_error(output: str, client_id: str, niche: str, erro: str) -> None:
    data = {
        "pesquisa_ollama_regional": {
            "client_id": client_id,
            "nicho": niche,
            "data_pesquisa": datetime.now().isoformat(),
            "status": "falha",
            "erro": erro,
            "resultados": [],
        }
    }
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Ollama Researcher (Regional)")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    api_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    model = os.environ.get("OLLAMA_RESEARCHER_MODEL", os.environ.get("OLLAMA_MODEL", "kimi-k2.6:cloud"))

    if not api_key:
        _write_error(args.output, args.client_id, "", "OLLAMA_API_KEY não configurada")
        logger.warning("Ollama Regional: OLLAMA_API_KEY ausente. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    client_profile = load_profile(args.client_id)
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    niche = client_profile.get("niche", "")
    location = client_profile.get("location", "Ilhéus, BA")
    audience = client_profile.get("audience", {}).get("description", "público geral")
    seasonal = seasonal_context(now)

    queries = _build_queries(client_profile, max_queries=3)
    search_results = []

    for axis, query in queries:
        result = _web_search_via_ollama(api_base, api_key, model, query, max_results=5)
        if result:
            search_results.append(f"[web_search] Query: {query}\n{result}")
            logger.info("web_search OK: %s", query)
        else:
            logger.warning("web_search sem resultados para: %s", query)

    sites = _load_search_sites()
    for site_url in sites:
        content = _web_fetch_via_requests(site_url)
        if content:
            search_results.append(f"[web_fetch] Portal: {site_url}\n{content}")
            logger.info("web_fetch OK: %s", site_url)
        else:
            logger.warning("web_fetch sem conteúdo para: %s", site_url)

    if not search_results:
        _write_error(args.output, args.client_id, niche, "Todas as buscas falharam")
        logger.warning("Ollama Regional: todas as buscas falharam. Research continua.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    pulse = os.environ.get("DREAM_SQUAD_PULSE", "")
    if pulse:
        search_results.append(f"[pulse do operador]\n{pulse}")

    synthesis_prompt = _SYNTHESIS_PROMPT.format(
        client_id=args.client_id,
        niche=niche,
        location=location,
        audience=audience,
        date=date_str,
        seasonal=seasonal,
        search_results="\n\n---\n\n".join(search_results),
    )

    retries = []

    @with_retry(max_attempts=3, base_delay=2.0, label="Ollama chat")
    def _call_ollama(retries):
        return _ollama_chat(
            api_base=api_base,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": synthesis_prompt}],
        )

    try:
        raw_text = _call_ollama(retries)
        raw = strip_fences(raw_text)
        data = yaml.safe_load(raw)

        if not isinstance(data, dict) or "pesquisa_ollama_regional" not in data:
            raise ValueError("Resposta não contém 'pesquisa_ollama_regional'")

        for r in data["pesquisa_ollama_regional"].get("resultados", []):
            r.setdefault("origem", "ollama")

        try:
            validate_yaml_output(data["pesquisa_ollama_regional"], PesquisaOllama, "ollama")
        except ValueError as e:
            actual_retries = retries[0] if retries else 0
            _write_error(args.output, args.client_id, niche, str(e))
            logger.error("Ollama Regional: schema inválido: %s. Research continua.", e)
            print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": actual_retries}))
            sys.exit(0)

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        actual_retries = retries[0] if retries else 0
        n = len(data["pesquisa_ollama_regional"].get("resultados", []))
        logger.info("Ollama Regional: %d resultados → %s", n, output_path)
        print("METRICS_JSON: " + json.dumps({"resultados_count": n, "retries": actual_retries}))

    except Exception as e:
        actual_retries = retries[0] if retries else 0
        _write_error(args.output, args.client_id, niche, str(e))
        logger.error("Ollama Regional falhou: %s. Research continua.", e)
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": actual_retries}))


if __name__ == "__main__":
    main()
