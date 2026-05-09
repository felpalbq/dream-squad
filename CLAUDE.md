# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## O que é o Dream Squad

Sistema multi-agentes rodando dentro do Claude Code CLI. Automatiza a produção de conteúdo estratégico (carrosséis, roteiros de reels/stories/b-rolls) para pequenas empresas de Ilhéus/Itabuna (BA) sem verba para tráfego pago. O operador é o estrategista/gestor; os clientes recebem o conteúdo via board Trello atualizado 2×/semana.

**Stack:** Python · Playwright (Chrome do operador) · Gemini API (pesquisa nacional) · Ollama Python SDK (visão multimodal + web search regional + embeddings) · Trello (publicação) · Claude Code CLI (todos os agentes LLM)

---

## Instalação

```bash
python -m pip install -r requirements.txt
playwright install chromium
```

Copie `.env.example` para `.env` e preencha todas as variáveis.

## Como Executar o Research

O operador invoca o sistema em linguagem natural. O Claude Code (orquestrador) segue o fluxo abaixo.

### Passo 1 — Etapas Python (coleta + pesquisa)

```bash
python agents/orchestrator/run.py --client-id casadobicho
```

Cria diretório de execução com timestamp, roda Playwright Collector (Instagram + Twitter), Gemini Researcher e — no ambiente Ollama — o Ollama Regional Researcher. Imprime ao final as instruções exatas para o Claude Code continuar.

Flags opcionais: `--source instagram|twitter|all` · `--skip-gemini` · `--skip-ollama-research` · `--skip-collect --exec-dir <path>`

### Passo 2 — Análise Visual

**Ambiente Anthropic:** o Claude Code lê `agents/visual_analyzer/instructions.md`, analisa os screenshots como sub-agente multimodal, e grava `visual_analysis.yaml` no diretório de execução.

**Ambiente Ollama:**
```bash
python agents/visual_analyzer/analyze_ollama.py \
  --client-id casadobicho \
  --collection-yaml clients/casadobicho/executions/{ts}/collection.yaml \
  --output clients/casadobicho/executions/{ts}/research/visual_analysis.yaml
```

### Passo 3 — Pré-processamento (apenas ambiente Ollama)

Deduplicação semântica via embeddings antes do merge LLM:
```bash
python agents/scoring_merge/preprocess.py \
  --visual clients/casadobicho/executions/{ts}/research/visual_analysis.yaml \
  --output clients/casadobicho/executions/{ts}/research/deduplicated_visual_analysis.yaml
```

### Passo 4 — Scoring e Merge

O Claude Code lê `agents/scoring_merge/instructions.md` e consolida:
- `deduplicated_visual_analysis.yaml` (Ollama) ou `visual_analysis.yaml` (Anthropic)
- `gemini_research.yaml`
- `ollama_research.yaml` (apenas ambiente Ollama, se existir)
- `profile.yaml` do cliente

Produz: `clients/{client_id}/executions/{ts}/research/final_research.md`

---

## Variáveis de Ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GEMINI_API_KEY` | Sim | Google Gemini API — deep research nacional |
| `CHROME_PROFILE_PATH` | Sim | Caminho absoluto ao perfil Chrome do operador |
| `CHROME_EXECUTABLE_PATH` | Sim | Caminho ao executável do Google Chrome |
| `DREAM_SQUAD_ENV` | Não | `anthropic` ou `ollama`. Se ausente, solicita confirmação manual |
| `OLLAMA_API_BASE` | Se Ollama | URL base do servidor Ollama (ex: `https://ollama.com`) |
| `OLLAMA_API_KEY` | Se Ollama | API key do servidor Ollama cloud |
| `OLLAMA_MODEL` | Não | Modelo para visão/análise. Default: `kimi-k2.6:cloud` |
| `OLLAMA_RESEARCHER_MODEL` | Não | Modelo para pesquisa regional. Default: `kimi-k2.6:cloud` |
| `OLLAMA_EMBEDDING_MODEL` | Não | Modelo para embeddings/dedup. Default: `qwen3-embedding` |
| `COST_ALERT_THRESHOLD` | Não | Custo estimado máximo (USD) por execução. Default: 0.50 |

O Chrome **deve estar fechado** antes de qualquer execução.

---

## Modos de Execução

| Modo | Trigger do operador | Agentes acionados |
|---|---|---|
| Completo semanal | "Conteúdo completo da semana para [cliente]" | Research → Estratégia → Copy → Produção → Publish |
| Carrossel único | "1 carrossel sobre [tema] para [cliente]" | Research → Estratégia → Copy → Produção → Publish |
| Roteiros completos | "Roteiros da semana para [cliente]" | Research → Estratégia → Copy → Produção → Publish |
| Roteiro único | "1 roteiro de [formato] sobre [tema] para [cliente]" | Research → Estratégia → Copy → Produção → Publish |

**Etapa atual:** apenas Research está implementado. As demais etapas serão implementadas em sequência.

---

## Arquitetura de Agentes (Etapa 1 — Research)

Todos os agentes LLM são sub-agentes nativos do Claude Code (Task tool). Nunca processos externos. As exceções são: Gemini API (pesquisa via Python direto), Ollama Python SDK (visão + web search + embeddings via Python direto).

### Fluxo do Research

```
[Solicitação do operador]
        ↓
[Orquestrador] — identifica cliente, modo, servidor ativo
        ↓
[Playwright Collector] — Instagram e Twitter/X serialmente
        ↓
[Gemini Researcher] — deep research nacional por nicho (API Python)
        ↓
[Ollama Regional Researcher] — notícias locais via web_search (apenas ambiente Ollama)
        ↓
[Visual Analyzer] — análise multimodal de todos os screenshots (batch)
        ↓
[Preprocess] — deduplicação semântica via embeddings (apenas ambiente Ollama)
        ↓
[Scoring/Merge] — enriquecimento cruzado, rankeamento, seleção editorial
        ↓
[Output: final_research.md → etapa de Estratégia]
```

**Regras absolutas:**
- Playwright Instagram e Twitter são executados serialmente, nunca simultaneamente
- A falha de uma fonte não interrompe as demais
- A análise visual aguarda conclusão de todas as fontes Playwright (batch)
- Toda comunicação entre agentes é em YAML/JSON/MD estruturado

### Responsabilidades por Agente

**Orquestrador**
- Carrega `profile.yaml` do cliente
- Detecta servidor via `DREAM_SQUAD_ENV`
- Aciona sub-agentes na ordem correta
- Captura falhas sem propagar para os demais
- Exibe log de execução ao final (tempo por etapa, fontes coletadas, custo estimado)
- Emite alerta se custo estimado ultrapassar `COST_ALERT_THRESHOLD`

**Playwright Collector**
- Fontes: Instagram (perfis de referência do cliente) + Twitter/X (feed curado do operador)
- Abre Chrome com perfil do operador via `launch_persistent_context`
- Comportamento anti-detecção obrigatório: delays com distribuição normal, mouse em curva de Bézier, scroll gradual
- Instagram: screenshot do grid → LLM seleciona posts → screenshot dos posts (máx 8 por perfil)
- Twitter: scroll passivo com screenshots a cada ciclo, para ao atingir 30 posts ou 10 oportunidades
- Rate limits: Instagram ≤ 15 perfis/hora, sessão ≤ 45 min; Twitter ≤ 30 min/sessão
- Se bloqueio detectado (checkpoint/challenge/captcha/verify na URL): para sessão, registra log, notifica. Não contorna automaticamente

**Gemini Researcher**
- Chamada direta à API Python com `GEMINI_API_KEY`
- Input: nicho + data atual + período sazonal
- Foco: tendências nacionais/comportamentais, estudos, fontes verificáveis, conexões indiretas com o nicho
- Output: `gemini_research.yaml` com campo `pesquisa_gemini`

**Ollama Regional Researcher** *(apenas ambiente Ollama)*
- Substitui o Playwright Regional: busca notícias de Ilhéus/Itabuna via `ollama.web_search()`
- Executa 3 queries direcionadas (notícias locais, nicho na região, comportamento do consumidor local)
- Sintetiza resultados via `client.chat()` com o modelo configurado em `OLLAMA_RESEARCHER_MODEL`
- Output: `ollama_research.yaml` com campo `pesquisa_ollama_regional`
- Falha silenciosa: research continua sem esta fonte se a API falhar

**Visual Analyzer**
- **Ambiente Anthropic:** Claude Sonnet nativo via sub-agente (Task tool)
- **Ambiente Ollama:** Kimi K2.6 via `ollama.Client.chat()` com `think=True` — o raciocínio explícito é logado para auditoria editorial
- Analisa screenshots de Instagram e Twitter em 4 camadas: Transformação · Fricção Central · Ângulo Narrativo · Evidências
- Recebe obrigatoriamente: nicho, persona, público-alvo, data do cliente
- Pautas com score médio < 6 em todos os critérios: descartar ou marcar como baixa prioridade
- Não inventa métricas não visíveis — registrar 0 ou "não visível"

**Preprocess** *(apenas ambiente Ollama, após Visual Analyzer)*
- Deduplicação semântica das pautas via embeddings Ollama (`qwen3-embedding` por padrão)
- Embeddings são L2-normalizados — similaridade = produto escalar, sem dependências externas
- Pautas com similaridade ≥ 0.85 são mescladas: mantém a de maior score, acumula `fontes_confirmadoras`
- Resultado: `deduplicated_visual_analysis.yaml` com `deduplicacao_aplicada: true`
- Falha silenciosa: se embeddings falharem, usa `visual_analysis.yaml` original

**Scoring/Merge** (sub-agente dedicado via Task tool)
- Se receber `deduplicated_visual_analysis.yaml`: pula passo de deduplicação, foca em enriquecimento cruzado
- Enriquecimento cruzado: pauta visual + fonte Gemini ou Ollama Regional correspondente = pauta mais forte
- Bônus de confiança para pautas confirmadas por múltiplas fontes
- Rankeamento por potencial total (média ponderada dos scores)
- Balanceia eixos narrativos: carrossel de alcance (Cultura/Notícias, funil Topo) + carrossel de conversão (Cases/Produto, funil Fundo)
- Output: `final_research.md` no formato documentado em `build/03_research_agent_behavior.md`

---

## Estrutura de Diretórios

```
dream-squad/
├── CLAUDE.md
├── clients/
│   └── {client_id}/
│       ├── profile.yaml
│       └── executions/
│           └── {YYYY-MM-DD_HHMMSS}/
│               ├── collection.yaml
│               ├── session.yaml
│               ├── instagram/
│               │   ├── screenshots/
│               │   └── parsed/
│               ├── twitter/
│               │   ├── screenshots/
│               │   └── parsed/
│               └── research/
│                   ├── gemini_research.yaml
│                   ├── ollama_research.yaml          # apenas ambiente Ollama
│                   ├── visual_analysis.yaml
│                   ├── deduplicated_visual_analysis.yaml  # apenas ambiente Ollama
│                   └── final_research.md
├── agents/
│   ├── orchestrator/
│   │   └── run.py
│   ├── playwright_collector/
│   │   └── collect.py
│   ├── gemini_researcher/
│   │   └── research.py
│   ├── ollama_researcher/
│   │   └── research.py
│   ├── visual_analyzer/
│   │   ├── analyze_ollama.py
│   │   └── instructions.md
│   ├── scoring_merge/
│   │   ├── score.py
│   │   ├── preprocess.py
│   │   └── instructions.md
│   └── utils/
│       └── paths.py
├── config/
│   └── server_config.yaml
└── docs/
    ├── playwright_reference.md
    └── content_strategy.md
```

---

## Schema do profile.yaml

```yaml
client_id: "casadobicho"
name: "Casa di Bicho"
niche: "veterinária"
location: "Ilhéus, BA"
active: true

persona:
  instagram_handle: "@casadobicho"
  bio: "descrição curta do posicionamento"

audience:
  description: "tutores de pets, principalmente mulheres, 25-45 anos"
  location: "Ilhéus e Itabuna, BA"

voice:
  tone:
    - "próximo"
    - "educativo"
    - "afetivo"
  style: "linguagem acessível, sem jargão técnico"

instagram_reference_profiles:
  - url: "https://instagram.com/handle_referencia"
    handle: "@handle_referencia"
    relevance: "veterinária com alto engajamento"

research:
  posts_per_profile: 20
  top_posts_to_capture: 8
  twitter_scroll_posts: 30
```

---

## Contrato de Comunicação entre Agentes

| De → Para | Formato | Conteúdo |
|---|---|---|
| Orquestrador → Playwright | Args CLI | client_id, source, exec_dir |
| Playwright → Visual Analyzer | YAML (`collection.yaml`) | caminhos de screenshots + metadata |
| Orquestrador → Gemini | Args CLI | client_id, output path |
| Orquestrador → Ollama Researcher | Args CLI | client_id, output path |
| Gemini → Scoring/Merge | YAML (`gemini_research.yaml`) | `pesquisa_gemini` com resultados |
| Ollama Researcher → Scoring/Merge | YAML (`ollama_research.yaml`) | `pesquisa_ollama_regional` com resultados |
| Visual Analyzer → Preprocess | YAML (`visual_analysis.yaml`) | `analise_visual` com `pautas_identificadas` |
| Preprocess → Scoring/Merge | YAML (`deduplicated_visual_analysis.yaml`) | pautas deduplicadas |
| Scoring/Merge → Estratégia | MD estruturado | `final_research.md` |

---

## Critérios de Scoring

| Campo | Escala | Descrição |
|---|---|---|
| `relevancia` | 0–10 | Relevância para nicho e público do cliente |
| `potencial_alcance` | 0–10 | Probabilidade de alcançar pessoas além dos seguidores |
| `potencial_engajamento` | 0–10 | Probabilidade de likes/comentários/shares/saves |
| `rate_timing` | 0–10 | Oportunidade agora (sazonal, trending, recente) |

Campos editoriais adicionais obrigatórios: `transformacao` · `friccao_central` · `evidencias_disponiveis` · `evidencias_a_pesquisar` · `eixo_narrativo` (Mercado/Cases/Notícias/Cultura/Produto) · `etapa_funil` (Topo/Meio/Fundo) · `gatilhos_emocionais` · `padrao_hook_potencial` (quando aplicável).

Fórmula de scoring de engajamento (determinística, em `score.py`):
```python
velocity = (likes + comments*3 + shares*5 + views*0.1) / hours_elapsed
# Twitter: inclui shares e views. Instagram: apenas likes + comments*3.
```

---

## Política de Falhas

| Falha | Comportamento |
|---|---|
| Perfil Instagram não carrega | Registrar, pular, continuar |
| Twitter bloqueado | Registrar, continuar |
| Gemini API error/rate limit | Registrar, continuar sem esta fonte |
| Ollama Regional API falha | Registrar, continuar sem esta fonte |
| Embedding dedup falha | Registrar, usar visual_analysis.yaml original |
| API Ollama indisponível (Visual Analyzer) | Registrar falha, research continua sem análise visual |
| Timeout de sub-agente | Registrar, marcar fonte como falha, orquestrador continua |

**Nunca:** travar a execução por falha de uma fonte.

---

## Documentos de Referência

| Arquivo | Conteúdo |
|---|---|
| `build/01_project_overview.md` | Visão geral, contexto de negócio, stack |
| `build/02_research_architecture.md` | Arquitetura do research, fontes, fluxo, schemas YAML |
| `build/03_research_agent_behavior.md` | Comportamento detalhado de cada agente, outputs, falhas |
| `build/04_complementary_context.md` | Gaps arquiteturais, contexto complementar, decisões |
| `build/05_research_editorial_intelligence.md` | Critérios editoriais, padrões de hook, lógica de conexão indireta |
| `build/06_etapa-coleta-playwright.md` | Implementação Playwright, scoring, anti-detecção, rate limits |
| `build/ollama_capabilities.md` | Capacidades do servidor Ollama (visão, thinking, web search, embeddings) |

O agente Visual Analyzer e o Scoring/Merge devem incorporar os critérios editoriais de `build/05_research_editorial_intelligence.md` como parte central do raciocínio.
