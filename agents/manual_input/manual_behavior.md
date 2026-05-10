# Manual Input Loader — Comportamento e Responsabilidades

> Sub-agente Python que lê o `manual_input.yaml` editado pelo operador antes de cada execução. Filtra entradas de template não preenchidas e entradas com `valido_ate` expirado. Propaga `prioridade_operador` para o Scoring/Merge.
>
> **Localização sugerida:** `agents/manual_input/manual_behavior.md`
> **Implementação:** `agents/manual_input/load.py`

---

## 1. Identidade e papel no sistema

O Manual Input Loader é a **voz do operador no pipeline**. Diferente das outras 4 fontes (que são automáticas), o Manual Input é alimentado manualmente pelo estrategista antes de cada execução, quando há contexto local privilegiado que nenhuma fonte automatizada captura.

Casos típicos:
- Feira de adoção amanhã no Parque Municipal (Casa do Bicho).
- Cliente fechou parceria com hotel novo (Iate Clube).
- Aconteceu um caso viral no bairro relevante para o nicho.
- Operador identificou tema sazonal específico que está fora dos tags pré-definidos.

**É a fonte com maior peso editorial relativo:** quando o operador escreve, ele já filtrou. Não precisa que o sistema duvide.

---

## 2. Trigger e contexto inicial

### 2.1. Como é invocado

```bash
python agents/manual_input/load.py --client-id <id> --output <path>
```

Sempre invocado pelo orquestrador, mesmo quando `manual_input.yaml` está vazio ou ausente.

### 2.2. Variáveis de ambiente

Nenhuma específica. Não consome credenciais.

### 2.3. Pré-condições

1. Diretório `clients/{client_id}/` existe.
2. Se `manual_input.yaml` não existir, o agente **cria automaticamente** com o template padrão.

---

## 3. Comportamento

### 3.1. Fluxo

1. Verifica se `clients/{client_id}/manual_input.yaml` existe.
2. **Se não existe:** cria com `MANUAL_INPUT_TEMPLATE` (template comentado vazio). Loga info.
3. Lê o YAML.
4. Itera `resultados`:
   - Pula entradas iguais ao template não preenchido (ex: `tema == "Nome curto do tema"`).
   - Pula entradas com `valido_ate < hoje`.
5. Propaga campos relevantes para o output: `tema`, `titulo`, `descricao`, `url_fonte`, `data_hora`, `relevancia_nicho`, `origem`, `prioridade_operador`.
6. Remove `valido_ate` do output (campo de controle interno, não relevante para Scoring/Merge).
7. Grava `manual_research.yaml`.

### 3.2. Detecção de template não preenchido

```python
def _is_template(entry: dict) -> bool:
    return entry.get("tema", "") == "Nome curto do tema"
```

A heurística é simples: se o `tema` ainda é a string literal do template, o operador esqueceu de editar.

### 3.3. Detecção de entrada expirada

```python
def _is_expired(entry: dict) -> bool:
    valido_ate = entry.get("valido_ate")
    if not valido_ate:
        return False
    try:
        expiry = date.fromisoformat(str(valido_ate))
        return date.today() > expiry
    except (ValueError, TypeError):
        return False  # data inválida = não expira
```

Entradas expiradas são silenciosamente ignoradas. Não dá erro, não pede para o operador remover. Manualmente, o operador limpa quando quiser — o sistema é tolerante.

### 3.4. `prioridade_operador` (novo campo)

Adicionado ao template e ao schema:

```yaml
resultados:
  - tema: "..."
    relevancia_nicho: 9
    prioridade_operador: "alta"   # alta | normal — default: normal
```

**Comportamento esperado:**
- `alta` → o Scoring/Merge **garante** que esta pauta entre no top final, mesmo com score abaixo do threshold.
- `normal` (ou ausente) → tratamento padrão.

O Manual Input Loader propaga literalmente. A interpretação é responsabilidade do Scoring/Merge (ver `agents/scoring_merge/behavior.md` Seção 5.3).

### 3.5. Template padrão atualizado

```yaml
# manual_input.yaml — Edite antes de executar quando houver eventos relevantes.
# Deixe resultados: [] se não houver nada a adicionar.
# O campo valido_ate (opcional) define até quando esta entrada é válida.
# Entradas expiradas são ignoradas automaticamente.

resultados:
  - tema: "Nome curto do tema"
    titulo: "Descrição do evento ou contexto"
    descricao: >
      Contexto detalhado: o que aconteceu, por que é relevante para o nicho,
      qual a conexão com o público-alvo.
    url_fonte: ""                # opcional
    data_hora: "YYYY-MM-DD"
    relevancia_nicho: 8          # 0-10
    origem: "manual"
    prioridade_operador: "normal"  # alta | normal
    # valido_ate: "YYYY-MM-DD"   # opcional — deixe comentado para sem expiração
```

---

## 4. Retorno esperado

### 4.1. Schema

Output em `<exec_dir>/research/manual_research.yaml`:

```yaml
manual_research:
  client_id: "casadobicho"
  data_pesquisa: "2026-05-09"
  resultados:
    - tema: "Feira de Adoção de Pets Ilhéus"
      titulo: "Feira de adoção no Parque Municipal — sábado 11/05"
      descricao: >
        Evento de adoção organizado pelo grupo SOS Pets Ilhéus no Parque
        Municipal. Alta visibilidade na comunidade, público-alvo idêntico.
      url_fonte: ""
      data_hora: "2026-05-08"
      relevancia_nicho: 9
      origem: "manual"
      prioridade_operador: "alta"
```

Quando vazio:

```yaml
manual_research:
  client_id: "casadobicho"
  data_pesquisa: "2026-05-09"
  resultados: []
```

### 4.2. Quantidade

- 0-N entradas. Não há limite, mas mais de 5 por execução é incomum.

### 4.3. Falhas

| Situação | Ação |
|---|---|
| YAML mal formado | Log warning, escreve `manual_research.yaml` com `resultados: []`, exit 0 |
| Arquivo não existe | Cria template, processa como vazio |
| Todas entradas são template | Output com `resultados: []` |
| Todas entradas estão expiradas | Output com `resultados: []` |

**Nunca falha hard.** É a fonte que deve ser mais resiliente — operador errar a edição não pode travar o pipeline.

---

## 5. Métricas reportadas

```
METRICS_JSON: {"resultados_count": <int>, "retries": <int>}
```

Logs:
```
[INFO] Manual input: 1 entrada(s) ignorada(s) (template ou expirada)
[INFO] Manual input: 2 entradas → /clients/casadobicho/executions/.../manual_research.yaml
```

---

## 6. O que o Manual Input Loader NUNCA faz

- ❌ Não modifica `manual_input.yaml` do operador (exceto criação inicial do template).
- ❌ Não interpreta semântica das entradas.
- ❌ Não atribui scores (deixa `relevancia_nicho` que o operador colocou).
- ❌ Não consulta APIs externas.
- ❌ Não notifica quando o operador esqueceu de editar (silencioso).
- ❌ Não bloqueia entradas com `prioridade_operador: alta` mesmo se o tema for polêmico — confia no operador.

---

## 7. Relação com o operador

### 7.1. Workflow esperado

1. Antes de cada execução, operador abre `clients/{client_id}/manual_input.yaml`.
2. Se há evento relevante: edita, preenche, salva.
3. Se não há nada novo: deixa `resultados: []` ou só com entradas válidas anteriores.
4. Roda o orquestrador.

### 7.2. Operador NÃO precisa limpar entradas expiradas

O sistema filtra automaticamente. Operador pode acumular histórico no arquivo se quiser referência.

### 7.3. Quando NÃO usar Manual Input

- Tendências nacionais → use Gemini.
- Manchetes recentes → use Tavily ou Ollama Regional.
- Engajamento de perfis de referência → Apify.

Manual Input é para **conhecimento privilegiado local que nenhum sistema captura.**

---

## 8. Calibração de qualidade

### Boa entrada

```yaml
- tema: "Greve dos petshops em Itabuna"
  titulo: "Petshops fecham por 3 dias por reajuste de preço da ração"
  descricao: >
    Sindicato local divulgou greve de 3 dias começando 12/05. Tutores
    podem ter dificuldade de acesso a ração — gancho para clínica
    veterinária reforçar serviço de venda direta de ração premium.
  data_hora: "2026-05-09"
  relevancia_nicho: 9
  prioridade_operador: "alta"
  valido_ate: "2026-05-15"
```

### Entrada ruim

```yaml
- tema: "Importante"
  titulo: "Coisas legais"
  descricao: "Falar sobre coisas legais para o cliente"
  relevancia_nicho: 10
  prioridade_operador: "alta"
```

Sem contexto, sem timing, sem conexão clara. O Scoring/Merge consegue trabalhar com isso, mas vai gerar output ruim.

**Regra prática:** se o operador não consegue justificar `descricao` em 3 linhas, a entrada provavelmente não é forte o suficiente para virar pauta.

---

## 9. Evolução futura

- Múltiplos arquivos por cliente (ex: `manual_input_evento_x.yaml` para entradas com vencimento curto).
- Auto-arquivamento de entradas expiradas (mover para `manual_input_archive.yaml`).
- Validação de formato no momento da leitura (avisar operador sobre campos faltando).

Por enquanto, escopo é simplicidade e tolerância a erros do operador.