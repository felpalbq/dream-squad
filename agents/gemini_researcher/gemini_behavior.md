# Gemini Researcher — Comportamento e Responsabilidades

> Sub-agente Python que executa deep research nacional via Google Gemini API. Lê o `profile.yaml` do cliente, gera prompt rotativo por eixo editorial, chama a API com retry, valida o YAML retornado e grava em `gemini_research.yaml`.
>
> **Localização sugerida:** `agents/gemini_researcher/gemini_behavior.md`
> **Implementação:** `agents/gemini_researcher/research.py`

---

## 1. Identidade e papel no sistema

O Gemini Researcher é a fonte primária de **tendências nacionais com profundidade**. Diferente do Tavily (web search amplo) e do Ollama (regional), o Gemini deve trazer:

- Estudos e pesquisas com dados verificáveis.
- Tendências comportamentais ou culturais emergentes.
- Reportagens recentes com gancho editorial.
- Comportamentos sociais em alta no Brasil.
- Oportunidades sazonais específicas.

**Não é um agregador de manchetes.** É um pesquisador com instrução para conectar nicho + público-alvo de forma criativa.

---

## 2. Trigger e contexto inicial

### 2.1. Como é invocado

```bash
python agents/gemini_researcher/research.py --client-id <id> --output <path>
```

Invocado pelo orquestrador como subprocess. Nunca diretamente.

### 2.2. Variáveis de ambiente requeridas

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GEMINI_API_KEY` | Sim | Chave da API. Ausência → escreve YAML de erro e sai com `exit 0` (falha silenciosa). |
| `GEMINI_MODEL` | Não | Default: `gemini-2.5-flash-lite`. |
| `DREAM_SQUAD_PULSE` | Não | Conteúdo de `pulse.md`, injetado no prompt quando há contexto agudo. |

### 2.3. Pré-condições

1. `profile.yaml` do cliente carregado via `load_profile()`.
2. `niche`, `audience.description`, `location` extraídos.
3. Contexto sazonal calculado via `seasonal_context()` (utilitário compartilhado).
4. ISO week atual calculada para rotação determinística de queries.

---

## 3. Comportamento de pesquisa

### 3.1. Eixos editoriais

Cada execução escolhe `gemini_max_queries` queries (default: 1, podendo ser 2-3) entre os eixos abaixo. A escolha é determinística baseada em `hash(client_id + ISO_week)`, garantindo:

- Mesmo cliente, mesma semana → mesmas queries (consistência).
- Mesmo cliente, semanas diferentes → queries diferentes (variação).

| Eixo | Foco | Quando ativar |
|---|---|---|
| `tendencia` | Tendências comportamentais/culturais | Sempre |
| `estudo_dados` | Pesquisas com dados verificáveis | Sempre |
| `noticia_recente` | Reportagens com gancho editorial | Sempre |
| `sazonal` | Oportunidades de timing | Quando há janela sazonal ativa |
| `polarizacao` | Temas com fricção genuína | Quando `voice.avoid` permite |
| `regional_nacional` | Recortes regionais com leitura nacional | Default para clientes BA |

### 3.2. Construção do prompt

Template fixo + injeção dinâmica de:
- `niche`, `audience`, `location`, `date`, `seasonal`
- `extra_context` do `profile.research.gemini_context`
- `pulse_content` quando `DREAM_SQUAD_PULSE` está setada
- `eixos_ativos` (lista dos eixos escolhidos para esta execução)
- `manual_keywords` extraídas do `manual_input.yaml`, se houver entradas válidas

### 3.3. Critério editorial mais importante

**Conexão indireta ganha de conexão direta.** O prompt instrui explicitamente:

> Prefira temas que conectam o PÚBLICO-ALVO ao nicho de forma indireta e criativa.
> Exemplo: para veterinária, "mães de pet — mulheres que tratam pets como filhos" vale mais do que "vacinação animal".

Esse é o critério que diferencia o output do Gemini de uma busca trivial.

### 3.4. Sinais de fonte (novo)

Para cada resultado, o Gemini DEVE preencher (quando aplicável):

```yaml
- tema: "..."
  titulo: "..."
  ...
  sinal_friccao: "polarização tutor pet vs ambientalistas"   # opcional
  sinal_transformacao: "antropomorfização crescente do pet"   # opcional
  sinal_timing: "trending_now" | "weekly_news" | "seasonal" | "evergreen"
```

Esses sinais são âncoras para o Scoring/Merge não inventar `friccao_central` e `transformacao` no output final.

---

## 4. Retorno esperado

### 4.1. Schema (validação Pydantic)

Output gravado em `<exec_dir>/research/gemini_research.yaml`:

```yaml
pesquisa_gemini:
  client_id: "casadobicho"
  nicho: "veterinária"
  data_pesquisa: "2026-05-09"
  resultados:
    - tema: "Mães de pet"
      titulo: "Pesquisa Globo: 78% das mulheres acima de 30 tratam pets como filhos"
      descricao: >
        Estudo do Globo Reporter de abril/2026 mapeia comportamento de
        antropomorfização crescente. Dado central: 78% das mulheres 30-50
        chamam pets de "filhos". Conexão direta com público-alvo da clínica.
      url_fonte: "https://g1.globo.com/..."
      data_hora: "2026-04-22"
      relevancia_nicho: 9
      origem: "gemini"
      sinal_friccao: null
      sinal_transformacao: "pet como filho — substituição parcial do desejo de maternidade"
      sinal_timing: "trending_now"
```

### 4.2. Quantidade de resultados esperada

- Mínimo: 3 resultados por execução (se a API responder com sucesso).
- Máximo: 8 resultados (limite do prompt).
- Se < 3: registrar warning, mas gravar normalmente.

### 4.3. Falhas

| Situação | Ação |
|---|---|
| API key ausente | YAML de erro, exit 0 |
| Lib `google-genai` não instalada | YAML de erro, exit 0 |
| API timeout/error após 3 retries | YAML de erro, exit 0 |
| YAML retornado pelo modelo é inválido | YAML de erro, exit 0, log do raw text |
| Resposta sem campo `pesquisa_gemini` | YAML de erro, exit 0 |

**Em todos os casos de falha:** o pipeline continua. O Scoring/Merge consegue funcionar sem esta fonte.

---

## 5. Retry e timeouts

- **Retry:** 3 tentativas com backoff exponencial (2s, 4s, 8s) via `with_retry`.
- **Timeout por tentativa:** governado pelo timeout do orquestrador (default 120s).
- **Comportamento em rate limit:** o decorator `with_retry` trata como exceção qualquer e dorme. Se 3 tentativas falharem, registra falha e aceita.

---

## 6. Métricas reportadas

Última linha do stdout:
```
METRICS_JSON: {"resultados_count": <int>, "retries": <int>}
```

Logs em stderr:
```
[INFO] Gemini: 6 resultados → /clients/casadobicho/executions/.../gemini_research.yaml
```

---

## 7. O que o Gemini Researcher NUNCA faz

- ❌ Não modifica `profile.yaml`.
- ❌ Não consulta outras fontes (Tavily, Ollama, Apify).
- ❌ Não decide se a pauta é boa o suficiente — só extrai e reporta.
- ❌ Não inventa URLs quando a fonte real não tem.
- ❌ Não reproduz texto literal de artigos com mais de 15 palavras (compliance).
- ❌ Não loga `GEMINI_API_KEY`.
- ❌ Não escreve em outro arquivo que não seja o `--output`.

---

## 8. Calibração de qualidade

### Critérios para um output considerado "bom"

1. **Pelo menos 60% dos resultados têm URL verificável.**
2. **Pelo menos 1 resultado tem `sinal_transformacao` ou `sinal_friccao` preenchido.**
3. **Os temas variam entre eixos editoriais — não são todos do mesmo tipo.**
4. **Nenhum resultado viola `voice.avoid` do cliente** (esta validação é refeita pelo Scoring/Merge, mas o Gemini deve já tentar respeitar).
5. **Sazonalidade é refletida quando há janela ativa.**

### Sinal de output ruim

- Todos os resultados são genéricos ("dicas para veterinários", "como cuidar do pet").
- Nenhum resultado tem dado quantitativo ou fonte verificável.
- Resultados se repetem semana a semana — sintoma de prompt sem rotação.
- `relevancia_nicho` é sempre 7 ou 8 — sintoma de modelo "preguiçoso".

Quando esses sinais aparecem, **revisar o prompt**, não o cliente.

---

## 9. Evolução futura (não implementar agora)

- Cache de resultados por (client_id, ISO_week) — evita queimar tokens em retries do operador.
- Detecção de "déjà vu" — se 60%+ dos resultados de hoje são iguais aos da semana passada, alerta.
- Rotação de modelos (Gemini Flash vs Gemini Pro) por eixo — Pro para `estudo_dados`, Flash para `noticia_recente`.

Por enquanto, escopo é manter o agente simples e funcional.