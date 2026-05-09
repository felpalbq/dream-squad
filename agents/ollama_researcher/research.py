#!/usr/bin/env python3
"""
Dream Squad — Ollama Researcher (Regional)
Pesquisa regional via Ollama web_search. Substitui o Playwright Regional.
Foco em notícias e tendências de Ilhéus/Itabuna, BA relevantes para o nicho do cliente.
Falha silenciosa: se a API falhar, o research continua sem esta fonte.
"""

import os
import sys
import yaml
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.utils.paths import load_profile


_SYNTHESIS_PROMPT = """\
Você é o Agente de Pesquisa Regional do sistema Dream Squad.

CONTEXTO DO CLIENTE:
- client_id: {client_id}
- Nicho: {niche}
- Localização: {location}
- Público-alvo: {audience}
- Data atual: {date}
- Período sazonal: {seasonal}

RESULTADOS DAS BUSCAS REALIZADAS:
{search_results}

TAREFA:
Com base nos resultados acima, identifique notícias, eventos e tendências REGIONAIS de \
Ilhéus/Itabuna relevantes para este nicho e público-alvo.
Aplique o critério de conexão indireta: o tema não precisa ser sobre o nicho diretamente \
— precisa ter um ângulo que conecta com o nicho ou com o público-alvo.
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
    parser.add_argument("--output", required=True, help="Path do .yaml de saída")
    args = parser.parse_args()

    api_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    model = os.environ.get("OLLAMA_RESEARCHER_MODEL", os.environ.get("OLLAMA_MODEL", "kimi-k2.6:cloud"))

    if not api_key:
        _write_error(args.output, args.client_id, "", "OLLAMA_API_KEY não configurada")
        print("[AVISO] Ollama Regional falhou (OLLAMA_API_KEY ausente). Research continua sem esta fonte.", file=sys.stderr)
        sys.exit(0)

    try:
        from ollama import Client, web_search
    except ImportError as e:
        _write_error(args.output, args.client_id, "", f"ollama library não disponível: {e}")
        print(f"[AVISO] Ollama Regional falhou ({e}). Research continua.", file=sys.stderr)
        sys.exit(0)

    # Configura a lib ollama para usar o servidor correto
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
            search_results.append(f"Query: {query}\n{result}")
            print(f"  [OK] web_search: {query}", file=sys.stderr)
        except Exception as e:
            print(f"  [AVISO] web_search falhou para '{query}': {e}", file=sys.stderr)

    if not search_results:
        _write_error(args.output, args.client_id, niche, "Todas as buscas falharam")
        print("[AVISO] Ollama Regional — todas as buscas falharam. Research continua.", file=sys.stderr)
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

    try:
        response = ollama_client.chat(
            model=model,
            messages=[{"role": "user", "content": synthesis_prompt}],
            options={"temperature": 0.2},
        )
        raw = _strip_fences(response.message.content)
        data = yaml.safe_load(raw)

        if not isinstance(data, dict) or "pesquisa_ollama_regional" not in data:
            raise ValueError("Resposta não contém 'pesquisa_ollama_regional'")

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        n = len(data["pesquisa_ollama_regional"].get("resultados", []))
        print(f"[ollama_researcher] {n} resultados regionais → {output_path}")

    except Exception as e:
        _write_error(args.output, args.client_id, niche, str(e))
        print(f"[AVISO] Ollama Regional falhou ({e}). Research continua sem esta fonte.", file=sys.stderr)


if __name__ == "__main__":
    main()
