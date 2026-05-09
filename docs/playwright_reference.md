# Playwright Reference — Anti-Detecção e Configuração

> Arquivo placeholder. O operador deve adicionar aqui materiais específicos sobre:
> - Técnicas adicionais de anti-detecção para Instagram via Playwright
> - Configuração avançada do perfil Chrome para reutilização de sessão
> - Casos de falha conhecidos e como contorná-los
> - Qualquer ajuste específico observado em produção

## Configuração do Perfil Chrome (Windows)

O caminho padrão do perfil Chrome no Windows é:
```
C:\Users\{SeuUsuario}\AppData\Local\Google\Chrome\User Data
```

Configure `CHROME_PROFILE_PATH` no `.env` com esse caminho.

O Chrome **deve estar fechado** antes de cada execução. O Playwright abre o Chrome de forma exclusiva com o perfil do operador.

## Sessão Persistida

O `launch_persistent_context` do Playwright salva automaticamente o estado da sessão (cookies, localStorage) no diretório do perfil Chrome. Não é necessário nenhum procedimento adicional de salvamento — a sessão é reutilizada automaticamente na próxima execução.

## Sinais de Bloqueio Conhecidos

O sistema detecta automaticamente bloqueios pelas seguintes URLs:
- `checkpoint` — Instagram solicitou verificação
- `challenge` — Instagram suspeita de automação
- `captcha` — Captcha ativo
- `verify` — Verificação pendente
- `accounts/login` — Sessão expirada

Ao detectar qualquer desses sinais: **pare, registre, não tente contornar automaticamente.** Faça login manual no Chrome e execute novamente.
