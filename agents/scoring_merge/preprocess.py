#!/usr/bin/env python3
"""Pré-clustering determinístico de pautas antes do Scoring/Merge LLM."""

import sys
import yaml
import re
import unicodedata
import argparse
from pathlib import Path
from datetime import datetime

# Stopwords simples em português
_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "um", "uma",
    "para", "por", "com", "sem", "no", "na", "nos", "nas", "que", "se", "ao", "aos",
}


def _normalize(text: str) -> set[str]:
    """Normaliza texto: lowercase, sem acentos, sem pontuação, sem stopwords."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    tokens = {t for t in text.split() if t and t not in _STOPWORDS and len(t) > 2}
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    """Similaridade Jaccard entre dois conjuntos."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def load_candidates(exec_dir: Path) -> list[dict]:
    """Carrega todos os resultados de pesquisa do diretório de execução."""
    candidates = []
    research_dir = exec_dir / "research"
    if not research_dir.exists():
        return candidates

    files = [
        ("gemini_research.yaml", "pesquisa_gemini"),
        ("tavily_research.yaml", "pesquisa_tavily"),
        ("ollama_research.yaml", "pesquisa_ollama_regional"),
        ("apify_research.yaml", "pesquisa_apify"),
        ("manual_research.yaml", "manual_research"),
    ]

    for fname, key in files:
        path = research_dir / fname
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            container = data.get(key, {})
            for r in container.get("resultados", []):
                if not isinstance(r, dict):
                    continue
                candidates.append({
                    "origem": r.get("origem", "unknown"),
                    "tema": r.get("tema", ""),
                    "titulo": r.get("titulo", ""),
                    "descricao": r.get("descricao", ""),
                    "url_fonte": r.get("url_fonte", ""),
                    "data_hora": r.get("data_hora", ""),
                    "relevancia_nicho": r.get("relevancia_nicho"),
                    "engagement_score": r.get("engagement_score"),
                    "sinal_friccao": r.get("sinal_friccao"),
                    "sinal_transformacao": r.get("sinal_transformacao"),
                    "sinal_timing": r.get("sinal_timing"),
                    "prioridade_operador": r.get("prioridade_operador"),
                })
        except Exception:
            continue
    return candidates


def cluster_candidates(candidates: list[dict], threshold: float = 0.5) -> list[list[int]]:
    """Agrupa candidatos por similaridade Jaccard ≥ threshold."""
    n = len(candidates)
    if n == 0:
        return []

    tokens = [
        _normalize(c["tema"] + " " + c["titulo"])
        for c in candidates
    ]

    visited = [False] * n
    clusters: list[list[int]] = []

    for i in range(n):
        if visited[i]:
            continue
        cluster = [i]
        visited[i] = True
        for j in range(i + 1, n):
            if visited[j]:
                continue
            sim = _jaccard(tokens[i], tokens[j])
            if sim >= threshold:
                cluster.append(j)
                visited[j] = True
        clusters.append(cluster)

    return clusters


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Pré-clustering de pautas")
    parser.add_argument("--exec-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    exec_dir = Path(args.exec_dir)
    candidates = load_candidates(exec_dir)
    clusters = cluster_candidates(candidates, threshold=args.threshold)

    data = {
        "preprocess": {
            "timestamp": datetime.now().isoformat(),
            "threshold": args.threshold,
            "total_candidates": len(candidates),
            "total_clusters": len(clusters),
            "clusters": [
                {
                    "indices": cluster,
                    "items": [candidates[i] for i in cluster],
                }
                for cluster in clusters
            ],
        }
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    print(f"Clusters: {len(clusters)} de {len(candidates)} candidatos → {output_path}")


if __name__ == "__main__":
    main()
