"""Contexto sazonal unificado para todos os agentes de pesquisa."""

from datetime import datetime


def seasonal_context(dt: datetime | None = None) -> str:
    """Retorna o período sazonal atual baseado na data."""
    dt = dt or datetime.now()
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
        # Janela normal (ex: 25 abr → 14 mai)
        if start <= end:
            if start <= current <= end:
                return label
        else:
            # Wrap-around: janela cruza virada de ano (ex: 10 dez → 10 jan).
            # Ativa se current está depois do start (dez) OU antes do end (jan).
            if current >= start or current <= end:
                return label
    month_labels = {
        1: "início de ano", 2: "verão/carnaval", 3: "outono chegando",
        4: "outono/Páscoa", 5: "Dia das Mães", 6: "Dia dos Namorados",
        7: "férias de julho", 8: "Dia dos Pais/inverno", 9: "primavera",
        10: "Dia das Crianças", 11: "Black Friday", 12: "Natal/fim de ano",
    }
    return month_labels.get(m, "período sem sazonalidade específica")
