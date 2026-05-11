# Ollama Regional Researcher — Comportamento e Responsabilidades

> Sub-agente Python que faz pesquisa REGIONAL via Ollama `web_search` + `web_fetch`, sintetizada por LLM (Kimi K2.6 cloud). Foco exclusivo em Ilhéus/Itabuna (BA) e contexto local relevante para o nicho do cliente.
>
> **Localização sugerida:** `agents/ollama_researcher/ollama_behavior.md`
> **Implementação:** `agents/ollama_researcher/research.py`

---

## 1. Identidade e papel no sistema

O Ollama Regional Researcher é a **fonte local profunda** do sistema. Diferente do Tavily (busca geral) e Gemini (síntese nacional), o Ollama:

- Foca exclusivamente em conteúdo regional (cidade do cliente + região da Bahia).
- Combina `web_search` (busca dirigida) com `web_fetch` (leitura de portais regionais conhecidos).
- Sintetiza os resultados via LLM antes de gravar — produz YAML estruturado, não resultados crus.
- Aplica raciocínio de conexão indireta entre tema regional e nicho do cliente.

Ativado quando `OLLAMA_API_KEY` está configurada.

---

## 2. Trigger e contexto inicial

### 2.1. Como é invocado

```bash
python agents/ollama_researcher/research.py --client-id <id> --output <path>
```

### 2.2. Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `OLLAMA_API_KEY` | Sim | Sem ela, fonte é pulada silenciosamente. |
| `OLLAMA_API_BASE` | Não | Default: `https://ollama.com`. |
| `OLLAMA_RESEARCHER_MODEL` | Não | Default: `kimi-k2.6:cloud`. |
| `DREAM_SQUAD_PULSE` | Não | Conteúdo de `pulse.md`, injetado no prompt de síntese se disponível. |

### 2.3. Pré-condições

1. `OLLAMA_API_KEY` definida.
2. Lib `ollama>=0.5.0` importável.
3. `profile.yaml` carregado (extrai `niche`, `location`, `audience`).
4. ISO week atual (para rotação determinística de queries).
5. Lista de portais regionais carregada de `build/web_search_sites.txt`.

---

## 3. Comportamento de pesquisa

### 3.1. Duas modalidades combinadas

#### Modalidade A — `web_search` (busca dirigida)

3 queries por execução, escolhidas via rotação determinística entre 6-8 templates regionais:

| Eixo regional | Template |
|---|---|
| `noticia_local` | `notícias {city} {state} {month_year_pt}` |
| `evento` | `eventos {city} {month_year_pt}` |
| `nicho_regional` | `{niche} {city} {state} {month_year_pt}` |
| `comportamento_local` | `comportamento consumidor {city} {state}` |
| `cultura_baiana` | `cultura {state} {month_year_pt}` |
| `economia_regional` | `economia {city} {state} {year}` |

Selector via `hash(client_id + ISO_week)`.

#### Modalidade B — `web_fetch` (leitura de portais conhecidos)

Lê URLs de `build/web_search_sites.txt` (lista mantida pelo operador). Cada URL é fetched, conteúdo é truncado em `_WEB_FETCH_MAX_CHARS = 6000` e adicionado ao input de síntese.

**Por que truncar:** evita explodir o context window do Kimi com páginas inteiras de 50KB de HTML/markdown. 6000 chars é o suficiente para capturar manchetes e ledes da home.

### 3.2. Síntese via Kimi K2.6

Após coletar resultados de A + B, monta um prompt único com:

- Contexto do cliente (nicho, localização, público-alvo, sazonal).
- Resultados das buscas e dos portais.
- Instrução de aplicar conexão indireta.
- Schema YAML alvo.
- Pulse (se disponível).

Chama `client.chat()` com `temperature=0.2` (conservador, evita alucinação) e parseia o YAML retornado.

### 3.3. Critério editorial

O prompt instrui:

> Aplique o critério de conexão indireta: o tema não precisa ser sobre o nicho diretamente — precisa ter um ângulo que conecta com o nicho ou com o público-alvo.
> Priorize resultados concretos (notícias com data, evento específico) sobre resultados genéricos.
> Descarte resultados sem relação possível.

Esse é o filtro semântico que diferencia o Ollama de uma busca tosca.

### 3.4. Sinais de fonte (novo)

Para cada resultado sintetizado, o Kimi DEVE preencher (quando aplicável):

```yaml
- tema: "..."
  ...
  sinal_timing: "weekly_news" | "evento_proximo" | "evergreen_local"
  sinal_friccao: "..."          # opcional
  sinal_transformacao: "..."    # opcional
```

---

## 4. Retorno esperado

### 4.1. Schema

Output em `<exec_dir>/research/ollama_research.yaml`:

```yaml
pesquisa_ollama_regional:
  client_id: "casadobicho"
  nicho: "veterinária"
  data_pesquisa: "2026-05-09"
  resultados:
    - tema: "Feira de Adoção de Pets em Ilhéus"
      titulo: "Prefeitura de Ilhéus organiza feira de adoção no Parque Municipal"
      descricao: >
        Evento marcado para sábado 11/05 reunirá ONGs locais e divulgará
        práticas de adoção responsável. Alta visibilidade no público da clínica.
      url_fonte: "https://prefeituradeilheus.ba.gov.br/..."
      data_hora: "2026-05-09"
      relevancia_nicho: 9
      origem: "ollama"
      sinal_timing: "evento_proximo"
```

### 4.2. Quantidade

- 3-6 resultados por execução é o esperado.
- Mais que isso pode ser sinal de que o LLM está incluindo coisas irrelevantes — revisar critério de filtro no prompt.

### 4.3. Falhas

| Situação | Ação |
|---|---|
| `OLLAMA_API_KEY` ausente | YAML de erro, exit 0, fonte pulada |
| Lib `ollama` não disponível | YAML de erro, exit 0 |
| Todas as `web_search` falharam E todas as `web_fetch` falharam | YAML de erro, exit 0 |
| `web_search` falhou parcialmente | Log warning, continua com o que tem |
| `web_fetch` falhou parcialmente | Log warning, continua com o que tem |
| Kimi retornou YAML inválido | Após 3 retries, YAML de erro |
| Kimi retornou sem `pesquisa_ollama_regional` | YAML de erro |

---

## 5. Manutenção da lista de portais

### 5.1. Localização

`build/web_search_sites.txt`:
```
# Lista de portais regionais para web_fetch
# Uma URL por linha. Linhas começando com # são ignoradas.
https://radiosantamariaam.com.br/
https://www.bnews.com.br/noticias/regional/sul-da-bahia
https://www.aratu.uol.com.br/
# ...
```

### 5.2. Quem mantém

O operador. O agente lê passivamente. Adicionar/remover portais é decisão editorial humana.

### 5.3. Como avaliar qualidade do portal

- O portal tem manchetes atualizadas (últimos 7 dias)? → manter.
- O portal só publica conteúdo nacional sem recorte regional? → remover.
- O portal tem paywall agressivo que devolve "Erro 401" no `web_fetch`? → remover.

---

## 6. Custo

Ollama web_search e web_fetch consomem créditos do plano da Ollama Cloud. Verificar plano ativo.

Como controle indireto, há limite implícito: 3 web_searches + N web_fetches por execução. N é o tamanho de `web_search_sites.txt`.

**Recomendação:** manter `web_search_sites.txt` com no máximo 6-8 portais. Mais que isso, custo cresce linearmente sem ganho proporcional de qualidade.

---

## 7. Métricas reportadas

```
METRICS_JSON: {"resultados_count": <int>, "retries": <int>}
```

Logs (stderr):
```
[INFO] web_search OK: notícias Ilhéus Bahia maio 2026
[INFO] web_fetch OK: https://radiosantamariaam.com.br/
[INFO] Ollama Regional: 4 resultados → /clients/.../ollama_research.yaml
```

---

## 8. O que o Ollama Regional NUNCA faz

- ❌ Não pesquisa sobre temas nacionais/globais.
- ❌ Não tenta ser substituto do Gemini ou Tavily.
- ❌ Não reproduz texto literal de notícias regionais com mais de 15 palavras.
- ❌ Não inventa eventos locais.
- ❌ Não modifica `web_search_sites.txt`.
- ❌ Não cacheia resultados (cada execução é nova).

---

## 9. Calibração de qualidade

### Output bom

1. **Pelo menos 60% dos resultados são geograficamente locais** (Ilhéus, Itabuna, Sul da Bahia, Bahia).
2. **Pelo menos 1 resultado tem `data_hora` nos últimos 14 dias** (sinal de captura recente).
3. **Conexão indireta clara** quando o tema não é sobre o nicho diretamente.
4. **URLs são de portais distintos**, não todos do mesmo site.

### Sinal de output ruim

- Resultados sem URL (LLM inventou) → revisar prompt.
- Resultados sobre o Brasil em geral, sem recorte regional → ampliar peso de `city` no prompt.
- Resultados se repetem semana a semana → revisar rotação de queries.

---

## 10. Evolução futura

- Detectar quando portal regional está em manutenção (resposta vazia repetida) e pular automaticamente.
- Adicionar `web_search` por hashtag local quando aplicável.
- Cache de `web_fetch` por (URL, ISO_day) para retries do operador.

Por enquanto, foco é robustez e qualidade da síntese.