"""Rotação determinística de queries por eixo editorial."""

import hashlib
import random
from datetime import datetime
from typing import Any

MONTH_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

TAVILY_TEMPLATES: list[tuple[str, str]] = [
    ("mercado", "{niche} tendências Brasil {year}"),
    ("comportamento", "comportamento {audience_first} {year}"),
    ("cultura", "cultura digital {audience_first} Brasil"),
    ("noticia", "{niche} notícias {month_year_pt}"),
    ("sazonal", "{seasonal_tag} {niche} Brasil"),
    ("regional", "{niche} {city} Bahia {month_year_pt}"),
    ("caso", "case sucesso {niche} pequena empresa"),
    ("curiosidade", "{audience_first} curiosidades {niche}"),
]

OLLAMA_TEMPLATES: list[tuple[str, str]] = [
    ("noticia", "notícias {city} Itabuna Bahia {month_year_pt}"),
    ("regional", "{niche} {city} Bahia {year}"),
    ("evento", "eventos comportamento consumidor {city} Bahia {month_year_pt}"),
    ("sazonal", "{seasonal_tag} {city} Bahia"),
    ("comportamento", "comportamento {audience_first} {city} Bahia"),
    ("curiosidade", "{audience_first} {city} Bahia notícias"),
]

GEMINI_FOCI: list[tuple[str, str]] = [
    ("comportamento", "Tendências comportamentais ou culturais emergentes relacionadas ao nicho OU ao público-alvo (mesmo que indiretamente)"),
    ("dados", "Estudos, pesquisas ou reportagens recentes com dados verificáveis"),
    ("social", "Comportamentos sociais em alta no Brasil relacionados ao público-alvo"),
    ("polarizacao", "Tópicos com potencial de polarização genuína (respeitando voice.avoid)"),
    ("sazonal", "Oportunidades sazonais específicas para esta data"),
    ("conexao", "Temas que conectam o PÚBLICO-ALVO ao nicho de forma INDIRETA e criativa"),
]


def _week_iso(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%G-W%V")


def select_queries(
    templates: list[tuple[str, str]],
    n: int,
    client_id: str,
    week_iso: str | None = None,
) -> list[tuple[str, str]]:
    """Seleciona N templates de forma determinística por cliente + semana."""
    week = week_iso or _week_iso()
    key = f"{client_id}:{week}".encode()
    seed = int(hashlib.sha256(key).hexdigest(), 16)
    rng = random.Random(seed)
    return rng.sample(templates, min(n, len(templates)))


def select_gemini_focus(
    n: int = 2,
    client_id: str = "",
    week_iso: str | None = None,
) -> list[tuple[str, str]]:
    """Seleciona N focos editoriais para o prompt do Gemini."""
    week = week_iso or _week_iso()
    key = f"gemini:{client_id}:{week}".encode()
    seed = int(hashlib.sha256(key).hexdigest(), 16)
    rng = random.Random(seed)
    return rng.sample(GEMINI_FOCI, min(n, len(GEMINI_FOCI)))


def build_query_context(client_profile: dict[str, Any], dt: datetime | None = None) -> dict[str, str]:
    """Extrai variáveis de substituição a partir do profile do cliente."""
    dt = dt or datetime.now()
    niche = client_profile.get("niche", "")
    audience = client_profile.get("audience", {}).get("description", "público geral")
    audience_first = audience.split(",")[0].strip()
    location = client_profile.get("location", "Brasil")
    city = location.split(",")[0].strip()
    year = dt.strftime("%Y")
    month_year_pt = f"{MONTH_PT.get(dt.month, '')} {year}"

    # Tag sazonal simplificada para query
    seasonal_map = {
        "Natal": "Natal", "Carnaval": "Carnaval", "Páscoa": "Páscoa",
        "Dia Internacional da Mulher": "Dia da Mulher", "Dia das Mães": "Dia das Mães",
        "Dia dos Namorados": "Namorados", "Dia dos Pais": "Dia dos Pais",
        "Dia das Crianças": "Crianças", "Black Friday": "Black Friday",
        "férias": "férias", "primavera": "primavera", "verão": "verão",
        "outono": "outono", "inverno": "inverno",
    }
    seasonal_tag = ""
    for k, v in seasonal_map.items():
        if k.lower() in month_year_pt.lower():
            seasonal_tag = v
            break
    if not seasonal_tag:
        seasonal_tag = MONTH_PT.get(dt.month, "")

    # Extrair até 3 palavras-chave do manual_input.yaml se existir
    manual_keywords = ""
    client_id = client_profile.get("client_id", "")
    if not client_id:
        logger.warning("build_query_context: client_id ausente no profile, pulando manual_keywords")
    else:
        try:
            from agents.utils.paths import client_dir
            manual_path = client_dir(client_id) / "manual_input.yaml"
            if manual_path.exists():
                import yaml
                with open(manual_path, encoding="utf-8") as f:
                    manual = yaml.safe_load(f) or {}
                temas = [r.get("tema", "") for r in manual.get("resultados", []) if r.get("tema")]
                if temas:
                    # Pegar até 5 palavras dos temas manuais
                    words = " ".join(temas[:2]).split()
                    manual_keywords = " ".join(words[:5])
        except Exception:
            pass

    return {
        "niche": niche,
        "audience_first": audience_first,
        "location": location,
        "city": city,
        "year": year,
        "month_year_pt": month_year_pt,
        "seasonal_tag": seasonal_tag,
        "manual_keywords": manual_keywords,
    }


def format_query(template: str, context: dict[str, str]) -> str:
    """Substitui placeholders no template pelos valores do contexto."""
    return template.format(**context)
