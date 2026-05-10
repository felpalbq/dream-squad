# Tavily Researcher — Comportamento e Responsabilidades

> Sub-agente Python que executa web search geral via Tavily API. Diferente do Gemini (deep research com síntese) e do Ollama Regional (foco local), o Tavily traz **resultados de busca crus** otimizados para LLM, com URL, título, conteúdo extraído e score de relevância.
>
> **Localização sugerida:** `agents/tavily_researcher/tavily_behavior.md`
> **Implementação:** `agents/tavily_researcher/research.py`

---

## 1. Identidade e papel no sistema

O Tavily Researcher é a **rede de captura ampla** do sistema. Sua função é:

- Capturar manchetes recentes relevantes para nicho + público.
- Trazer URL e content snippet de fontes confiáveis.
- Validar (ou contradizer) tendências apontadas pelo Gemini.
- Servir como ponte entre tendências nacionais (Gemini) e contexto regional (Ollama).

Diferentemente do Gemini, o Tavily **não sintetiza**. Ele entrega resultados estruturados que o Scoring/Merge consolida.

---

## 2. Trigger e contexto inicial

### 2.1. Como é invocado

```bash
python agents/tavily_researcher/research.py --client-id <id> --output <path>
```

Invocado pelo orquestrador como subprocess.

### 2.2. Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `TAVILY_API_KEY` | Sim | Chave da API. Ausência → falha silenciosa. |

### 2.3. Configuração via `profile.yaml`

```yaml
research:
  tavily_max_requests: 3              # teto de queries por execução
  tavily_search_depth: "basic"        # "basic" (1 crédito) ou "advanced" (2 créditos)
  tavily_days: 30                     # filtro de recência
  tavily_country: "brazil"            # boost regional (opcional)
  tavily_topic_news: true             # ativa topic="news" para queries de eixo "noticia"
  tavily_include_domains:             # opcional
    - "g1.globo.com"
    - "uol.com.br"
  tavily_exclude_domains:             # opcional
    - "site_baixa_qualidade.com"
```

---

## 3. Comportamento de pesquisa

### 3.1. Eixos de query (rotação determinística)

Mesmo princípio do Gemini: 6-8 templates organizados por eixo, escolha de N templates baseada em `hash(client_id + ISO_week)`.

| Eixo | Template exemplo | Params Tavily |
|---|---|---|
| `mercado` | `{niche} tendências Brasil {year}` | `topic="general"`, `time_range="month"` |
| `comportamento` | `comportamento {audience_first} {year}` | `topic="general"` |
| `cultura` | `cultura digital {audience_first} Brasil` | `topic="general"` |
| `noticia` | `{niche} notícias {month_year_pt}` | `topic="news"`, `time_range="week"` |
| `sazonal` | `{seasonal_tag} {niche} Brasil` | `topic="general"`, `time_range="month"` |
| `regional` | `{niche} {city} Bahia {month_year_pt}` | `topic="news"`, `country="brazil"` |
| `caso` | `case sucesso {niche} pequena empresa` | `topic="general"` |
| `curiosidade` | `{audience_first} curiosidades {niche}` | `topic="general"` |

A escolha de eixos respeita `tavily_max_requests`. Se for 3, escolhe 3 eixos diferentes.

### 3.2. Mapeamento eixo → params Tavily

```python
EIXO_TO_PARAMS = {
    "mercado":       {"topic": "general", "time_range": "month"},
    "comportamento": {"topic": "general"},
    "cultura":       {"topic": "general"},
    "noticia":       {"topic": "news", "time_range": "week"},
    "sazonal":       {"topic": "general", "time_range": "month"},
    "regional":      {"topic": "news", "country": "brazil"},
    "caso":          {"topic": "general"},
    "curiosidade":   {"topic": "general"},
}
```

`include_domains` e `exclude_domains` do profile são aplicados a TODAS as queries.

### 3.3. Strip de HTML

O Tavily às vezes retorna `content` com tags HTML residuais. O agente faz strip antes de gravar:

```python
re.sub(r"<[^>]+>", "", text or "").strip()
```

Aplicado a `title` e `content`.

### 3.4. Truncagem

- `tema`: primeiros 80 chars do title.
- `titulo`: title completo (sem HTML).
- `descricao`: primeiros 400 chars do content.

---

## 4. Retorno esperado

### 4.1. Schema

Output em `<exec_dir>/research/tavily_research.yaml`:

```yaml
pesquisa_tavily:
  client_id: "casadobicho"
  nicho: "veterinária"
  data_pesquisa: "2026-05-09"
  resultados:
    - tema: "Tutores de pet aumentam gastos com saúde animal"
      titulo: "Tutores de pet aumentam gastos com saúde animal em 2026 | Globo"
      descricao: >
        Levantamento mostra que tutores brasileiros gastaram em média 38%
        a mais em 2026 com saúde dos pets, comparado a 2024. Aumento puxado
        por exames preventivos e cirurgias eletivas.
      url_fonte: "https://g1.globo.com/economia/..."
      data_hora: "2026-05-08"
      relevancia_nicho: null         # ← Tavily não atribui, Scoring/Merge decide
      origem: "tavily"
      eixo_query: "noticia"          # ← novo: ajuda Scoring/Merge a entender contexto
      sinal_timing: "weekly_news"    # ← derivado do topic="news"
```

### 4.2. Quantidade

- `tavily_max_requests` queries × `max_results=5` = até 15 resultados.
- Tipicamente 8-12 resultados úteis (após dedup e qualidade).

### 4.3. Falhas

| Situação | Ação |
|---|---|
| `TAVILY_API_KEY` ausente | YAML de erro, exit 0 |
| `tavily-python` não instalado | YAML de erro, exit 0 |
| Query individual falha | Log warning, continua próxima query |
| Todas as queries falharam | YAML de erro, exit 0 |
| Crédito esgotado (HTTP 429) | Retry com backoff; após 3 falhas, registra e aceita |

---

## 5. Controle de custo

### 5.1. Plano gratuito Tavily

- 1.000 créditos/mês (renova mensalmente, não acumula).
- Basic search: 1 crédito/query.
- Advanced search: 2 créditos/query.

### 5.2. Cálculo de margem

Cenário típico: 6 clientes × 3 queries × 2 runs/semana × 4 semanas = **144 queries/mês**.

- Pior caso (todas advanced): 288 créditos/mês → margem ~712.
- Caso típico (todas basic): 144 créditos/mês → margem ~856.

**Alavancas:**
- `tavily_max_requests`: reduz quantidade.
- `tavily_search_depth`: troca qualidade por custo.

### 5.3. Quando usar `advanced`

- Cliente premium ou execução crítica.
- Queries que retornam pouco em basic (sintoma de termo muito específico).
- Pesquisas com `topic="news"` onde recência exata importa.

Por padrão, **basic é suficiente** para 80% dos casos.

---

## 6. Métricas reportadas

```
METRICS_JSON: {"resultados_count": <int>, "retries": <int>}
```

Logs:
```
[INFO] Tavily OK: 'veterinária notícias maio 2026' → 5 resultados
[INFO] Tavily: 12 resultados → /clients/casadobicho/executions/.../tavily_research.yaml
```

---

## 7. O que o Tavily Researcher NUNCA faz

- ❌ Não atribui `relevancia_nicho` (deixa para o Scoring/Merge).
- ❌ Não interpreta semântica dos resultados.
- ❌ Não consolida resultados duplicados (deixa para o pré-clustering).
- ❌ Não escreve em campos que o Gemini ou outras fontes alimentam.
- ❌ Não modifica `profile.yaml`.
- ❌ Não chama o Gemini ou outras fontes.

---

## 8. Calibração de qualidade

### Output bom

1. **Diversidade de domínios:** pelo menos 5 domínios diferentes nos resultados.
2. **Recência:** pelo menos 30% dos resultados com `data_hora` nos últimos 30 dias (quando `tavily_days=30`).
3. **URLs únicas:** sem duplicação literal.
4. **Conteúdo extraído tem substância** — não é só metadata da página.

### Sinal de output ruim

- Todos os resultados do mesmo domínio (sintoma de SEO ruim ou query muito específica).
- 80%+ dos resultados são de blogs/agregadores genéricos.
- `data_hora` antigo (>90 dias) na maioria — sintoma de query mal formulada.
- Conteúdo é apenas título repetido — sintoma de páginas sem texto útil.

Quando isso ocorre: **revisar templates de query** ou ajustar `include_domains`.

---

## 9. Diferenças vs Ollama Regional

| Aspecto | Tavily | Ollama Regional |
|---|---|---|
| Escopo | Geral (Brasil) | Local (Ilhéus/Itabuna) |
| Queries | Rotação por eixos editoriais | Foco em "regional + nicho" |
| Síntese | Não — entrega bruto | Sim — sintetiza via Kimi |
| Custo | Plano gratuito até ~140 queries/mês | Web search via Ollama (verificar plano) |
| Quando ativar | Sempre | Quando `OLLAMA_API_KEY` disponível |

Tavily e Ollama Regional **não substituem um ao outro**. São complementares.

---

## 10. Evolução futura

- Filtro automático de domínios pelo histórico de "fontes confirmadoras" mais usadas.
- A/B test de `topic="news"` vs `topic="general"` por eixo.
- Caching de resultados por (query, ISO_day) para retries do operador.

Por enquanto, escopo é manter o agente operacional e econômico em créditos.