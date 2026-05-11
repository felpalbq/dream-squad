# Plano de Implementação — Correções Críticas e Estruturais

**Data:** 2026-05-11
**Escopo:** 15 itens priorizados em 4 fases
**Branch sugerida:** `fix/critical-issues-2026-05-11`

---

## Fase 1: Silenciamento de Agente + Falha Hard (P0 — Quebra Execução)

### 1.1 Corrigir import `ollama.web_search/web_fetch` (Falha #4)
**Arquivo:** `agents/ollama_researcher/research.py`
**Problema:** `from ollama import Client, web_search, web_fetch` não existe no SDK `ollama>=0.5.0`.
**Comportamento atual:** ImportError → agente pula silenciosamente em 100% das execuções.

**Mudança:**
- Remover `web_search` e `web_fetch` dos imports.
- Implementar chamada via `client.chat(..., tools=[{"type": "web_search"}])` conforme SDK real.
- `web_fetch` não existe como tool no SDK padrão; usar somente `web_search` com `max_results` e sites específicos via query string (`site:example.com`).
- `_load_search_sites()` converte URLs em queries `site:domain.com` concatenadas à query base.
- Se a API cloud do Kimi K2 expõe web_search via tools no endpoint chat, usar `options={"tools": [{"type": "web_search"}]}` ou o formato correto documentado pelo provedor.

**Investigar antes de codificar:**
> Qual é a chamada real e documentada de `web_search` no Ollama Python SDK com Kimi cloud? Verificar em `ollama.com` ou na base de conhecimento do provedor antes de implementar.

---

### 1.2 Decidir e executar sobre `preprocess.py` (Falha #1 + #2)
**Arquivo:** `agents/scoring_merge/preprocess.py` e `agents/orchestrator/run.py:353-368`
**Problema:** O arquivo existe, é chamado com `check=True`, e contradiz a decisão arquitetural de deduplicação 100% no LLM. Se falha, o orquestrador não grava status em `session.yaml`.

**Opção A — Remover completamente (recomendada pela arquitetura atual):**
1. Deletar `agents/scoring_merge/preprocess.py`
2. Remover Etapa 6 de `run.py` (linhas 353-368)
3. Remover `clusters_preprocessed.yaml` da lista de inputs disponíveis (linhas 401-402)
4. Atualizar `agents/scoring_merge/instructions.md` para remover referências ao pré-clustering Jaccard
5. Atualizar `CLAUDE.md` seção de arquitetura para remover referência ao preprocess

**Opção B — Manter com tratamento gracioso:**
1. Mudar `check=True` para `check=False` em `run.py:364`
2. Tratar ausência de `clusters_preprocessed.yaml` no Scoring/Merge (não incluir nos inputs se não existir)
3. Documentar explicitamente no `CLAUDE.md` que o pré-clustering é opcional e determinístico

**Decisão recomendada:** Opção A. O clustering Jaccard por tema+título já é feito pelo LLM no Scoring/Merge com qualidade superior e contexto semântico. Manter os dois cria duplicação de responsabilidade e complexidade desnecessária.

---

## Fase 2: Dados e Parsing Incorretos (P1 — Qualidade Degradada)

### 2.1 Corrigir cooldown para usar `final_research.md` (Falha #6)
**Arquivo:** `agents/orchestrator/run.py:370-380`
**Problema:** `_extract_topics_from_research` extrai temas dos YAMLs brutos (todas as fontes), incluindo pautas que o Scoring/Merge vai descartar. Em 2 semanas o `used_topics.json` fica saturado e penaliza tudo.

**Mudança:**
1. Mover a extração e persistência de tópicos para **após** o Scoring/Merge terminar.
2. Como o orquestrador Python não controla o Scoring/Merge (é sub-agente LLM), o cooldown deve ser atualizado por quem executa o Scoring/Merge, ou o orquestrador deve ler `final_research.md` numa segunda passada.
3. **Implementação sugerida:** adicionar script `agents/orchestrator/update_cooldown.py` que:
   - Lê `final_research.md`
   - Extrai temas das pautas selecionadas (por regex ou parsing estruturado)
   - Atualiza `used_topics.json`
   - É chamado pelo operador após o Scoring/Merge, ou pelo orquestrador se `--exec-dir` for reusado.
4. No `run.py`, remover linhas 377-380 (a extração pós-etapas). Manter apenas o carregamento e salvamento do histórico (linhas 371-375) sem adicionar novos tópicos.

---

### 2.2 Corrigir `strip_fences` (Falha #7)
**Arquivo:** `agents/utils/text_utils.py`
**Problema:** Não trata `\n` após o fence, não lida com `~~~yaml`, e falha intermitentemente.

**Mudança:**
```python
def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:yaml|json|python)?\s*", "", text)
    text = re.sub(r"^~~~(?:yaml|json|python)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"\s*~~~$", "", text)
    return text.strip()
```
Necessário importar `re` no módulo.

---

### 2.3 Corrigir `validate_yaml_output` para capturar exceções Pydantic (Falha #5)
**Arquivo:** `agents/utils/validators.py:72-78`
**Problema:** `except Exception` captura tudo, mas o caller faz `except ValueError`. Se Pydantic lançar `TypeError` ou outro tipo, o `except ValueError` falha.

**Mudança:**
```python
def validate_yaml_output(data: dict, schema: type[BaseModel], label: str) -> None:
    try:
        schema.model_validate(data)
    except (ValueError, TypeError) as e:
        log.error("[%s] Schema inválido: %s", label, e)
        raise ValueError(f"[{label}] Schema inválido: {e}") from e
```
Não usar `except Exception` aqui — capturar os tipos que Pydantic v2 de fato lança.

---

### 2.4 Corrigir `query_rotation.py` para path seguro (Falha #8)
**Arquivo:** `agents/utils/query_rotation.py:107-108`
**Problema:** `client_profile.get("client_id", "")` pode retornar `""`, gerando path inválido. Exception silenciada por `except Exception: pass`.

**Mudança:**
```python
client_id = client_profile.get("client_id", "")
if not client_id:
    logger.warning("build_query_context: client_id ausente no profile, pulando manual_keywords")
    manual_keywords = ""
else:
    manual_path = client_dir(client_id) / "manual_input.yaml"
    # ... resto do try
```
Adicionar import do logger se necessário.

---

## Fase 3: Métricas, Config e Documentação (P2 — Observabilidade e Manutenção)

### 3.1 Adicionar contador real de retries (Falha #9)
**Arquivo:** `agents/utils/retry.py` e todos os agentes que usam `@with_retry`
**Problema:** `with_retry` executa retries mas não expõe contagem. Métricas sempre reportam `retries: 0`.

**Mudança (opção A — nonlocal, mínima invasão):**
Modificar cada agente que usa `@with_retry` para contar externamente:
```python
retry_count = 0

@with_retry(...)
def _call():
    nonlocal retry_count
    retry_count += 1
    # ... chamada API

try:
    result = _call()
    actual_retries = retry_count - 1  # tentativas = retries + 1 sucesso
except Exception:
    actual_retries = retry_count
```

**Mudança (opção B — alterar decorator):**
Modificar `with_retry` para retornar tupla `(result, retry_count)` ou aceitar um dict mutável como parâmetro opcional. Mais limpo mas afeta todas as callsites.

**Decisão recomendada:** Opção B com backward compat. Adicionar parâmetro opcional `retry_counter: list | None = None` ao decorator. Se fornecido, appenda o número de retries realizados.

---

### 3.2 Documentar e criar `build/web_search_sites.txt` (Falha #10)
**Arquivo:** `CLAUDE.md` + criar `build/web_search_sites.txt` no repo
**Problema:** Arquivo referenciado mas não existe; `.gitignore` ignora `build/`.

**Mudança:**
1. Criar arquivo `build/web_search_sites.txt` com portais regionais de Ilhéus/Itabuna:
   ```
   # Portais regionais para web_search via Ollama Regional
   # Um por linha. Comentários com # são ignorados.
   https://g1.globo.com/ba
   https://www.bnnoticias.com.br
   https://www.itabunaagora.com.br
   https://www.ilheus24h.com.br
   https://www.itapetingaagora.com.br
   ```
2. Adicionar exceção em `.gitignore` para `build/web_search_sites.txt` (ou mover para `config/`):
   ```
   build/
   !build/web_search_sites.txt
   ```
3. Documentar no `CLAUDE.md` na seção de Instalação:
   > Se usar Ollama Regional, crie/edit `build/web_search_sites.txt` com portais regionais. O arquivo já vem com defaults.

**Alternativa:** Mover o arquivo para `config/web_search_sites.txt` para evitar conflito com `.gitignore`. Atualizar `ollama_researcher/research.py:77`.

---

### 3.3 Resolver timeout Apify vs orquestrador (Falha #13)
**Arquivo:** `config/server_config.yaml:8` e `agents/orchestrator/run.py:174`
**Problema:** Apify actor timeout = 180s, AGENT_TIMEOUT_S default = 120s. Subprocess é morto antes.

**Mudança:**
Aumentar `AGENT_TIMEOUT_S` default para **240** em `.env.example:21` e documentar no `CLAUDE.md`:
> `AGENT_TIMEOUT_S` deve ser ≥ 240 se usando Apify, pois o actor pode demorar até 180s.

---

### 3.4 Corrigir Apify `nicho: ""` quando profile não tem `niche` (Falha #11)
**Arquivo:** `agents/apify_collector/collect.py:157-163`
**Problema:** `client_profile.get("niche", "")` retorna `""` se campo existe mas é vazio, ou `""` se não existe. Schema Pydantic aceita string vazia.

**Mudança:**
Validar antes de escrever YAML:
```python
niche = client_profile.get("niche", "")
if not niche:
    logger.warning("Apify: campo 'niche' ausente ou vazio no profile.yaml")
    niche = "não especificado"
```

---

### 3.5 Resolver dependência circular Apify → Score (Falha #12)
**Arquivo:** `agents/apify_collector/collect.py:23`
**Problema:** `from agents.scoring_merge.score import score_from_dict` cria dependência transversal.

**Mudança:**
Mover `score_from_dict` para `agents/utils/engagement.py` (novo módulo) e atualizar ambos os imports:
- `agents/apify_collector/collect.py`: importar de `agents.utils.engagement`
- `agents/scoring_merge/score.py`: re-exportar de `agents.utils.engagement` para backward compatibilidade, ou atualizar todos os callers.

---

## Fase 4: Bifurcação de Ambiente e Sazonalidade (P3 — UX e Robustez)

### 4.1 Resolver instrução de ambiente para Scoring/Merge (Falha #3 + #15)
**Arquivo:** `CLAUDE.md` e `agents/orchestrator/run.py:410-418`
**Problema:** Sem `DREAM_SQUAD_ENV`, o operador não sabe como informar ao Claude Code qual executor usar para o Scoring/Merge LLM. No ambiente Kimi (Ollama), o Claude Code nativo não está disponível.

**Mudança:**
1. **Adicionar flag `--local-merge`** ao `run.py` que, quando usada, pula a instrução de spawn de sub-agente e executa o merge localmente via script Python (`agents/scoring_merge/merge_local.py`).
2. Ou: adicionar variável `SCORING_EXECUTOR=local|anthropic` no `.env` e o orquestrador adapta a mensagem.
3. No `CLAUDE.md`, documentar explicitamente:
   > **Scoring/Merge:** Se estiver no Claude Code Desktop com Kimi (sem acesso a sub-agentes Anthropic), use `python agents/scoring_merge/run_local.py --exec-dir <path>`. Se estiver no Claude Code CLI nativo (Anthropic), spawne o sub-agente normalmente.
4. Criar `agents/scoring_merge/run_local.py` como wrapper que lê os YAMLs e chama o LLM local via Ollama para síntese (se `OLLAMA_API_KEY` disponível), ou escreve um merge determinístico simples quando não houver LLM disponível.

**Decisão recomendada:** Implementar `run_local.py` como fallback. O orquestrador imprime duas opções: sub-agente Claude Code (preferido) ou merge local via Ollama.

---

### 4.2 Adicionar teste/documentação para `seasonal_context` (Falha #14)
**Arquivo:** `agents/utils/seasonality.py`
**Problema:** Lógica de range cruzando meses funciona mas é não-óbvia e sem teste.

**Mudança:**
1. Extrair a lógica de comparação para função auxiliar com comentário explícito:
   ```python
   def _in_window(current: tuple[int, int], start: tuple[int, int], end: tuple[int, int]) -> bool:
       """Verifica se current está no intervalo [start, end], permitindo wrap around ano-virada."""
       if start <= end:
           return start <= current <= end
       # Wrap around: ex: 10 dez → 10 jan
       return current >= start or current <= end
   ```
2. Adicionar testes unitários em `tests/test_seasonality.py` cobrindo:
   - Janela normal (não wrap): `(4, 25)` a `(5, 14)` — testar dentro, antes, depois
   - Janela wrap: `(12, 10)` a `(1, 10)` — testar dez, jan, jun
   - Borda exata: igual a start, igual a end

---

## Resumo por Prioridade

| # | Item | Fase | Arquivo(s) Principal(is) | Esforço |
|---|------|------|--------------------------|---------|
| 4 | Fix Ollama import | 1 | `agents/ollama_researcher/research.py` | Médio (requer investigação API) |
| 1 | Remover preprocess.py | 1 | `agents/scoring_merge/preprocess.py`, `run.py` | Baixo |
| 2 | Fix falha hard preprocess | 1 | `agents/orchestrator/run.py` | Baixo |
| 6 | Fix cooldown (final_research) | 2 | `agents/orchestrator/run.py` + novo script | Médio |
| 7 | Fix strip_fences | 2 | `agents/utils/text_utils.py` | Baixo |
| 5 | Fix validate_yaml_output | 2 | `agents/utils/validators.py` | Baixo |
| 8 | Fix query_rotation path | 2 | `agents/utils/query_rotation.py` | Baixo |
| 9 | Contador real de retries | 3 | `agents/utils/retry.py` + 5 agentes | Médio |
| 10 | Documentar web_search_sites | 3 | `CLAUDE.md`, `build/`, `ollama_researcher` | Baixo |
| 13 | Timeout Apify | 3 | `.env.example`, `CLAUDE.md` | Baixo |
| 11 | Nicho vazio Apify | 3 | `agents/apify_collector/collect.py` | Baixo |
| 12 | Dependência circular score | 3 | `agents/apify_collector/collect.py`, `agents/utils/engagement.py` | Baixo |
| 15 | Bifurcação ambiente | 4 | `CLAUDE.md`, `agents/scoring_merge/run_local.py` | Médio |
| 3 | DREAM_SQUAD_ENV removida | 4 | `CLAUDE.md` | Baixo |
| 14 | Testes seasonal_context | 4 | `agents/utils/seasonality.py` + novo teste | Baixo |

---

## Checklist de Merge

- [ ] Todos os agentes rodam sem erro em `--client-id casadobicho`
- [ ] Ollama Regional produz resultados quando `OLLAMA_API_KEY` está setada
- [ ] `session.yaml` contém `retries` com valor real > 0 quando há retry
- [ ] `used_topics.json` só cresce após Scoring/Merge, não após coleta
- [ ] Apify não quebra por timeout em instalação default
- [ ] `build/web_search_sites.txt` existe e é versionado
- [ ] Sub-agente Scoring/Merge recebe instrução clara sobre qual executor usar
- [ ] `preprocess.py` não é mais chamado (se removido) ou não falha hard (se mantido)
