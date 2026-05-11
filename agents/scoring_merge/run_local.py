#!/usr/bin/env python3
"""Scoring/Merge local — fallback quando o Claude Code sub-agente não está disponível.

Este script executa o merge determinístico das fontes de pesquisa via LLM local
(Ollama API via requests direto), produzindo final_research.md sem depender
do sub-agente nativo do Claude Code.

Uso:
    python agents/scoring_merge/run_local.py --client-id casadobicho --exec-dir clients/casadobicho/executions/YYYY-MM-DD_HHMMSS
"""

import os
import re
import sys
import json
import yaml
import argparse
import requests
from datetime import datetime
from pathlib import Path

from agents.utils.paths import load_profile
from agents.utils.logging_config import get_logger
from agents.utils.seasonality import seasonal_context
from agents.utils.text_utils import strip_fences

logger = get_logger(__name__)
ROOT = Path(__file__).parent.parent.parent
_OLLAMA_TIMEOUT = 180

_MERGE_PROMPT = """\
Você é o Agente de Scoring e Merge do sistema Dream Squad.
Consolide os resultados de pesquisa abaixo em um documento final de research estruturado.

PERFIL DO CLIENTE:
- Nome: {name}
- Nicho: {niche}
- Público-alvo: {audience}
- Tom de voz: {voice}
- O que evitar: {avoid}

RESULTADOS DAS FONTES:
{sources}

TAREFA:
1. Leia todos os resultados das fontes.
2. Deduplique semanticamente: pautas sobre o mesmo tema viram uma só.
3. Enriqueça com evidências cruzadas: se duas fontes confirmam o mesmo tema, a pauta fica mais forte.
4. Classifique cada pauta por relevância (0-10), alcance (0-10), engajamento (0-10) e timing (0-10).
5. Selecione a pauta principal + 2 alternativas (as 3 mais fortes, com balanceamento de funil).
6. Aplique os filtros de voice.avoid — descarte pautas que violem.

Produza o output em Markdown estruturado exatamente neste formato:

```markdown
# Research — {name} — {date}

## Cliente
- **Nicho:** {nicho}
- **Persona:** {handle}
- **Público-alvo:** {audience}
- **Tom de voz:** {tone}

---

## Pauta Principal

### Tema
{{tema em uma linha}}

### Pauta
{{descrição completa da oportunidade — 3-5 linhas}}

### Ângulos
- Ângulo 1
- Ângulo 2
- Ângulo 3

### Abordagens Possíveis
- Abordagem 1
- Abordagem 2

### Transformação
{{o que está mudando — omitir se não identificado}}

### Fricção Central
{{a tensão que gera engajamento — omitir se não identificado}}

### Evidências Disponíveis
- Evidência 1 (fonte, dado)
- Evidência 2

### Evidências a Pesquisar na Estratégia
- O que ainda precisa ser verificado

### Fontes e URLs
- [Título](url)

### Por que Funciona
{{raciocínio completo: timing, conexão com nicho, potencial emocional}}

### Potencial
- Relevância: X/10
- Alcance: X/10
- Engajamento: X/10
- Timing: X/10
- **Score total: X.X/10**

### Fontes Confirmadoras
- gemini (via [título](url))
- tavily (via [título](url))

### Classificação Editorial
- **Eixo narrativo:** {{Mercado | Cases | Notícias | Cultura | Produto}}
- **Etapa do funil:** {{Topo | Meio | Fundo}}
- **Padrão de hook potencial:** {{padrão identificado}}
- **Gatilhos emocionais:** {{lista}}

### Valor Real
{{o que o público ganha consumindo este conteúdo}}

---

## Pautas Alternativas

### Pauta 2 — {{Tema}}
**Pauta:** {{descrição}}
**Por que funciona:** {{raciocínio}}
**Potencial:** Relevância X/10 · Alcance X/10 · Engajamento X/10 · Timing X/10 · Score X.X/10
**Fontes confirmadoras:** {{lista}}
**Classificação:** Eixo {{X}} · Funil {{X}}

---

### Pauta 3 — {{Tema}}
{{mesmo formato resumido}}

---

## Pautas Descartadas por Filtro
- "Tema X" — motivo: viola voice.avoid

---

## Log de Fontes
| Fonte | Status | Resultados brutos |
|---|---|---|
| Gemini API | {status} | {n} |
| Tavily | {status} | {n} |
| Ollama Regional | {status} | {n} |
| Apify | {status} | {n} |
| Manual Input | {status} | {n} |
| **Total após merge** | — | {n} pautas únicas |
```

IMPORTANTE:
- Não invente dados, fontes ou métricas não presentes nos inputs.
- Não inclua pautas com score total < 5.5.
- Não omita o campo "Fontes Confirmadoras".
"""


def _load_sources(exec_dir: Path) -> tuple[list[dict], dict]:
    """Carrega todas as fontes de pesquisa disponíveis."""
    research_dir = exec_dir / "research"
    sources = []
    log = {}

    files = [
        ("gemini_research.yaml", "pesquisa_gemini", "Gemini API"),
        ("tavily_research.yaml", "pesquisa_tavily", "Tavily"),
        ("ollama_research.yaml", "pesquisa_ollama_regional", "Ollama Regional"),
        ("apify_research.yaml", "pesquisa_apify", "Apify"),
        ("manual_research.yaml", "manual_research", "Manual Input"),
    ]

    for fname, key, label in files:
        path = research_dir / fname
        if not path.exists():
            log[label] = {"status": "N/A", "count": 0}
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            container = data.get(key, {})
            resultados = container.get("resultados", [])
            log[label] = {"status": "sucesso" if resultados else "vazio", "count": len(resultados)}
            if resultados:
                sources.append({"fonte": label, "resultados": resultados})
        except Exception as e:
            log[label] = {"status": f"falha: {e}", "count": 0}

    return sources, log


def _format_sources(sources: list[dict]) -> str:
    lines = []
    for src in sources:
        lines.append(f"\n=== FONTE: {src['fonte']} ===")
        for r in src["resultados"]:
            lines.append(f"- tema: {r.get('tema', '')}")
            lines.append(f"  titulo: {r.get('titulo', '')}")
            lines.append(f"  descricao: {r.get('descricao', '')[:200]}")
            lines.append(f"  url_fonte: {r.get('url_fonte', '')}")
            lines.append(f"  relevancia_nicho: {r.get('relevancia_nicho', 'N/A')}")
            lines.append(f"  origem: {r.get('origem', '')}")
            lines.append("")
    return "\n".join(lines)


def _ollama_chat(api_base: str, api_key: str, model: str, prompt: str) -> str:
    url = f"{api_base.rstrip('/')}/api/chat"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.3, "num_ctx": 8192},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=_OLLAMA_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("message", {}).get("content", "")


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Scoring/Merge Local")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--exec-dir", required=True)
    parser.add_argument("--model", default=None, help="Modelo Ollama para síntese")
    args = parser.parse_args()

    exec_dir = Path(args.exec_dir)
    if not exec_dir.exists():
        print(f"[ERRO] Diretório de execução não existe: {exec_dir}", file=sys.stderr)
        sys.exit(1)

    client_profile = load_profile(args.client_id)
    sources, log = _load_sources(exec_dir)

    if not sources:
        print("[ERRO] Nenhuma fonte de pesquisa disponível.", file=sys.stderr)
        sys.exit(1)

    name = client_profile.get("name", args.client_id)
    niche = client_profile.get("niche", "não especificado")
    audience = client_profile.get("audience", {}).get("description", "público geral")
    voice = ", ".join(client_profile.get("voice", {}).get("tone", []))
    avoid = ", ".join(client_profile.get("voice", {}).get("avoid", []))
    handle = client_profile.get("persona", {}).get("instagram_handle", "")
    date_str = datetime.now().strftime("%Y-%m-%d")

    prompt = _MERGE_PROMPT.format(
        name=name,
        niche=niche,
        audience=audience,
        voice=voice,
        avoid=avoid,
        sources=_format_sources(sources),
        handle=handle,
        date=date_str,
    )

    api_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    model = args.model or os.environ.get("OLLAMA_MODEL", "kimi-k2.6:cloud")

    if not api_key:
        print("[ERRO] OLLAMA_API_KEY não configurada. Scoring/Merge local requer LLM.", file=sys.stderr)
        sys.exit(1)

    print(f"[Scoring/Merge Local] Sintetizando com {model}...")
    try:
        raw = _ollama_chat(api_base, api_key, model, prompt)
        content = strip_fences(raw)

        output_path = exec_dir / "research" / "final_research.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Log
        log_lines = [f"| {k} | {v['status']} | {v['count']} |" for k, v in log.items()]
        log_table = "\n".join([
            "## Log de Fontes",
            "",
            "| Fonte | Status | Resultados brutos |",
            "|---|---|---|",
            *log_lines,
            f"| **Total após merge** | — | {len(sources)} fontes |",
        ])

        # Append log se não estiver presente
        if "Log de Fontes" not in content:
            with open(output_path, "a", encoding="utf-8") as f:
                f.write("\n\n---\n\n" + log_table)

        print(f"[Scoring/Merge Local] OK → {output_path}")

    except Exception as e:
        print(f"[ERRO] Scoring/Merge local falhou: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
