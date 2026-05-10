# CLAUDE.md

Este arquivo fornece ao Claude Code o contexto completo do projeto Dream Squad.

---

## O que é o Dream Squad

Sistema multi-agentes rodando dentro do Claude Code CLI. Automatiza a produção de conteúdo estratégico (carrosséis, roteiros de reels/stories/b-rolls) para pequenas empresas de Ilhéus/Itabuna (BA) sem verba para tráfego pago. O operador é o estrategista/gestor; os clientes recebem o conteúdo via board Trello atualizado 2×/semana.

**Stack:** Python · Gemini API (pesquisa nacional) · Tavily (web search geral) · Ollama Python SDK (web search regional — disponível em qualquer ambiente se `OLLAMA_API_KEY` configurada) · Apify (posts públicos de perfis de referência) · Input manual do operador · Trello (publicação) · Claude Code CLI (todos os agentes LLM)

---

## Instalação

```bash
pip install -e .
```

Copie `.env.example` para `.env` e preencha todas as variáveis.

> `pip install -e .` instala o pacote em modo desenvolvimento e elimina a necessidade de `sys.path.insert` nos scripts.

---

## Como Executar o Research

O operador invoca o sistema em linguagem natural. O Claude Code (orquestrador) segue o fluxo abaixo.

### Passo 1 — Etapas Python (coleta + pesquisa)

```bash
python agents/orchestrator/run.py --client-id casadobicho
```

Cria diretório de execução com timestamp, roda Gemini, Tavily, Ollama Regional (se `OLLAMA_API_KEY` configurada), Apify e Manual Input serialmente. Imprime ao final as instruções exatas para o Claude Code continuar.

Flags opcionais: `--skip-gemini` · `--skip-tavily` · `--skip-ollama-research` · `--skip-apify` · `--exec-dir <path>`

### Passo 2 — Scoring e Merge

O Claude Code lê `agents/scoring_merge/instructions.md` e consolida todos os YAMLs disponíveis em `final_research.md`.

**Em qualquer ambiente:** o Scoring/Merge é um sub-agente nativo do Claude Code, invocado via **Task tool**. O `DREAM_SQUAD_ENV` indica apenas qual modelo o Claude Code está usando nativamente — não altera o mecanismo de invocação.

- **Ambiente Anthropic:** Claude Code logado com conta Anthropic → Task tool usa Claude Sonnet por baixo.
- **Ambiente Ollama:** Claude Code logado com conta Ollama → Task tool usa Kimi K2.6 (ou outro modelo Ollama configurado na conta) por baixo.

---

## Variáveis de Ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `DREAM_SQUAD_ENV` | **Sim** | `anthropic` ou `ollama`. Ausência = erro explícito (sem input manual). |
| `GEMINI_API_KEY` | Sim | Google Gemini API — deep research nacional |
| `GEMINI_MODEL` | Não | Modelo Gemini. Default: `gemini-2.0-flash` |
| `TAVILY_API_KEY` | Recomendado | Tavily web search. Ausência = fonte pulada silenciosamente |
| `APIFY_API_TOKEN` | Recomendado | Coleta de posts públicos via Apify. Ausência = fonte pulada |
| `OLLAMA_API_BASE` | Se Ollama Regional | URL base do servidor Ollama (ex: `https://ollama.com`) |
| `OLLAMA_API_KEY` | Se Ollama Regional | API key do servidor Ollama cloud. **Habilita pesquisa regional via Python SDK.** Não afeta Scoring/Merge. |
| `OLLAMA_MODEL` | Não | Modelo para pesquisa regional. Default: `kimi-k2.6:cloud` |
| `OLLAMA_RESEARCHER_MODEL` | Não | Modelo para pesquisa regional. Default: `kimi-k2.6:cloud` |
| `AGENT_TIMEOUT_S` | Não | Timeout por subprocess em segundos. Default: 120 |

> **Nota sobre `OLLAMA_API_KEY`:** habilita apenas o **Ollama Regional Researcher** (`agents/ollama_researcher/research.py`), que usa `ollama.web_search()` e `ollama.web_fetch()` via Python SDK. O Scoring/Merge nunca chama `ollama.Client.chat()` — em qualquer ambiente, o Scoring/Merge é um sub-agente nativo do Claude Code (Task tool).

---

## Selector de Ambiente Interativo

Quando o operador invocar qualquer fluxo de research (em linguagem natural), o Claude Code DEVE perguntar o ambiente antes de executar `agents/orchestrator/run.py`.

> **Importante:** o selector escolhe qual **provedor/modelo o Claude Code está usando nativamente** — não muda o mecanismo de invocação. Em ambos os casos, o Scoring/Merge é invocado via Task tool nativa do Claude Code. A diferença é apenas o modelo subjacente (Sonnet da Anthropic vs Kimi/GLM/Gemma/Qwen via Ollama).

### Comportamento

1. Antes de executar o orquestrador, apresente uma pergunta interativa ao operador:
   - `anthropic (Sonnet)` — Claude Code logado com conta Anthropic
   - `ollama (Kimi K2.6)` — Claude Code logado com conta Ollama
   - `usar último` — apenas se `.dream_squad_session` existir
2. Mapeie a resposta para `DREAM_SQUAD_ENV` e injete **apenas para esta execução**, sem alterar `.env`:
   ```bash
   DREAM_SQUAD_ENV=anthropic python agents/orchestrator/run.py --client-id casadobicho
   ```
3. Após sucesso, persista a escolha em `.dream_squad_session` (apenas a string).
4. Se a env já estiver definida no contexto (ex: cron), pule o selector — `detect_environment()` a usará diretamente.

### Fallback para execução automatizada

Para CI/cron futuro, exporte a env antes de invocar:
```bash
export DREAM_SQUAD_ENV=ollama
python agents/orchestrator/run.py --client-id casadobicho
```

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

Todos os agentes LLM são sub-agentes nativos do Claude Code (Task tool). As exceções são: Gemini API, Tavily API, Ollama Python SDK e Apify Client — usados como ferramentas de pesquisa Python direto.

### Fluxo do Research

```
[Solicitação do operador]
        ↓
[Orquestrador] — identifica cliente, ambiente, roda health check
        ↓
[Gemini Researcher] — tendências nacionais (API Python)
        ↓
[Tavily Researcher] — web search geral (API Python)
        ↓
[Ollama Regional Researcher] — notícias locais via web_search (qualquer ambiente, requer OLLAMA_API_KEY)
        ↓
[Apify Collector] — posts públicos de perfis de referência (API Python)
        ↓
[Manual Input Loader] — contexto manual do operador (leitura de arquivo)
        ↓
[Scoring/Merge] — dedup LLM, enriquecimento cruzado, rankeamento, seleção editorial
        ↓
[Output: final_research.md → etapa de Estratégia]
```

**Regras absolutas:**
- Todas as fontes Python são executadas serialmente
- A falha de uma fonte não interrompe as demais (falha silenciosa)
- Toda comunicação entre agentes é em YAML/JSON/MD estruturado

### Responsabilidades por Agente

**Orquestrador**
- Carrega `profile.yaml` do cliente
- Detecta ambiente via `DREAM_SQUAD_ENV` (obrigatória — ausência = `sys.exit(1)`)
- Roda health check antes de qualquer subprocess
- Aciona sub-agentes na ordem correta com timeout explícito (`AGENT_TIMEOUT_S`)
- Registra `session.yaml` com métricas por etapa (status, elapsed_s, retries, timeout, resultados_count)

**Gemini Researcher** (`agents/gemini_researcher/research.py`)
- Chamada direta à API Python com `GEMINI_API_KEY`
- Input: nicho + data + período sazonal + contexto do cliente
- Retry automático: 3 tentativas com backoff exponencial
- Output: `gemini_research.yaml` com campo `pesquisa_gemini`

**Tavily Researcher** (`agents/tavily_researcher/research.py`)
- Web search geral via `tavily-python`
- Respeita `tavily_max_requests` do profile como teto de queries por execução
- Strip de HTML nos resultados antes de gravar
- Output: `tavily_research.yaml` com campo `pesquisa_tavily`

**Ollama Regional Researcher** (`agents/ollama_researcher/research.py`) — *qualquer ambiente, ativado se `OLLAMA_API_KEY` estiver configurada*
- Busca notícias de Ilhéus/Itabuna via `ollama.web_search()`
- Executa 3 queries direcionadas, sintetiza via `client.chat()`
- Output: `ollama_research.yaml` com campo `pesquisa_ollama_regional`

**Apify Collector** (`agents/apify_collector/collect.py`)
- Coleta posts públicos de `instagram_reference_profiles` do profile
- `apify_budget_credits` do profile como `maxRequestsPerCrawl` (teto absoluto)
- Actor: `apify/instagram-scraper` (público, plano gratuito)
- Output: `apify_research.yaml` com campo `pesquisa_apify`

**Manual Input Loader** (`agents/manual_input/load.py`)
- Lê `clients/{client_id}/manual_input.yaml` editado pelo operador antes da execução
- Filtra entradas de template não preenchidas e entradas com `valido_ate` expirado
- Output: `manual_research.yaml` com campo `manual_research`

**Scoring/Merge** (sub-agente dedicado via Task tool)
- Deduplicação semântica via LLM entre as 5 fontes
- Enriquecimento cruzado: pauta de uma fonte + evidência de outra = pauta mais forte
- Bônus de confiança para pautas confirmadas por múltiplas fontes
- Rankeamento por potencial total, balanceamento Topo/Fundo de funil
- Output: `final_research.md`

---

## Estrutura de Diretórios

```
dream-squad/
├── pyproject.toml
├── CLAUDE.md
├── .env.example
├── .gitignore
├── requirements.txt
├── clients/
│   └── {client_id}/
│       ├── profile.yaml
│       ├── manual_input.yaml          # editado pelo operador antes de cada execução
│       └── executions/
│           └── {YYYY-MM-DD_HHMMSS}/
│               ├── session.yaml
│               └── research/
│                   ├── gemini_research.yaml
│                   ├── tavily_research.yaml
│                   ├── ollama_research.yaml      # apenas ambiente Ollama
│                   ├── apify_research.yaml
│                   ├── manual_research.yaml
│                   └── final_research.md
├── agents/
│   ├── orchestrator/
│   │   └── run.py
│   ├── gemini_researcher/
│   │   └── research.py
│   ├── tavily_researcher/
│   │   └── research.py
│   ├── ollama_researcher/
│   │   └── research.py
│   ├── apify_collector/
│   │   └── collect.py
│   ├── manual_input/
│   │   └── load.py
│   ├── scoring_merge/
│   │   ├── score.py
│   │   └── instructions.md
│   └── utils/
│       ├── paths.py
│       ├── logging_config.py
│       ├── retry.py
│       └── validators.py
├── config/
│   └── server_config.yaml
└── docs/
    └── content_strategy.md
```

---

## Clientes Ativos

| client_id | Nome | Nicho | Localização |
|---|---|---|---|
| `casadobicho` | Casa do Bicho | Veterinária | Ilhéus, BA |
| `verusca-lino` | Dra. Verusca Lino | Pediatria | Ilhéus, BA |
| `ed-telas-e-varais` | Ed Telas e Varais | Serviços (telas/varais) | Ilhéus, BA |
| `musicalizando` | Musicalizando | Escola de música infanto-juvenil | Itabuna, BA |
| `ilheus-iate-clube` | Ilhéus Iate Clube | Clube de sócios náutico | Ilhéus, BA |
| `opcao-seguros` | Opção Seguros | Seguros, financiamentos e consórcio | Itabuna, BA |

**Perfil geral:** todos os clientes têm ticket baixo, pouco conhecimento de marketing, interesse em posicionamento digital e resistência a produzir conteúdo orgânico autêntico. Macros comuns: engajamento, visibilidade, alcance e conversão. Diretrizes transversais: evitar polêmica, linguagem intrusiva e conteúdo político-partidário. Carrosséis prontos para postar são o produto-chefe; roteiros de reels e stories são entregues com direção de arte detalhada. **Exceção:** `ed-telas-e-varais` — carrosséis são inviáveis para o nicho; foco exclusivo em reels e stories.

---

## Schema do profile.yaml

```yaml
client_id: "casadobicho"
name: "Casa do Bicho"
niche: "veterinária"
location: "Ilhéus, BA"
active: true

persona:
  instagram_handle: "@casadobicho"
  bio: "descrição curta do posicionamento"

audience:
  description: "tutores de pets, principalmente mulheres, 25-45 anos"
  location: "Ilhéus e Itabuna, BA"
  pain_points:
    - "dor relevante do público"

voice:
  tone:
    - "institucional leve"
    - "educativo"
    - "emocional leve"
  style: "linguagem acessível, sem jargão técnico"
  avoid:
    - "tom clínico e frio"

objectives:
  - "autoridade"
  - "reconhecimento"

# operator_notes: instruções específicas do operador para este cliente (opcional)
operator_notes: >
  Contexto e ressalvas importantes que guiam a produção de conteúdo.

# content_strategy: override de formato para clientes com restrição (opcional)
content_strategy:
  carousel_viable: true          # false para ed-telas-e-varais
  focus_formats:
    - "carrosséis"
    - "reels"
    - "stories"

instagram_reference_profiles:
  - url: "https://instagram.com/handle_referencia"
    handle: "@handle_referencia"
    relevance: "descrição da relevância"

research:
  apify_max_crawl_requests: 30    # limite de requisições HTTP por chamada ao actor (segurança, não custo)
  apify_max_posts_per_profile: 5  # CONTROLA CUSTO: posts × $0,001/post (apify/instagram-scraper)
  tavily_max_requests: 3          # queries/run = créditos consumidos (1 basic / 2 advanced cada)
  tavily_search_depth: "basic"   # "basic" (1 crédito) ou "advanced" (2 créditos) por query
  tavily_days: 30                # filtro de recência em dias
  tavily_country: "brazil"        # boost de resultados regionais
  tavily_topic_news: true        # se true, usa topic="news" para queries de eixo "noticia"
  tavily_include_domains:        # opcional
    - "g1.globo.com"
  tavily_exclude_domains:        # opcional
    - "site_de_baixa_qualidade.com"
  gemini_max_queries: 3          # quantas queries rotacionadas usar por execução
  score_threshold: 5.5           # threshold padrão de score_total
  score_threshold_low_sources: 4.5  # threshold quando < 3 fontes disponíveis
  gemini_context: >
    Contexto adicional para o pesquisador Gemini.
```

**Budget Apify:** plano gratuito = $5/mês (renova mensalmente, não acumula). Custo total estimado com 6 clientes × 2 runs/semana = **640 posts/mês = $0,64/mês**. Margem: ~$4,36. Alavanca de custo real é `apify_max_posts_per_profile`, não `apify_max_crawl_requests`.

**Budget Tavily:** plano gratuito = 1.000 créditos/mês (renova mensalmente). 6 clientes × 3 queries × 8 runs = 144 queries/mês. Pior caso (todos advanced = 2 créditos): **288 créditos/mês**. Margem: ~712 créditos. Alavancas: `tavily_max_requests` (quantidade) e `tavily_search_depth` (custo por query).

---

## Contrato de Comunicação entre Agentes

| De → Para | Formato | Conteúdo |
|---|---|---|
| Orquestrador → Gemini | Args CLI | client_id, output path |
| Orquestrador → Tavily | Args CLI | client_id, output path |
| Orquestrador → Ollama Researcher | Args CLI | client_id, output path |
| Orquestrador → Apify | Args CLI | client_id, output path |
| Orquestrador → Manual Input | Args CLI | client_id, output path |
| Gemini → Scoring/Merge | YAML (`gemini_research.yaml`) | `pesquisa_gemini` |
| Tavily → Scoring/Merge | YAML (`tavily_research.yaml`) | `pesquisa_tavily` |
| Ollama Researcher → Scoring/Merge | YAML (`ollama_research.yaml`) | `pesquisa_ollama_regional` |
| Apify → Scoring/Merge | YAML (`apify_research.yaml`) | `pesquisa_apify` |
| Manual Input → Scoring/Merge | YAML (`manual_research.yaml`) | `manual_research` |
| Scoring/Merge → Estratégia | MD estruturado | `final_research.md` |

---

## Critérios de Scoring

| Campo | Escala | Descrição |
|---|---|---|
| `relevancia` | 0–10 | Relevância para nicho e público do cliente |
| `potencial_alcance` | 0–10 | Probabilidade de alcançar pessoas além dos seguidores |
| `potencial_engajamento` | 0–10 | Probabilidade de likes/comentários/shares/saves |
| `rate_timing` | 0–10 | Oportunidade agora (sazonal, trending, recente) |

Campos editoriais adicionais no `final_research.md`: `transformacao` · `friccao_central` · `evidencias_disponiveis` · `evidencias_a_pesquisar` · `eixo_narrativo` (Mercado/Cases/Notícias/Cultura/Produto) · `etapa_funil` (Topo/Meio/Fundo) · `gatilhos_emocionais` · `padrao_hook_potencial` · `fontes_confirmadoras`.

---

## Política de Falhas

| Falha | Comportamento |
|---|---|
| Gemini API error/rate limit | Registrar em session.yaml, continuar sem esta fonte |
| Tavily API error/rate limit | Registrar em session.yaml, continuar sem esta fonte |
| Ollama Regional API falha | Registrar em session.yaml, continuar sem esta fonte |
| Apify erro de rede | Registrar, retry 2x com backoff, depois falha silenciosa |
| Apify erro de permissão/plano | Registrar como falha de configuração, sem retry |
| Manual input ausente ou vazio | Registrar, continuar sem esta fonte |
| Timeout de subprocess | Registrar `"timeout": true` em session.yaml, continuar |
| DREAM_SQUAD_ENV ausente | `sys.exit(1)` com mensagem de erro explícita |

**Nunca:** travar a execução por falha de uma fonte.
