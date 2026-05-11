#!/usr/bin/env python3
"""Cálculo determinístico de velocidade de engajamento por post.

Este módulo foi extraído de agents/scoring_merge/score.py para evitar
dependência circular com agents/apify_collector/collect.py.
"""

from datetime import datetime


def score_post(
    likes: int,
    comments: int,
    posted_at: datetime,
    platform: str,
    shares: int = 0,
    views: int = 0,
) -> float:
    """
    Velocidade de engajamento = engajamento total / horas desde publicação.
    - Comentário vale 3× (gerou conversa)
    - Share vale 5× (amplificação ativa)
    - Views entram com peso 0.1 (passivos)
    """
    hours = max((datetime.now() - posted_at).total_seconds() / 3600, 1.0)

    if platform == "instagram":
        engagement = likes + comments * 3
    elif platform == "twitter":
        engagement = likes + comments * 3 + shares * 5 + views * 0.1
    else:
        engagement = likes + comments * 3

    return round(engagement / hours, 2)


def score_from_dict(post: dict, platform: str) -> float:
    """Calcula score a partir de um dict de post extraído."""
    likes = int(post.get("curtidas", post.get("likes", 0)) or 0)
    comments = int(post.get("comentarios", post.get("comments", 0)) or 0)
    shares = int(post.get("shares", post.get("compartilhamentos", 0)) or 0)
    views = int(post.get("views", post.get("visualizacoes", 0)) or 0)

    posted_raw = post.get("data_postagem", post.get("data_post", ""))
    if not posted_raw:
        # Sem data = score de velocidade inválido; usar contagem absoluta
        return round((likes + comments * 3 + shares * 5) / 1000, 2)

    try:
        posted_at = datetime.fromisoformat(str(posted_raw))
    except (ValueError, TypeError):
        return round((likes + comments * 3 + shares * 5) / 1000, 2)

    return score_post(likes, comments, posted_at, platform, shares, views)


def rank_posts(posts: list[dict], platform: str) -> list[dict]:
    """Retorna posts ordenados por score decrescente (input imutável)."""
    enriched = [
        {**p, "engagement_score": score_from_dict(p, platform)}
        for p in posts
    ]
    return sorted(enriched, key=lambda x: x["engagement_score"], reverse=True)
