#!/usr/bin/env python3
"""
Dream Squad — Engagement Scoring + Embedding Deduplication
Scoring: cálculo determinístico de velocidade de engajamento.
Dedup: deduplicação semântica via embeddings Ollama (ambiente Ollama).
Ambos são determinísticos e auditáveis — sem LLM.
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
    try:
        posted_at = datetime.fromisoformat(str(posted_raw))
    except (ValueError, TypeError):
        posted_at = datetime.now()

    return score_post(likes, comments, posted_at, platform, shares, views)


def rank_posts(posts: list[dict], platform: str) -> list[dict]:
    """Retorna posts ordenados por score decrescente."""
    for p in posts:
        p["engagement_score"] = score_from_dict(p, platform)
    return sorted(posts, key=lambda x: x["engagement_score"], reverse=True)


def _cosine_sim(a: list, b: list) -> float:
    """Embeddings Ollama são L2-normalizados — similaridade de cosseno = produto escalar."""
    return sum(x * y for x, y in zip(a, b))


def embed_and_deduplicate(
    pautas: list[dict],
    api_base: str = "http://localhost:11434",
    api_key: str = "",
    model: str = "qwen3-embedding",
    threshold: float = 0.85,
) -> list[dict]:
    """
    Deduplicação semântica via embeddings Ollama.
    Pautas com similaridade de cosseno >= threshold são mescladas em uma entrada,
    mantendo a de maior score e acumulando fontes confirmadoras.
    """
    from ollama import Client

    if not pautas:
        return pautas

    if api_key:
        client = Client(host=api_base, headers={"Authorization": f"Bearer {api_key}"})
    else:
        client = Client(host=api_base)

    texts = [
        f"{p.get('pauta', p.get('tema', ''))} {p.get('descricao', '')}".strip()
        for p in pautas
    ]

    response = client.embed(model=model, input=texts)
    embeddings = response["embeddings"]

    merged: list[dict] = []
    skip: set[int] = set()

    for i, pauta_i in enumerate(pautas):
        if i in skip:
            continue

        group = [pauta_i]
        for j in range(i + 1, len(pautas)):
            if j in skip:
                continue
            if _cosine_sim(embeddings[i], embeddings[j]) >= threshold:
                group.append(pautas[j])
                skip.add(j)

        if len(group) > 1:
            base = max(
                group,
                key=lambda p: (
                    p.get("relevancia", 0) + p.get("potencial_alcance", 0)
                    + p.get("potencial_engajamento", 0) + p.get("rate_timing", 0)
                ),
            )
            merged_entry = dict(base)
            merged_entry["fontes_confirmadoras"] = list(
                {p.get("fonte", "") for p in group if p.get("fonte")}
            )
            merged_entry["deduplicado"] = True
            merged.append(merged_entry)
        else:
            merged.append(pauta_i)

    return merged


if __name__ == "__main__":
    import json, sys
    sample = [
        {"curtidas": 1243, "comentarios": 87, "data_postagem": "2025-01-14T19:30:00"},
        {"curtidas": 3102, "comentarios": 201, "data_postagem": "2025-01-13T12:00:00"},
    ]
    ranked = rank_posts(sample, "instagram")
    json.dump(ranked, sys.stdout, ensure_ascii=False, indent=2)
