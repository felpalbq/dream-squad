#!/usr/bin/env python3
"""
Dream Squad — Engagement Scoring
Cálculo determinístico de velocidade de engajamento por post.
Deduplicação semântica é responsabilidade do sub-agente LLM no Scoring/Merge.
"""

# Re-exporta de agents.utils.engagement para backward compatibilidade.
# O código novo deve importar diretamente de agents.utils.engagement.
from agents.utils.engagement import score_post, score_from_dict, rank_posts  # noqa: F401


if __name__ == "__main__":
    import json, sys
    from agents.utils.engagement import rank_posts as _rank_posts
    sample = [
        {"curtidas": 1243, "comentarios": 87, "data_postagem": "2025-01-14T19:30:00"},
        {"curtidas": 3102, "comentarios": 201, "data_postagem": "2025-01-13T12:00:00"},
    ]
    ranked = _rank_posts(sample, "instagram")
    json.dump(ranked, sys.stdout, ensure_ascii=False, indent=2)
