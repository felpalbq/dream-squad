#!/usr/bin/env python3
"""
Dream Squad — Apify Collector
Coleta posts públicos de perfis de referência via Apify.
Sem autenticação — apenas perfis públicos.
Controle de budget via profile.yaml (apify_budget_credits).
Falha silenciosa se API indisponível ou budget esgotado.
"""

import os
import re
import sys
import json
import yaml
import argparse
from datetime import datetime
from pathlib import Path

from agents.utils.paths import load_profile
from agents.utils.logging_config import get_logger
from agents.utils.retry import with_retry
from agents.utils.validators import PesquisaApify, validate_yaml_output
from agents.utils.engagement import score_from_dict

logger = get_logger(__name__)

_PERMISSION_ERRORS = ("permission", "forbidden", "unauthorized", "plan", "quota")


def _is_permission_error(e: Exception) -> bool:
    """Erros de permissão/plano não devem gerar retry."""
    msg = str(e).lower()
    return any(kw in msg for kw in _PERMISSION_ERRORS)


@with_retry(max_attempts=2, base_delay=3.0, label="Apify run")
def _run_actor(client, actor_id: str, run_input: dict, retries: list = None) -> list[dict]:
    run = client.actor(actor_id).call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return items


def _extract_tema(caption: str) -> str:
    """Primeira frase ou primeira hashtag forte."""
    caption = caption.strip()
    first_sentence = re.split(r"[.!?\n]", caption, maxsplit=1)[0]
    if 20 <= len(first_sentence) <= 80:
        return first_sentence.strip()
    hashtags = re.findall(r"#(\w+)", caption)
    if hashtags:
        return " · ".join(hashtags[:3])
    return caption[:80].strip()


def _build_titulo(handle: str, item: dict) -> str:
    """Título distintivo: data + tipo + handle."""
    date_str = str(item.get("timestamp", ""))[:10]
    post_type = item.get("type", "Post")
    return f"{post_type} de @{handle} ({date_str})"


def _clean_caption(caption: str) -> str:
    """Remove emojis no início, normaliza espaço, trunca em 400."""
    cleaned = re.sub(r"^[^\w]+", "", caption)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:400]


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Apify Collector")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    api_token = os.environ.get("APIFY_API_TOKEN", "")
    if not api_token:
        _write_error(args.output, args.client_id, "APIFY_API_TOKEN não configurado")
        logger.warning("Apify: token ausente. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    try:
        from apify_client import ApifyClient
    except ImportError as e:
        _write_error(args.output, args.client_id, f"apify-client não instalado: {e}")
        logger.warning("Apify: biblioteca não disponível. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    client_profile = load_profile(args.client_id)
    research_cfg = client_profile.get("research", {})
    max_crawl_requests = research_cfg.get("apify_max_crawl_requests", 30)
    profiles = client_profile.get("instagram_reference_profiles", [])
    max_posts = research_cfg.get("apify_max_posts_per_profile", 5)

    if not profiles:
        _write_error(args.output, args.client_id, "Nenhum perfil de referência configurado")
        logger.warning("Apify: sem perfis de referência no profile.yaml. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    apify = ApifyClient(api_token)
    resultados = []
    total_retries = 0

    for profile_info in profiles:
        handle = profile_info.get("handle", "").lstrip("@")
        if not handle:
            continue

        retries = []
        try:
            items = _run_actor(
                apify,
                actor_id="apify/instagram-scraper",
                run_input={
                    "directUrls": [f"https://www.instagram.com/{handle}/"],
                    "resultsType": "posts",
                    "resultsLimit": max_posts,        # trava de custo: $0,001 × max_posts
                    "maxRequestsPerCrawl": max_crawl_requests,  # trava de segurança HTTP
                },
                retries=retries,
            )
            total_retries += retries[0] if retries else 0

            for item in items:
                post_dict = {
                    "curtidas": item.get("likesCount", 0),
                    "comentarios": item.get("commentsCount", 0),
                    "data_postagem": str(item.get("timestamp", "")),
                }
                engagement_score = score_from_dict(post_dict, "instagram")
                resultados.append({
                    "tema": _extract_tema(item.get("caption", "")),
                    "titulo": _build_titulo(handle, item),
                    "descricao": _clean_caption(item.get("caption", "")),
                    "url_fonte": item.get("url", ""),
                    "data_hora": str(item.get("timestamp", ""))[:10],
                    "relevancia_nicho": None,
                    "origem": "apify",
                    "perfil": f"@{handle}",
                    "curtidas": item.get("likesCount", 0),
                    "comentarios": item.get("commentsCount", 0),
                    "engagement_score": engagement_score,
                    "post_type": item.get("type", ""),
                    "hashtags": item.get("hashtags", [])[:10],
                })

            logger.info("Apify OK: @%s — %d posts", handle, len(items))

        except Exception as e:
            total_retries += retries[0] if retries else 0
            if _is_permission_error(e):
                logger.error(
                    "Apify: erro de permissão/plano para @%s (%s). "
                    "Verifique a conta Apify — sem retry.",
                    handle, e,
                )
            else:
                logger.warning("Apify falhou para @%s: %s", handle, e)

    niche = client_profile.get("niche", "")
    if not niche:
        logger.warning("Apify: campo 'niche' ausente ou vazio no profile.yaml")
        niche = "não especificado"
    data = {
        "pesquisa_apify": {
            "client_id": args.client_id,
            "nicho": niche,
            "data_pesquisa": datetime.now().isoformat(),
            "resultados": resultados,
        }
    }

    try:
        validate_yaml_output(data["pesquisa_apify"], PesquisaApify, "apify")
    except ValueError as e:
        _write_error(args.output, args.client_id, str(e))
        logger.error("Apify: schema inválido: %s. Fonte pulada.", e)
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": total_retries}))
        sys.exit(0)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    n = len(resultados)
    logger.info("Apify: %d posts → %s", n, output_path)
    print("METRICS_JSON: " + json.dumps({"resultados_count": n, "retries": total_retries}))


def _write_error(output: str, client_id: str, erro: str) -> None:
    data = {
        "pesquisa_apify": {
            "client_id": client_id,
            "nicho": "",
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
