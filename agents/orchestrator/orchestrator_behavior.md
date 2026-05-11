# Orchestrator — Comportamento e Responsabilidades

> Arquivo de referência para o agente orquestrador do sistema Dream Squad. Este documento descreve **o que** o orquestrador faz, **como** decide, **com quem** se comunica e **o que nunca deve fazer**. Implementação técnica vive em `agents/orchestrator/run.py`. Este arquivo descreve comportamento esperado.
>
> **Localização sugerida:** `agents/orchestrator/orchestrator_behavior.md`

---

## 1. Identidade e papel no sistema

O Orquestrador é o coordenador da Etapa 1 (Research). Sua responsabilidade é única: **garantir que cada fonte de pesquisa rode com o contexto correto, na ordem correta, com timeout adequado, e que o resultado de cada uma chegue até o Scoring/Merge sem perda nem corrupção**.

Ele **não pesquisa**. Ele **não interpreta resultados**. Ele **não decide qualidade de conteúdo**. Sua função é processo, não conteúdo.

---

## 2. Trigger e contexto inicial

### 2.1. Como é invocado

```bash
python agents/orchestrator/run.py --client-id <client_id>
```

Flags opcionais:
- `--skip-gemini`
- `--skip-tavily`
- `--skip-ollama-research`
- `--skip-apify`
- `--exec-dir <path>` (reusar diretório de execução existente, útil para retry parcial)

### 2.2. Pré-condições

Antes de iniciar qualquer subprocess, o orquestrador verifica:

1. **`profile.yaml` do cliente existe** em `clients/{client_id}/`. Ausência → `sys.exit(1)`.
2. **Health check de fontes externas**: para cada fonte, verifica presença da env var de credencial E disponibilidade da biblioteca Python.
3. **Pelo menos uma fonte disponível**. Zero fontes disponíveis → `sys.exit(1)` com mensagem de configuração.

### 2.3. Saída do health check

```
[health check] Fontes disponíveis:
  [OK] gemini
  [OK] tavily
  [OK] ollama
  [--] apify
  [OK] manual
```

Fontes marcadas `--` são puladas silenciosamente — o pipeline continua.

---

## 3. Fluxo de execução

### 3.1. Ordem das etapas (determinística)

1. Carregar `profile.yaml`
2. Health check
3. Criar diretório de execução `clients/{client_id}/executions/{YYYY-MM-DD_HHMMSS}/`
4. Carregar `pulse.md` da raiz, se existir, e injetar contexto via env var `DREAM_SQUAD_PULSE`
6. Carregar `used_topics.json` do cliente (se existir) — passa adiante para o Scoring/Merge
7. **Etapa 1:** Gemini Researcher
8. **Etapa 2:** Tavily Researcher
9. **Etapa 3:** Ollama Regional Researcher (se `OLLAMA_API_KEY` disponível)
10. **Etapa 4:** Apify Collector
11. **Etapa 5:** Manual Input Loader (sempre, mesmo se vazio)
12. **Etapa 6:** Pré-clustering (Jaccard) → `clusters_preprocessed.yaml`
13. Gravar `session.yaml` com métricas completas
14. Imprimir instruções para o Claude Code spawnar o sub-agente Scoring/Merge

**Regras absolutas:**
- Etapas 1-5 são serializadas. Não rodar em paralelo.
- Falha em qualquer etapa de coleta NÃO interrompe as demais — o orquestrador apenas registra `status: falha` em `session.yaml.stages.<etapa>` e continua.
- Falha na Etapa 6 (pré-clustering) **interrompe** — sem clusters, o Scoring/Merge não tem entrada estruturada.

### 3.2. Timeouts

Cada subprocess tem timeout independente, configurável via `AGENT_TIMEOUT_S` (default: 120s). Em caso de timeout:
- Subprocess é morto.
- `session.yaml.stages.<etapa>.timeout = true`.
- `session.yaml.stages.<etapa>.status = "falha"`.
- Próxima etapa inicia normalmente.

### 3.3. Retry

Retry de subprocess **não é responsabilidade do orquestrador**. Cada agente é responsável pelo seu próprio retry interno (via `with_retry`). Se um agente falhou após exaurir suas tentativas, o orquestrador aceita a falha e continua.

---

## 4. Comunicação entre agentes

### 4.1. Input para sub-agentes

Sempre via argumentos CLI:
- `--client-id <id>`: identifica o cliente.
- `--output <path>`: caminho exato onde gravar o YAML de output.

Variáveis de ambiente (herdadas):
- `DREAM_SQUAD_PULSE` (se houver `pulse.md`)
- Credenciais específicas de cada fonte.

### 4.2. Output recebido de sub-agentes

Cada subprocess imprime na última linha do stdout:
```
METRICS_JSON: {"resultados_count": <int>, "retries": <int>}
```

O orquestrador faz parse e popula `session.yaml.stages.<etapa>.resultados_count`.

### 4.3. Output para Scoring/Merge

O orquestrador NÃO chama o Scoring/Merge diretamente. Ele apenas:
1. Garante que todos os YAMLs de fonte estão no diretório de execução.
2. Gera `clusters_preprocessed.yaml`.
3. Imprime no stdout instruções exatas para o Claude Code (top-level) spawnar o sub-agente.

Exemplo de instrução:
```
PRÓXIMOS PASSOS (Claude Code):

1. SCORING E MERGE:
   Spawne um sub-agente com:
   - Instruções: agents/scoring_merge/instructions.md
   - Cliente: casadobicho | Nicho: veterinária
   - Inputs disponíveis:
     <exec_dir>/research/clusters_preprocessed.yaml
     <exec_dir>/research/gemini_research.yaml
     <exec_dir>/research/tavily_research.yaml
     <exec_dir>/research/apify_research.yaml
     <exec_dir>/research/manual_research.yaml
     clients/casadobicho/profile.yaml
     clients/casadobicho/research/used_topics.json   # se existir
   - Output: <exec_dir>/research/final_research.md
```

---

## 5. Métricas registradas em `session.yaml`

```yaml
client_id: "casadobicho"
timestamp: "2026-05-09T14:05:30"
exec_dir: "clients/casadobicho/executions/2026-05-09_140530"
health_check:
  gemini: true
  tavily: true
  ollama: true
  apify: false
  manual: true
stages:
  gemini:
    status: "sucesso"            # sucesso | falha | pulado
    elapsed_s: 8.4
    retries: 0
    timeout: false
    resultados_count: 6
    erro: null
    output: "<path>/gemini_research.yaml"
  tavily:
    status: "sucesso"
    elapsed_s: 5.1
    retries: 1                    # ← retry interno do agente
    resultados_count: 12
    output: "<path>/tavily_research.yaml"
  ollama_researcher:
    status: "falha"
    elapsed_s: 30.0
    retries: 3
    timeout: true
    resultados_count: 0
    erro: "Timeout após 120s"
  apify:
    status: "pulado"
    motivo: "APIFY_API_TOKEN não configurado"
  manual_input:
    status: "sucesso"
    elapsed_s: 0.1
    resultados_count: 2
  preprocess:
    status: "sucesso"
    elapsed_s: 0.4
    clusters_count: 8
total_elapsed_s: 44.0
```

Esse arquivo é fonte canônica para auditoria pós-execução.

---

## 6. O que o Orquestrador NUNCA faz

- ❌ Não interpreta conteúdo dos YAMLs de fontes.
- ❌ Não decide qualidade de pautas.
- ❌ Não retenta subprocess (retry é dos agentes individuais).
- ❌ Não escreve em `final_research.md` (responsabilidade do Scoring/Merge).
- ❌ Não modifica `profile.yaml` ou `manual_input.yaml`.
- ❌ Não loga credenciais (env vars) em `session.yaml` ou stdout.
- ❌ Não acessa internet diretamente.
- ❌ Não invoca o Scoring/Merge — apenas instrui o Claude Code top-level.

---

## 7. Política de logs

- Stdout: progresso humano-legível (cabeçalhos, status por etapa, resumo final).
- Stderr: logs estruturados via `logging` (formato `YYYY-MM-DD HH:MM:SS [LEVEL] name — message`).
- `session.yaml`: estado completo da execução, fonte de verdade para auditoria.
- Nunca logar valores de env vars (credenciais).

---

## 8. Critério de sucesso de uma execução

Uma execução é considerada **sucesso** quando:
1. `session.yaml` foi gravado.
2. Pelo menos 2 das 5 fontes retornaram `status: "sucesso"` com `resultados_count >= 1`.
3. `clusters_preprocessed.yaml` foi gerado com pelo menos 1 cluster.
4. As instruções de continuação foram impressas no stdout.

Caso contrário, retornar exit code 1. O Claude Code top-level deve tratar exit code 1 como "research não consegue prosseguir, avise o operador".