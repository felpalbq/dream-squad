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
from agents.utils.query_rotation import select_gemini_focus
from agents.utils.seasonality import seasonal_context
from agents.utils.text_utils import strip_fences

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

FOQUE ESPECIALMENTE NESTES EIXOS ESTA SEMANA:
{focus_areas}

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
- Quando aplicável, adicione sinal_friccao (tensão/polarização identificada) ou sinal_transformacao (mudança de comportamento clara)

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
      sinal_friccao: ""          # preencher quando houver tensão/polarização
      sinal_transformacao: ""    # preencher quando houver mudança de comportamento clara
"""




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

    foci = select_gemini_focus(n=2, client_id=args.client_id)
    focus_lines = "\n".join(f"{i+1}. {desc}" for i, (_, desc) in enumerate(foci))

    extra = client_profile.get("research", {}).get("gemini_context", "nenhum")
    pulse = os.environ.get("DREAM_SQUAD_PULSE", "")
    if pulse:
        extra = f"{extra}\n\nPULSE DO OPERADOR (contexto agudo desta execução):\n{pulse}"

    prompt = _PROMPT_TEMPLATE.format(
        client_id=args.client_id,
        niche=client_profile.get("niche", ""),
        audience=client_profile.get("audience", {}).get("description", "público geral"),
        location=client_profile.get("location", "Brasil"),
        date=now.strftime("%Y-%m-%d"),
        seasonal=seasonal_context(now),
        extra_context=extra,
        focus_areas=focus_lines,
    )

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    client = genai.Client(api_key=api_key)

    retries = []

    @with_retry(max_attempts=3, base_delay=2.0, label="Gemini API")
    def _call_gemini(retries):
        response = client.models.generate_content(model=model_name, contents=prompt)
        return response.text

    try:
        raw_text = _call_gemini(retries)
        raw = strip_fences(raw_text)
        data = yaml.safe_load(raw)

        if not isinstance(data, dict) or "pesquisa_gemini" not in data:
            raise ValueError("Resposta Gemini não contém 'pesquisa_gemini'")

        for r in data["pesquisa_gemini"].get("resultados", []):
            r.setdefault("origem", "gemini")

        try:
            validate_yaml_output(data["pesquisa_gemini"], PesquisaGemini, "gemini")
        except ValueError as e:
            actual_retries = retries[0] if retries else 0
            _write_error(args.output, args.client_id, client_profile.get("niche", ""), str(e))
            logger.error("Gemini: schema inválido: %s. Research continua sem esta fonte.", e)
            print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": actual_retries}))
            sys.exit(0)

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        actual_retries = retries[0] if retries else 0
        n = len(data["pesquisa_gemini"].get("resultados", []))
        logger.info("Gemini: %d resultados → %s", n, output_path)
        print("METRICS_JSON: " + json.dumps({"resultados_count": n, "retries": actual_retries}))

    except Exception as e:
        actual_retries = retries[0] if retries else 0
        _write_error(args.output, args.client_id, client_profile.get("niche", ""), str(e))
        logger.error("Gemini falhou: %s. Research continua sem esta fonte.", e)
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": actual_retries}))


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
