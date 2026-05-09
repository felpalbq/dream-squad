#!/usr/bin/env python3
"""
Dream Squad — Manual Input Loader
Lê manual_input.yaml do diretório do cliente e copia para exec_dir.
Se arquivo ausente ou vazio, pula silenciosamente.
O operador edita manual_input.yaml antes de rodar quando há eventos relevantes.
"""

import sys
import json
import yaml
import argparse
from datetime import date, datetime
from pathlib import Path

from agents.utils.paths import client_dir
from agents.utils.logging_config import get_logger

logger = get_logger(__name__)

MANUAL_INPUT_TEMPLATE = """\
# manual_input.yaml — Edite antes de executar quando houver eventos relevantes.
# Deixe resultados: [] se não houver nada a adicionar.
# O campo valido_ate (opcional) define até quando esta entrada é válida.
# Entradas expiradas são ignoradas automaticamente.

resultados:
  - tema: "Nome curto do tema"
    titulo: "Descrição do evento ou contexto"
    descricao: >
      Contexto detalhado: o que aconteceu, por que é relevante para o nicho,
      qual a conexão com o público-alvo.
    url_fonte: ""          # opcional
    data_hora: "YYYY-MM-DD"
    relevancia_nicho: 8    # 0-10
    origem: "manual"
    # valido_ate: "YYYY-MM-DD"   # opcional — deixe comentado para sem expiração
"""


def _is_expired(entry: dict) -> bool:
    valido_ate = entry.get("valido_ate")
    if not valido_ate:
        return False
    try:
        expiry = date.fromisoformat(str(valido_ate))
        return date.today() > expiry
    except (ValueError, TypeError):
        return False


def _is_template(entry: dict) -> bool:
    return entry.get("tema", "") == "Nome curto do tema"


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Manual Input Loader")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manual_path = client_dir(args.client_id) / "manual_input.yaml"

    if not manual_path.exists():
        with open(manual_path, "w", encoding="utf-8") as f:
            f.write(MANUAL_INPUT_TEMPLATE)
        logger.info("manual_input.yaml criado como template em %s", manual_path)

    try:
        with open(manual_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Falha ao ler manual_input.yaml: %s. Fonte pulada.", e)
        _write_empty(args.output, args.client_id)
        print("METRICS_JSON: " + json.dumps({"resultados_count": 0, "retries": 0}))
        sys.exit(0)

    resultados = raw.get("resultados", []) or []
    before = len(resultados)

    # Filtrar template não preenchido e entradas expiradas
    resultados = [
        r for r in resultados
        if not _is_template(r) and not _is_expired(r)
    ]

    skipped = before - len(resultados)
    if skipped:
        logger.info("Manual input: %d entrada(s) ignorada(s) (template ou expirada)", skipped)

    for r in resultados:
        r["origem"] = "manual"
        r.pop("valido_ate", None)  # não propagar campo de controle para o YAML de output

    data = {
        "manual_research": {
            "client_id": args.client_id,
            "data_pesquisa": datetime.now().isoformat(),
            "resultados": resultados,
        }
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    n = len(resultados)
    logger.info("Manual input: %d entradas → %s", n, output_path)
    print("METRICS_JSON: " + json.dumps({"resultados_count": n, "retries": 0}))


def _write_empty(output: str, client_id: str) -> None:
    data = {
        "manual_research": {
            "client_id": client_id,
            "data_pesquisa": datetime.now().isoformat(),
            "resultados": [],
        }
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


if __name__ == "__main__":
    main()
