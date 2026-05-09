#!/usr/bin/env python3
"""
Dream Squad — Gemini Researcher
Deep research via Gemini API sobre tendências e oportunidades de conteúdo.
Falha silenciosa: se a API falhar, o research continua sem esta fonte.
"""

import os
import sys
import json
import argparse
import yaml
from datetime import datetime
from pathlib import Path

from google import genai

from agents.utils.paths import load_profile
from agents.utils.logging_config import get_logger
from agents.utils.retry import with_retry
from agents.utils.validators import PesquisaGemini, validate_yaml_output

logger = get_logger(__name__)

_PROMPT_TEMPLATE = """\
Você é um pesquisador de tendências de conteúdo para redes sociais brasileiras.

CONTEXTO DO CLIENTE:
- Nicho: {niche}
- Público-alvo: {audience}
- Localização: {location}
- Data atual: {date}
- Período sazonal: {seasonal}
- Contexto adicional: {extra_context}

TAREFA:
Realize uma pesquisa profunda sobre tendências, estudos e oportunidades de conteúdo AGORA para este nicho.

FOQUE EM:
1. Tendências comportamentais ou culturais emergentes relacionadas ao nicho OU ao público-alvo (mesmo que indiretamente)
2. Estudos, pesquisas ou reportagens recentes com dados verificáveis
3. Comportamentos sociais em alta no Brasil relacionados ao público-alvo
4. Tópicos com potencial de polarização genuína
5. Oportunidades sazonais específicas para esta data

CRITÉRIO EDITORIAL MAIS IMPORTANTE:
Prefira temas que conectam o PÚBLICO-ALVO ao nicho de forma INDIRETA e criativa.
Exemplo: para veterinária, "mães de pet — mulheres que tratam pets como filhos" vale mais do que "vacinação animal".

Para cada tema, forneça:
- Nome curto do tema
- Título da fonte/estudo/reportagem
- Resumo em 3-4 linhas (o que é, dado principal, por que importa)
- URL da fonte (quando possível)
- Data ou período da fonte
- Relevância para o nicho de 0 a 10

Retorne SOMENTE o YAML abaixo, sem texto adicional, sem code fences:

pesquisa_gemini:
  client_id: "{client_id}"
  nicho: "{niche}"
  data_pesquisa: "{date}"
  resultados:
    - tema: "nome do tema"
      titulo: "Título da fonte ou estudo"
      descricao: >
        Resumo em 3-4 linhas.
      url_fonte: "https://..."
      data_hora: "YYYY-MM-DD"
      relevancia_nicho: 8
      origem: "gemini"
"""


def _seasonal_context(dt: datetime) -> str:
    m, d = dt.month, dt.day
    windows = [
        ((12, 10), (1, 10), "Natal e Ano Novo"),
        ((1, 25), (2, 28), "Carnaval próximo"),
        ((2, 25), (3, 10), "Pós-Carnaval, início do outono"),
        ((3, 1), (3, 15), "Dia Internacional da Mulher"),
        ((3, 20), (4, 20), "Páscoa, Semana Santa"),
        ((4, 25), (5, 14), "Dia das Mães"),
        ((5, 25), (6, 14), "Dia dos Namorados"),
        ((7, 1), (7, 31), "Férias escolares de julho"),
        ((7, 25), (8, 14), "Dia dos Pais"),
        ((9, 25), (10, 15), "Dia das Crianças"),
        ((10, 25), (11, 30), "Black Friday, pré-Natal"),
    ]
    current = (m, d)
    for (sm, sd), (em, ed), label in windows:
        start, end = (sm, sd), (em, ed)
        if start <= end:
            if start <= current <= end:
                return label
        else:
            if current >= start or current <= end:
                return label
    month_labels = {
        1: "início de ano", 2: "verão/carnaval", 3: "outono chegando",
        4: "outono/Páscoa", 5: "Dia das Mães", 6: "Dia dos Namorados",
        7: "férias de julho", 8: "Dia dos Pais/inverno", 9: "primavera",
        10: "Dia das Crianças", 11: "Black Friday", 12: "Natal/fim de ano",
    }
    return month_labels.get(m, "período sem sazonalidade específica")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```yaml"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Gemini Researcher")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        _write_error(args.output, args.client_id, "", "GEMINI_API_KEY não configurada")
        logger.warning("Gemini: GEMINI_API_KEY ausente. Fonte pulada.")
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    client_profile = load_profile(args.client_id)
    now = datetime.now()

    prompt = _PROMPT_TEMPLATE.format(
        client_id=args.client_id,
        niche=client_profile.get("niche", ""),
        audience=client_profile.get("audience", {}).get("description", "público geral"),
        location=client_profile.get("location", "Brasil"),
        date=now.strftime("%Y-%m-%d"),
        seasonal=_seasonal_context(now),
        extra_context=client_profile.get("research", {}).get("gemini_context", "nenhum"),
    )

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    client = genai.Client(api_key=api_key)

    @with_retry(max_attempts=3, base_delay=2.0, label="Gemini API")
    def _call_gemini() -> str:
        response = client.models.generate_content(model=model_name, contents=prompt)
        return response.text

    try:
        raw_text = _call_gemini()
        raw = _strip_fences(raw_text)
        data = yaml.safe_load(raw)

        if not isinstance(data, dict) or "pesquisa_gemini" not in data:
            raise ValueError("Resposta Gemini não contém 'pesquisa_gemini'")

        for r in data["pesquisa_gemini"].get("resultados", []):
            r.setdefault("origem", "gemini")

        validate_yaml_output(data["pesquisa_gemini"], PesquisaGemini, "gemini")

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        n = len(data["pesquisa_gemini"].get("resultados", []))
        logger.info("Gemini: %d resultados → %s", n, output_path)
        print("METRICS_JSON: " + json.dumps({"resultados_count": n, "retries": 0}))

    except Exception as e:
        _write_error(args.output, args.client_id, client_profile.get("niche", ""), str(e))
        logger.error("Gemini falhou: %s. Research continua sem esta fonte.", e)
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))


def _write_error(output: str, client_id: str, niche: str, erro: str) -> None:
    data = {
        "pesquisa_gemini": {
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
