#!/usr/bin/env python3
"""
Dream Squad — Ollama Researcher (Regional)
Pesquisa regional via Ollama web_search + web_fetch em sites configurados.
Foco em Ilhéus/Itabuna, BA. Falha silenciosa por fonte.
"""

import os
import sys
import json
import yaml
import argparse
from datetime import datetime
from pathlib import Path

from agents.utils.paths import load_profile
from agents.utils.logging_config import get_logger
from agents.utils.retry import with_retry
from agents.utils.validators import PesquisaOllama, validate_yaml_output

logger = get_logger(__name__)

ROOT = Path(__file__).parent.parent.parent
_WEB_FETCH_MAX_CHARS = 6000

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
Os resultados abaixo vêm de duas fontes:
1. Buscas web (web_search) — consultas direcionadas ao contexto do cliente
2. Portais regionais (web_fetch) — conteúdo buscado diretamente nos sites configurados

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
"""


def _seasonal_context(dt: datetime) -> str:
    m, d = dt.month, dt.day
    windows = [
        ((12, 10), (1, 10), "Natal e Ano Novo"),
        ((1, 25), (2, 28), "Carnaval próximo"),
        ((4, 25), (5, 14), "Dia das Mães"),
        ((5, 25), (6, 14), "Dia dos Namorados"),
        ((7, 25), (8, 14), "Dia dos Pais"),
        ((10, 25), (11, 30), "Black Friday, pré-Natal"),
    ]
    current = (m, d)
    for (sm, sd), (em, ed), label in windows:
        if (sm, sd) <= current <= (em, ed):
            return label
    month_labels = {
        1: "início de ano", 2: "verão", 3: "outono chegando",
        4: "outono/Páscoa", 5: "Dia das Mães", 6: "Dia dos Namorados",
        7: "férias de julho", 8: "Dia dos Pais", 9: "primavera",
        10: "Dia das Crianças", 11: "Black Friday", 12: "Natal",
    }
    return month_labels.get(m, "período sem sazonalidade específica")


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


def _build_queries(niche: str, location: str, date_str: str) -> list[str]:
    city = location.split(",")[0].strip()
    month_year = datetime.now().strftime("%B %Y")
    return [
        f"notícias {city} Itabuna Bahia {month_year}",
        f"{niche} {city} Bahia {date_str[:7]}",
        f"eventos comportamento consumidor {city} Bahia {month_year}",
    ]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```yaml"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


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

    try:
        from ollama import Client, web_search, web_fetch
    except ImportError as e:
        _write_error(args.output, args.client_id, "", f"ollama library não disponível: {e}")
        logger.warning("Ollama Regional: biblioteca não disponível. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    os.environ["OLLAMA_HOST"] = api_base
    os.environ["OLLAMA_API_KEY"] = api_key

    client_profile = load_profile(args.client_id)
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")

    niche = client_profile.get("niche", "")
    location = client_profile.get("location", "Ilhéus, BA")
    audience = client_profile.get("audience", {}).get("description", "público geral")
    seasonal = _seasonal_context(now)

    queries = _build_queries(niche, location, date_str)
    search_results = []

    for query in queries:
        try:
            result = web_search(query, max_results=5)
            search_results.append(f"[web_search] Query: {query}\n{result}")
            logger.info("web_search OK: %s", query)
        except Exception as e:
            logger.warning("web_search falhou para '%s': %s", query, e)

    sites = _load_search_sites()
    for site_url in sites:
        try:
            content = web_fetch(site_url)
            truncated = str(content)[:_WEB_FETCH_MAX_CHARS]
            search_results.append(f"[web_fetch] Portal: {site_url}\n{truncated}")
            logger.info("web_fetch OK: %s", site_url)
        except Exception as e:
            logger.warning("web_fetch falhou para '%s': %s", site_url, e)

    if not search_results:
        _write_error(args.output, args.client_id, niche, "Todas as buscas falharam")
        logger.warning("Ollama Regional: todas as buscas falharam. Research continua.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    synthesis_prompt = _SYNTHESIS_PROMPT.format(
        client_id=args.client_id,
        niche=niche,
        location=location,
        audience=audience,
        date=date_str,
        seasonal=seasonal,
        search_results="\n\n---\n\n".join(search_results),
    )

    ollama_client = Client(
        host=api_base,
        headers={"Authorization": f"Bearer {api_key}"},
    )

    @with_retry(max_attempts=3, base_delay=2.0, label="Ollama chat")
    def _call_ollama():
        return ollama_client.chat(
            model=model,
            messages=[{"role": "user", "content": synthesis_prompt}],
            options={"temperature": 0.2},
        )

    try:
        response = _call_ollama()
        raw = _strip_fences(response.message.content)
        data = yaml.safe_load(raw)

        if not isinstance(data, dict) or "pesquisa_ollama_regional" not in data:
            raise ValueError("Resposta não contém 'pesquisa_ollama_regional'")

        for r in data["pesquisa_ollama_regional"].get("resultados", []):
            r.setdefault("origem", "ollama")

        validate_yaml_output(data["pesquisa_ollama_regional"], PesquisaOllama, "ollama")

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        n = len(data["pesquisa_ollama_regional"].get("resultados", []))
        logger.info("Ollama Regional: %d resultados → %s", n, output_path)
        print("METRICS_JSON: " + json.dumps({"resultados_count": n, "retries": 0}))

    except Exception as e:
        _write_error(args.output, args.client_id, niche, str(e))
        logger.error("Ollama Regional falhou: %s. Research continua.", e)
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))


if __name__ == "__main__":
    main()
