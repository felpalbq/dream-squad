# Scoring/Merge — Comportamento e Responsabilidades

> Sub-agente LLM que consolida outputs das 5 fontes de research (Gemini, Tavily, Ollama Regional, Apify, Manual Input) e produz `final_research.md` para a etapa de Estratégia. Combina pré-clustering determinístico em Python (Jaccard) + raciocínio LLM para deduplicação semântica, scoring, balanceamento e seleção editorial.
>
> **Localização sugerida:** `agents/scoring_merge/merge_behavior.md`
> **Implementação técnica:** `agents/scoring_merge/instructions.md` (prompt para o LLM) + `agents/scoring_merge/preprocess.py` (clustering determinístico) + `agents/scoring_merge/score.py` (engagement score)

---

## 1. Identidade e papel no sistema

O Scoring/Merge é o **agente mais crítico do pipeline**. Ele recebe ~30-50 candidatos brutos de 5 fontes diferentes e precisa entregar 3-5 pautas finais que vão alimentar a etapa de Estratégia. Tudo abaixo dele depende da qualidade dessa decisão.

### Suas responsabilidades

1. **Consumir clusters pré-formados** pelo `preprocess.py` (Jaccard sobre `tema + titulo`).
2. **Validar ou quebrar clusters** semanticamente (LLM julga se cluster é mesmo uma pauta única).
3. **Enriquecer cruzamento entre fontes** (pauta de uma fonte + URL de outra = pauta mais forte).
4. **Aplicar bônus e penalidades** segundo regras explícitas.
5. **Filtrar pautas que violam `voice.avoid` do cliente.**
6. **Aplicar cooldown de 14 dias** consultando `used_topics.json`.
7. **Garantir balanceamento Topo/Fundo de funil** (quando aplicável ao modo).
8. **Selecionar top 3-5 pautas** para o output final.
9. **Gerar `final_research.md` no formato especificado.**

---

## 2. Trigger e contexto

### 2.1. Como é invocado

**Não é um subprocess Python.** É um sub-agente LLM, invocado pelo Claude Code top-level após o orquestrador concluir.

Spawn via **Task tool nativa do Claude Code** com:
- Instructions: `agents/scoring_merge/instructions.md`
- Inputs anexados (paths dos YAMLs)
- Output target: `<exec_dir>/research/final_research.md`

### 2.2. Inputs

| Arquivo | Sempre presente? | Conteúdo |
|---|---|---|
| `profile.yaml` | Sim | Contexto do cliente |
| `clusters_preprocessed.yaml` | Sim | Clusters pré-formados pelo Jaccard |
| `gemini_research.yaml` | Se Gemini OK | `pesquisa_gemini` |
| `tavily_research.yaml` | Se Tavily OK | `pesquisa_tavily` |
| `ollama_research.yaml` | Se Ollama OK | `pesquisa_ollama_regional` |
| `apify_research.yaml` | Se Apify OK | `pesquisa_apify` (com `engagement_score`) |
| `manual_research.yaml` | Sempre | `manual_research` (pode ter `resultados: []`) |
| `used_topics.json` | Se existir | Pautas dos últimos 14 dias |
| `pulse.md` (se houver) | Não | Contexto agudo do operador |

### 2.3. Pré-condições

1. Pelo menos 2 fontes com `resultados_count >= 1` em `session.yaml`.
2. `clusters_preprocessed.yaml` foi gerado (orquestrador garante).
3. `profile.yaml` carrega sem erro.

---

## 3. Processo de 7 passos

### Passo 1 — Validação de clusters

`preprocess.py` já agrupou candidatos por similaridade Jaccard ≥ 0.5 sobre tokens normalizados de `tema + titulo`. Cada cluster vem com:

```yaml
clusters:
  - id: "cluster_001"
    candidatos:
      - {origem: "gemini", tema: "Mães de pet", titulo: "...", url_fonte: "...", relevancia_nicho: 9, ...}
      - {origem: "tavily", tema: "Tutoras tratam pets como filhos", titulo: "...", url_fonte: "...", ...}
      - {origem: "apify", tema: "Antes e depois...", engagement_score: 187.4, ...}
    similaridade_max: 0.72
  - id: "cluster_002"
    candidatos:
      - {origem: "manual", tema: "Feira de adoção", prioridade_operador: "alta", ...}
    similaridade_max: 1.0  # singleton
```

**Sua tarefa neste passo:** para cada cluster com >1 candidato, **validar semanticamente** se é mesmo uma única pauta:

- Se sim: manter agrupado, marcar `fontes_confirmadoras: [gemini, tavily, apify]`.
- Se não: quebrar em subclusters separados.

**Critério de validação:** intenção editorial idêntica + mesmo público-alvo + mesmo gancho. Não é só palavras parecidas.

### Passo 2 — Filtro de `voice.avoid`

Antes de qualquer scoring:

1. Leia `profile.voice.avoid` (lista de strings).
2. Para cada cluster, verifique se algum candidato menciona ou se aproxima dos temas a evitar (julgamento semântico, não match literal).
3. **Descarte clusters que violam** independente do score.
4. Registre em variável interna `pautas_descartadas_por_filtro` para o output.

**Exemplos:**
- Cliente diz "evitar política, religião, polêmica" → descartar pautas sobre vacinação compulsória, abate ritual, debates Anvisa.
- Cliente diz "evitar tom clínico" → descartar pautas que só funcionam com vocabulário técnico.
- Cliente diz "evitar pressão de venda" → descartar pautas com gancho promocional explícito.

### Passo 3 — Cooldown de 14 dias

Se `used_topics.json` foi anexado:

1. Para cada cluster sobrevivente, normalize tokens de `tema` (lowercase, sem acentos, sem stopwords).
2. Para cada entrada em `used_topics.json` com `data_uso > hoje - 14 dias`:
   - Se Jaccard(cluster_tema, used_tema) ≥ 0.5 → cluster está em cooldown.
3. Para clusters em cooldown:
   - Reduza `relevancia_nicho` em -2.
   - Marque com flag interna `cooldown: true`.
4. Cluster pode ainda entrar no top, mas com penalidade — registre em "Pautas com Cooldown Ativo".

### Passo 4 — Bonus e penalidades

| Situação | Ajuste |
|---|---|
| Cluster confirmado por 2+ fontes | +1 em todos os scores |
| Cluster com URL verificável (Gemini/Tavily/Ollama) | +0.5 em `relevancia` |
| Cluster com fricção/polarização identificada (`sinal_friccao` preenchido) | +1 em `potencial_engajamento` |
| Cluster com transformação clara (`sinal_transformacao` preenchido) | +0.5 em `relevancia` |
| Cluster com `engagement_score >= 100` (Apify) | +1.5 em `potencial_engajamento` |
| Cluster com `engagement_score 50-99` (Apify) | +1.0 em `potencial_engajamento` |
| Cluster com `engagement_score 20-49` (Apify) | +0.5 em `potencial_engajamento` |
| Cluster com `prioridade_operador: alta` (Manual) | **garante seleção** independente do score |
| Cluster sem nenhuma evidência verificável | -1 em `relevancia` |
| Cluster em cooldown | -2 em `relevancia` |
| Cluster com `sinal_timing: trending_now` | +1 em `rate_timing` |
| Cluster com `sinal_timing: weekly_news` | +0.5 em `rate_timing` |

Aplique cumulativamente. Score final por cluster é capado em [0, 10] por dimensão.

### Passo 5 — Score consolidado

Para cada cluster sobrevivente:

```
score_total = (relevancia + potencial_alcance + potencial_engajamento + rate_timing) / 4
```

Threshold de descarte:
- Default: `score_total < 5.5` → descarte.
- Quando há < 3 fontes ativas: `score_total < 4.5` → descarte (relaxado).
- Sempre: `relevancia < 4` → descarte (qualidade mínima).

Exceção: clusters com `prioridade_operador: alta` **não passam por threshold**.

### Passo 6 — Balanceamento Topo/Fundo (condicional ao modo)

Modos do sistema:

#### Modo "Completo semanal"
- Top 3-5 pautas no output final.
- **Obrigatório:** pelo menos 1 pauta de Topo de funil + 1 de Fundo de funil.
- Se não houver pautas suficientes em alguma etapa, registre alerta e siga em frente — não trave.

#### Modo "Carrossel único" / "Roteiro único"
- Pauta principal + 2 alternativas.
- Balanceamento NÃO se aplica — escolha pela maior pontuação.

**Classificação Topo/Meio/Fundo (julgamento editorial):**

| Etapa | Característica | Exemplos |
|---|---|---|
| **Topo** | Tema cultural, comportamental, identificação. Alcance orgânico. | "Mães de pet", "Cultura local", "Tendência geracional" |
| **Meio** | Problema reconhecido pelo público, não decidido a comprar. | "5 sinais que seu pet precisa de check-up", "Como escolher tela protetora" |
| **Fundo** | Decisão de compra, autoridade técnica. | "Por que Casa do Bicho usa anestesia inalatória", "Comparativo de tipos de varal" |

### Passo 7 — Geração do `final_research.md`

Formato exato definido em `instructions.md`. Resumo das seções obrigatórias:

```markdown
# Research — {Nome do Cliente} — {Data}

## Cliente
{contexto resumido}

## Pauta Principal
### Tema
### Pauta
### Ângulos
### Abordagens Possíveis
### Transformação    ← omitir se nenhuma fonte trouxer sinal
### Fricção Central  ← omitir se nenhuma fonte trouxer sinal
### Evidências Disponíveis
### Evidências a Pesquisar na Estratégia
### Fontes e URLs
### Por que Funciona
### Potencial (4 scores + score total)
### Fontes Confirmadoras
### Classificação Editorial (eixo, funil, hook, gatilhos)
### Valor Real

## Pautas Alternativas
### Pauta 2
### Pauta 3

## Pautas Descartadas por Filtro    ← novo
- "Tema X" — motivo: viola voice.avoid: política
- "Tema Y" — motivo: viola voice.avoid: tom clínico

## Pautas com Cooldown Ativo        ← novo, se aplicável
- "Tema Z" — usada em 2026-04-25, cooldown até 2026-05-09 (incluída mesmo assim por relevância)

## Log de Fontes
| Fonte | Status | Resultados brutos |
| ... |
```

---

## 4. Regras editoriais firmes

### 4.1. Honestidade epistêmica

> "Por que Funciona" deve citar pelo menos 1 evidência verificável (URL, métrica, dado). Se nenhuma evidência estiver disponível, escreva apenas:
> *"Sem evidência verificável — pauta priorizada por timing/relevância editorial."*
>
> **Não invente dados, métricas, autores ou estudos.** Honestidade > polish.

### 4.2. Conexão indireta como princípio

Se uma pauta tem conexão direta forte (ex: "vacinação anual" para veterinária) E uma pauta tem conexão indireta interessante (ex: "mães de pet — antropomorfização") com scores similares, **prefira a indireta**. O nicho técnico é menos engajante que o cultural/comportamental.

Esse princípio é dado pelo `docs/content_strategy.md`:
> Hit rate de viralização: comportamento geracional ~33%, marketing técnico ~7%.

### 4.3. Não duplicar com outros nomes

Pauta "Mulheres tratam pets como filhos" e pauta "Antropomorfização do pet" são **a mesma pauta** com nomes diferentes. Detecte isso no Passo 1 (validação semântica do cluster).

### 4.4. Compliance de copyright

Nunca reproduzir literalmente:
- Trechos > 15 palavras de qualquer fonte.
- Letras de música, poemas, manchetes literais.
- Texto de artigos pagos/protegidos.

Sempre parafrasear em suas próprias palavras.

---

## 5. Casos especiais

### 5.1. `prioridade_operador: alta` no Manual Input

Quando o operador marca uma entrada manual como `prioridade_operador: alta`:
- A pauta **garantidamente entra** no top final.
- Mesmo que score < 5.5, entra como pauta principal ou primeira alternativa.
- O operador tem contexto local não verificável — confie.

Exceção: se a pauta também viola `voice.avoid`, descarte mesmo assim. Filtro de avoid > prioridade do operador.

### 5.2. Apenas 1-2 fontes com resultados

Quando `len(fontes_ativas) < 3`:
- Use threshold relaxado (4.5 em vez de 5.5).
- No "Por que Funciona", cite a limitação de fontes.
- Considere apresentar apenas 2-3 pautas em vez de 5.

### 5.3. `content_strategy.carousel_viable: false`

Para clientes como `ed-telas-e-varais`:
- O output deve **ainda assim** trazer pautas, mas adaptadas para reels e stories.
- Em "Tipo de carrossel sugerido", escrever: `"Não aplicável — cliente prioriza reels/stories."`
- Adicionar campo "Formato sugerido": `"Reel"` ou `"Stories sequência"`.

### 5.4. Pulse ativo

Se `pulse.md` tem conteúdo:
- Trate como contexto adicional no Passo 4.
- Pautas alinhadas com o pulse recebem +1 em `rate_timing`.
- Cite o pulse em "Por que Funciona" da pauta afetada.

---

## 6. Output: `final_research.md`

### 6.1. Idioma e tom

- Português do Brasil.
- Tom analítico e direto, não narrativo.
- Sem floreios — cada linha precisa carregar informação útil.

### 6.2. Tamanho

- Pauta principal: ~600-1000 palavras.
- Cada alternativa: ~150-300 palavras.
- Total: 2-4 páginas markdown.

### 6.3. Estrutura imutável

A ordem das seções é fixa. Não inverter, não adicionar seções, não renomear. A etapa de Estratégia depende dessa estrutura para parsear.

---

## 7. O que o Scoring/Merge NUNCA faz

- ❌ Não inventa fontes ou URLs.
- ❌ Não inventa estatísticas ou dados.
- ❌ Não reproduz texto literal de fontes (limite 15 palavras).
- ❌ Não ignora `voice.avoid` do cliente.
- ❌ Não pula o filtro de avoid em nome do `prioridade_operador`.
- ❌ Não escreve em outro arquivo que não seja `final_research.md`.
- ❌ Não modifica os YAMLs de input.
- ❌ Não consulta APIs externas ou faz busca adicional.
- ❌ Não escolhe pautas que violem `content_strategy.carousel_viable: false` apenas em formato carrossel.
- ❌ Não inclui pautas com score < 5.5 (ou < 4.5 em modo relaxado), exceto `prioridade_operador: alta`.

---

## 8. Atualização de `used_topics.json` (pós-execução)

Após gerar `final_research.md`, o **orquestrador** (não o Scoring/Merge) deve atualizar `clients/{client_id}/research/used_topics.json`:

```json
[
  {
    "tema": "Mães de pet — mulheres que tratam pets como filhos",
    "tema_normalizado": "maes pet mulheres tratam pets filhos",
    "data_uso": "2026-05-09",
    "execution_dir": "executions/2026-05-09_140530"
  }
]
```

Limpeza automática: remover entradas com `data_uso > hoje - 14 dias`.

---

## 9. Calibração de qualidade do output final

### Output bom

1. **Top pauta tem ≥ 2 fontes confirmadoras** ou tem `engagement_score` forte do Apify.
2. **"Por que Funciona" cita evidência verificável** (URL ou número).
3. **Balanceamento Topo/Fundo respeitado** quando o modo exige.
4. **Nenhuma pauta selecionada viola `voice.avoid`.**
5. **Pautas Descartadas por Filtro** lista explicitamente o que foi cortado e por quê.
6. **Variedade de eixos narrativos** entre as 3-5 pautas (não todas Mercado, ou todas Notícias).

### Sinal de output ruim

- Top pauta tem 0 evidência e 0 URL.
- Todas as pautas têm score idêntico → sintoma de LLM "preguiçoso", não diferenciou.
- Nenhuma pauta de Topo de funil em modo Completo semanal.
- "Por que Funciona" tem frases genéricas tipo "este tema engaja muito" sem ancoragem.
- Mesma pauta da semana passada apareceu sem ser marcada como cooldown.

Quando isso ocorre: revisar `instructions.md` E o pré-clustering, não o LLM.

---

## 10. Evolução futura

- Embeddings semânticos para deduplicação (substituiria Jaccard) — ganho de precisão de 5-15%.
- Feedback loop com operador (marcar pautas usadas como "boas/ruins" para calibrar scoring futuro).
- A/B test de prompts (versionar `instructions.md` e medir output).
- Suporte a múltiplas linguagens (sistema atual é PT-BR exclusivo).

Por enquanto, foco é qualidade do raciocínio editorial e fidelidade ao formato de output.

---

## 12. Referência rápida do prompt

O `instructions.md` é o **prompt de produção** que entra no LLM. Este documento (`behavior.md`) é o **manual de comportamento** para humanos entenderem o que o agente faz. Os dois devem estar consistentes. Quando atualizar regras aqui, atualize `instructions.md` também.

**Hierarquia de fontes da verdade:**
1. Este `behavior.md` é a verdade arquitetural.
2. `instructions.md` é a verdade operacional (o que o LLM lê).
3. `preprocess.py` é a verdade do clustering.
4. `score.py` é a verdade do engagement_score.

Em caso de conflito entre os 4: este documento manda. Atualizar os outros para alinhar.