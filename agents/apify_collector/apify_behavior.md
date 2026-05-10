# Apify Collector — Comportamento e Responsabilidades

> Sub-agente Python que coleta posts públicos de perfis de referência do Instagram via Apify (`apify/instagram-scraper`). Não usa autenticação. Calcula `engagement_score` localmente para cada post coletado, gerando evidência empírica de engajamento real para o Scoring/Merge.
>
> **Localização sugerida:** `agents/apify_collector/apify_behavior.md`
> **Implementação:** `agents/apify_collector/collect.py`

---

## 1. Identidade e papel no sistema

O Apify Collector é a **única fonte do sistema com evidência empírica de engajamento real**. Enquanto Gemini, Tavily e Ollama trazem temas e tendências, o Apify traz:

- Posts reais de perfis de referência do nicho.
- Métricas de engajamento (curtidas, comentários, visualizações).
- Tipo de post (Image, Video, Sidecar/carrossel).
- Hashtags utilizadas.
- Data de publicação.
- **`engagement_score` calculado** = engajamento total / horas desde publicação.

Esse score é a métrica mais confiável que o Scoring/Merge tem para validar (ou contradizer) "potencial de engajamento" das pautas das outras fontes.

---

## 2. Trigger e contexto inicial

### 2.1. Como é invocado

```bash
python agents/apify_collector/collect.py --client-id <id> --output <path>
```

### 2.2. Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `APIFY_API_TOKEN` | Sim | Sem ele, fonte é pulada silenciosamente. |

### 2.3. Configuração via `profile.yaml`

```yaml
research:
  apify_max_crawl_requests: 30        # limite HTTP/segurança (não controla custo)
  apify_max_posts_per_profile: 5      # CONTROLA CUSTO — $0,001/post

instagram_reference_profiles:
  - url: "https://www.instagram.com/handle1/"
    handle: "@handle1"
    relevance: "descrição da relevância"
  - url: "..."
    handle: "..."
    relevance: "..."
```

### 2.4. Pré-condições

1. `APIFY_API_TOKEN` definido.
2. Lib `apify-client>=1.7.0` importável.
3. `profile.instagram_reference_profiles` não vazio.
4. Cada perfil tem `handle` válido (não vazio após `lstrip("@")`).

Se qualquer pré-condição falhar: YAML de erro + exit 0 (falha silenciosa).

---

## 3. Comportamento de coleta

### 3.1. Loop por perfil

Para cada `handle` na lista:

1. Monta `directUrls` com a URL canônica do perfil.
2. Chama `actor("apify/instagram-scraper").call()` com:
   - `resultsType: "posts"`
   - `resultsLimit: apify_max_posts_per_profile`
   - `maxRequestsPerCrawl: apify_max_crawl_requests`
3. Itera o dataset retornado.
4. Para cada `item`:
   - Constrói `tema` via `_extract_tema()`.
   - Constrói `titulo` via `_build_titulo()`.
   - Limpa caption via `_clean_caption()`.
   - Calcula `engagement_score` via `score_from_dict()` de `agents/scoring_merge/score.py`.
   - Anexa ao `resultados`.
5. Falhas individuais por perfil são logadas mas não interrompem os demais.

### 3.2. Construção de `tema`

Não usar primeiros 80 chars literalmente. Em vez disso:

```python
def _extract_tema(caption: str) -> str:
    """Primeira frase ou primeiras hashtags."""
    first_sentence = re.split(r"[.!?\n]", caption.strip(), maxsplit=1)[0]
    if 20 <= len(first_sentence) <= 80:
        return first_sentence.strip()
    hashtags = re.findall(r"#(\w+)", caption)
    return " · ".join(hashtags[:3]) if hashtags else caption[:80].strip()
```

Por que isso importa: o `tema` é o que o Scoring/Merge usa para deduplicar e identificar conteúdo. "🐶❤️ Veja só esse..." não é um tema. "Antes e depois da castração" é.

### 3.3. Construção de `titulo`

Tem que ser distintivo entre posts do mesmo perfil:

```python
def _build_titulo(handle: str, item: dict) -> str:
    date_str = str(item.get("timestamp", ""))[:10]
    post_type = item.get("type", "Post")
    return f"{post_type} de @{handle} ({date_str})"
```

Resultado: `"Video de @anacarolinalanavet (2026-04-22)"`.

### 3.4. Limpeza de caption

```python
def _clean_caption(caption: str) -> str:
    cleaned = re.sub(r"^[^\w]+", "", caption)        # remove emojis/símbolos do início
    cleaned = re.sub(r"\s+", " ", cleaned).strip()   # normaliza espaços
    return cleaned[:400]
```

### 3.5. Cálculo de engagement_score

Importa de `agents.scoring_merge.score`:

```python
from agents.scoring_merge.score import score_from_dict

post_dict = {
    "curtidas": item.get("likesCount", 0),
    "comentarios": item.get("commentsCount", 0),
    "data_postagem": str(item.get("timestamp", "")),
}
engagement_score = score_from_dict(post_dict, "instagram")
```

A fórmula em `score.py`:
- `engagement = curtidas + comentarios × 3`
- `score = engagement / max(horas_desde_post, 1.0)`
- Sem data de postagem: fallback para `(curtidas + comentarios × 3) / 1000`.

### 3.6. Erros de permissão vs erros de rede

```python
_PERMISSION_ERRORS = ("permission", "forbidden", "unauthorized", "plan", "quota")
```

- **Erro de permissão:** plano insuficiente, conta bloqueada, etc. → log error, **sem retry**, continua próximo perfil.
- **Erro de rede:** timeout, conexão recusada → retry 2x via `with_retry`, depois aceita falha.

Distinguir os dois evita queimar tentativas em problemas que retry não resolve.

---

## 4. Retorno esperado

### 4.1. Schema

Output em `<exec_dir>/research/apify_research.yaml`:

```yaml
pesquisa_apify:
  client_id: "casadobicho"
  nicho: "veterinária"
  data_pesquisa: "2026-05-09"
  resultados:
    - tema: "Antes e depois da castração da minha gata"
      titulo: "Video de @anacarolinalanavet (2026-04-28)"
      descricao: >
        Vídeo mostra recuperação pós-cirúrgica em 7 dias. Comentários
        cheios de relatos similares de tutoras. Engajamento alto.
      url_fonte: "https://instagram.com/p/abcdef/"
      data_hora: "2026-04-28"
      relevancia_nicho: null            # ← Apify não atribui
      origem: "apify"
      perfil: "@anacarolinalanavet"
      curtidas: 4302
      comentarios: 287
      engagement_score: 187.4           # ← novo, calculado localmente
      post_type: "Video"
      hashtags: ["castracao", "veterinaria", "petlovers"]
```

### 4.2. Quantidade

- `len(reference_profiles) × apify_max_posts_per_profile` posts máximos.
- Para Casa do Bicho com 2 perfis × 5 posts = 10 posts.
- Para Ed Telas com 3 perfis × 5 posts = 15 posts.

### 4.3. Falhas

| Situação | Ação |
|---|---|
| `APIFY_API_TOKEN` ausente | YAML de erro, exit 0 |
| Lib `apify-client` ausente | YAML de erro, exit 0 |
| `instagram_reference_profiles` vazio | YAML de erro, exit 0 |
| Perfil individual com erro de rede | Log warning, retry 2x, depois pula |
| Perfil individual com erro de permissão | Log error, **sem retry**, pula |
| Actor retorna 0 itens (perfil privado/não existe) | Log info, continua próximo |
| Validação Pydantic falha | YAML de erro |

---

## 5. Controle de custo

### 5.1. Plano gratuito Apify

- $5 USD/mês (renova mensalmente).
- `apify/instagram-scraper`: $0,001/post (público).

### 5.2. Cálculo

Cenário: 6 clientes × 2 perfis (média) × 5 posts × 8 runs/mês = **480 posts/mês = $0,48/mês**.

Margem confortável (~$4,52). Custo escala linearmente com `apify_max_posts_per_profile`.

### 5.3. Alavancas

- **Reduzir `apify_max_posts_per_profile`** → impacto direto no custo.
- **Reduzir `instagram_reference_profiles`** → impacto direto.
- **Aumentar `apify_max_crawl_requests`** → NÃO afeta custo. Só protege contra runaway HTTP.

### 5.4. Sinais de custo descontrolado

- Run de Apify demora >60s para um perfil — pode indicar que `maxRequestsPerCrawl` está sendo atingido.
- Posts retornados são menos do que `apify_max_posts_per_profile` consistentemente — perfil pode ter pouco conteúdo recente, considerar trocar referência.

---

## 6. Métricas reportadas

```
METRICS_JSON: {"resultados_count": <int>, "retries": <int>}
```

Logs:
```
[INFO] Apify OK: @anacarolinalanavet — 5 posts
[INFO] Apify OK: @alinecrunflivet — 5 posts
[INFO] Apify: 10 posts → /clients/casadobicho/executions/.../apify_research.yaml
```

---

## 7. O que o Apify Collector NUNCA faz

- ❌ Não usa autenticação (perfis privados são ignorados).
- ❌ Não faz login programático no Instagram.
- ❌ Não armazena cookies ou sessão.
- ❌ Não atribui `relevancia_nicho` (deixa para o Scoring/Merge).
- ❌ Não interpreta semântica do post (só extrai estrutura).
- ❌ Não baixa imagens ou vídeos — só metadata.
- ❌ Não consulta perfis fora de `instagram_reference_profiles`.

---

## 8. Calibração de qualidade

### Output bom

1. **Todos os perfis listados retornaram pelo menos 1 post.**
2. **Posts têm `engagement_score > 5`** na maioria (sinal de perfis ativos).
3. **`tema` é descritivo**, não fragmento de emoji ou hashtag única.
4. **Mistura de `post_type`** — não 100% Image se o nicho típico tem vídeos.

### Sinal de output ruim

- Algum perfil retornou 0 posts → revisar URL ou trocar referência.
- `engagement_score` médio < 1 → perfis "mortos", trocar referências.
- Caption truncada no meio de palavra (ex: "como cuid") → `_clean_caption` precisa de melhoria.
- Posts muito antigos (>90 dias) — pode indicar perfil que parou de postar.

---

## 9. Limpeza ética da coleta

### 9.1. Apenas perfis públicos

O agente NÃO faz login. Se um perfil de `instagram_reference_profiles` virou privado, o actor retornará vazio. **Não tentar contornar.**

### 9.2. Compliance

- Os dados coletados são públicos por definição (perfis abertos).
- O Scoring/Merge **nunca reproduz literalmente** caption de post (limite de 15 palavras, regra global do sistema).
- O `descricao` truncada em 400 chars é apenas para análise interna — nunca aparece no `final_research.md` sem reescrita.

### 9.3. Operator notes

Se o operador adicionar perfis de concorrentes diretos do cliente como referência, o agente coleta normalmente. **Recomendação editorial:** evitar concorrentes diretos como referência — usar referências de outras regiões ou nichos adjacentes para evitar repetição de pautas que o concorrente já queimou.

---

## 10. Evolução futura

- Coleta de Reels separadamente (já que `apify/instagram-scraper` retorna em `posts`).
- Detecção de carrosséis e extração de slides.
- Análise de comentários (top 5 comentários como sinal adicional).
- Fallback para outros actors públicos do Apify se `instagram-scraper` der throttle.

Por enquanto, foco é simplicidade, custo controlado e qualidade do `engagement_score`.