#!/usr/bin/env python3
"""Atualiza o cooldown de pautas com base no final_research.md.

Este script deve ser executado APÓS o Scoring/Merge terminar.
Ele extrai apenas os temas das pautas selecionadas no final_research.md
(e não de todos os YAMLs brutos), evitando saturação do used_topics.json.

Uso:
    python agents/orchestrator/update_cooldown.py --client-id casadobicho --exec-dir clients/casadobicho/executions/YYYY-MM-DD_HHMMSS
"""

import re
import json
import argparse
import unicodedata
from pathlib import Path
from datetime import date, timedelta

from agents.utils.paths import client_dir


def _load_used_topics(client_id: str) -> list[dict]:
    path = client_dir(client_id) / "research" / "used_topics.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _cleanup_used_topics(topics: list[dict]) -> list[dict]:
    """Remove entradas com mais de 14 dias."""
    cutoff = date.today() - timedelta(days=14)
    cleaned = []
    for t in topics:
        try:
            d = date.fromisoformat(t.get("data_uso", ""))
            if d >= cutoff:
                cleaned.append(t)
        except (ValueError, TypeError):
            continue
    return cleaned


def _save_used_topics(client_id: str, topics: list[dict]) -> None:
    path = client_dir(client_id) / "research" / "used_topics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topics, f, ensure_ascii=False, indent=2)


def _normalize_tema(tema: str) -> str:
    normalizado = (
        unicodedata.normalize("NFD", tema.lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    normalizado = " ".join(
        w for w in re.sub(r"[^\w\s]", " ", normalizado).split()
        if len(w) > 2
    )
    return normalizado


def _extract_temas_from_final_research(final_path: Path) -> list[str]:
    """Extrai temas do final_research.md via regex simples."""
    if not final_path.exists():
        return []
    text = final_path.read_text(encoding="utf-8")
    temas = []
    # Padrões comuns no final_research.md
    # "### Tema\n{tema em uma linha}"
    for match in re.finditer(r"### Tema\s*\n([^\n]+)", text):
        tema = match.group(1).strip()
        if tema:
            temas.append(tema)
    # Também capturar "**Tema:** {tema}" ou similar
    for match in re.finditer(r"\*\*Tema:\*\*\s*([^\n]+)", text):
        tema = match.group(1).strip()
        if tema and tema not in temas:
            temas.append(tema)
    return temas


def main():
    parser = argparse.ArgumentParser(description="Atualiza cooldown de pautas a partir do final_research.md")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--exec-dir", required=True, help="Diretório de execução contendo research/final_research.md")
    args = parser.parse_args()

    exec_dir = Path(args.exec_dir)
    final_path = exec_dir / "research" / "final_research.md"

    if not final_path.exists():
        print(f"[ERRO] {final_path} não encontrado. O Scoring/Merge já rodou?")
        return

    temas = _extract_temas_from_final_research(final_path)
    if not temas:
        print("[AVISO] Nenhum tema extraído de final_research.md. Nada a atualizar.")
        return

    used_topics = _load_used_topics(args.client_id)
    used_topics = _cleanup_used_topics(used_topics)

    seen = {t.get("tema_normalizado", "") for t in used_topics}
    today = date.today().isoformat()

    for tema in temas:
        normalizado = _normalize_tema(tema)
        if not normalizado or normalizado in seen:
            continue
        seen.add(normalizado)
        used_topics.append({
            "tema": tema,
            "tema_normalizado": normalizado,
            "data_uso": today,
            "execution_dir": str(exec_dir),
        })

    _save_used_topics(args.client_id, used_topics)
    print(f"Cooldown atualizado: {len(temas)} tema(s) extraído(s) de final_research.md -> {len(used_topics)} total no histórico.")


if __name__ == "__main__":
    main()
