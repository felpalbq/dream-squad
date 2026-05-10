#!/usr/bin/env python3
"""
Dream Squad — Tavily Researcher
Web search geral via Tavily API com controle de requests por execução.
Falha silenciosa: research continua sem esta fonte se API falhar.
"""

import os
import sys
import re
import json
import yaml
import argparse
from datetime import datetime
from pathlib import Path

from agents.utils.paths import load_profile
from agents.utils.logging_config import get_logger
from agents.utils.retry import with_retry
from agents.utils.validators import PesquisaTavily, validate_yaml_output

logger = get_logger(__name__)


def _build_queries(niche: str, audience: str, location: str) -> list[str]:
    city = location.split(",")[0].strip()
    year = datetime.now().strftime("%Y")
    audience_first = audience.split(",")[0].strip()
    return [
        f"{niche} tendências Brasil {year}",
        f"comportamento consumidor {audience_first} Brasil",
        f"{niche} {city} Bahia",
    ]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


@with_retry(max_attempts=3, base_delay=2.0, label="Tavily search")
def _tavily_search(
    client,
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    days: int | None = None,
) -> list[dict]:
    kwargs = {"query": query, "max_results": max_results, "search_depth": search_depth}
    if days is not None:
        kwargs["days"] = days
    response = client.search(**kwargs)
    return response.get("results", [])


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Tavily Researcher")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        _write_error(args.output, args.client_id, "", "TAVILY_API_KEY não configurada")
        logger.warning("Tavily: TAVILY_API_KEY ausente. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    try:
        from tavily import TavilyClient
    except ImportError as e:
        _write_error(args.output, args.client_id, "", f"tavily-python não instalado: {e}")
        logger.warning("Tavily: biblioteca não disponível. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    client_profile = load_profile(args.client_id)
    niche = client_profile.get("niche", "")
    audience = client_profile.get("audience", {}).get("description", "público geral")
    location = client_profile.get("location", "Brasil")
    research_cfg = client_profile.get("research", {})
    max_requests = research_cfg.get("tavily_max_requests", 3)
    search_depth = research_cfg.get("tavily_search_depth", "basic")
    days = research_cfg.get("tavily_days", 30)

    tavily = TavilyClient(api_key=api_key)
    queries = _build_queries(niche, audience, location)[:max_requests]

    raw_results: list[dict] = []
    for query in queries:
        try:
            results = _tavily_search(tavily, query, search_depth=search_depth, days=days)
            for r in results:
                raw_results.append({
                    "tema": _strip_html(r.get("title", ""))[:80],
                    "titulo": _strip_html(r.get("title", "")),
                    "descricao": _strip_html(r.get("content", ""))[:400],
                    "url_fonte": r.get("url", ""),
                    "data_hora": datetime.now().strftime("%Y-%m-%d"),
                    "relevancia_nicho": 5,  # neutro — Scoring/Merge reavalia
                    "origem": "tavily",
                })
            logger.info("Tavily OK: '%s' → %d resultados", query, len(results))
        except Exception as e:
            logger.warning("Tavily falhou para '%s': %s", query, e)

    if not raw_results:
        _write_error(args.output, args.client_id, niche, "Todas as buscas Tavily falharam")
        logger.warning("Tavily: zero resultados. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    data = {
        "pesquisa_tavily": {
            "client_id": args.client_id,
            "nicho": niche,
            "data_pesquisa": datetime.now().isoformat(),
            "resultados": raw_results,
        }
    }

    validate_yaml_output(data["pesquisa_tavily"], PesquisaTavily, "tavily")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    n = len(raw_results)
    logger.info("Tavily: %d resultados → %s", n, output_path)
    print("METRICS_JSON: " + json.dumps({"resultados_count": n, "retries": 0}))


def _write_error(output: str, client_id: str, niche: str, erro: str) -> None:
    data = {
        "pesquisa_tavily": {
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


if __name__ == "__main__":
    main()
