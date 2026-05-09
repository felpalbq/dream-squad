#!/usr/bin/env python3
"""
Dream Squad — Pré-processamento para Scoring/Merge
Deduplicação semântica via embeddings Ollama antes da análise LLM.
Executado apenas no ambiente Ollama, entre Visual Analyzer e Scoring/Merge.
"""

import os
import sys
import yaml
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.scoring_merge.score import embed_and_deduplicate


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Preprocess (embedding dedup)")
    parser.add_argument("--visual", required=True, help="Path do visual_analysis.yaml")
    parser.add_argument("--output", required=True, help="Path do yaml deduplicado de saída")
    parser.add_argument("--threshold", type=float, default=0.85, help="Limiar de similaridade (default: 0.85)")
    args = parser.parse_args()

    api_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    embed_model = os.environ.get("OLLAMA_EMBEDDING_MODEL", "qwen3-embedding")

    with open(args.visual, encoding="utf-8") as f:
        visual_data = yaml.safe_load(f)

    pautas = visual_data.get("analise_visual", {}).get("pautas_identificadas", [])
    print(f"[preprocess] {len(pautas)} pautas recebidas para deduplicação", file=sys.stderr)

    try:
        deduped = embed_and_deduplicate(
            pautas=pautas,
            api_base=api_base,
            api_key=api_key,
            model=embed_model,
            threshold=args.threshold,
        )
    except Exception as e:
        print(f"[AVISO] Embedding dedup falhou ({e}). Usando pautas originais.", file=sys.stderr)
        deduped = pautas

    removed = len(pautas) - len(deduped)
    print(f"[preprocess] {len(deduped)} pautas únicas ({removed} duplicatas removidas)", file=sys.stderr)

    output_data = dict(visual_data)
    output_data["analise_visual"] = dict(visual_data.get("analise_visual", {}))
    output_data["analise_visual"]["pautas_identificadas"] = deduped
    output_data["analise_visual"]["deduplicacao_aplicada"] = True
    output_data["analise_visual"]["pautas_originais"] = len(pautas)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, allow_unicode=True, default_flow_style=False)

    print(f"[preprocess] saída → {out_path}")


if __name__ == "__main__":
    main()
