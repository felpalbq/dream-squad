#!/usr/bin/env python3
"""
Dream Squad — Orchestrator Runner
Coordena as etapas Python do Research: Gemini + Tavily + Ollama Regional + Apify + Manual Input.
Após este script, o Claude Code spawna o sub-agente Scoring/Merge.

Uso:
    python agents/orchestrator/run.py --client-id casadobicho
"""

import os
import sys
import json
import argparse
import subprocess
import yaml
from pathlib import Path
from datetime import datetime

from agents.utils.paths import load_profile, execution_dir
from agents.utils.logging_config import get_logger

ROOT = Path(__file__).parent.parent.parent
logger = get_logger(__name__)


def detect_environment() -> str:
    env = os.environ.get("DREAM_SQUAD_ENV", "").strip().lower()
    if env in ("anthropic", "ollama"):
        return env
    print(
        "[ERRO] DREAM_SQUAD_ENV não definida ou inválida. "
        "Defina como 'anthropic' ou 'ollama' no .env antes de executar.",
        file=sys.stderr,
    )
    sys.exit(1)


def health_check(env: str) -> dict:
    """Verifica disponibilidade de cada fonte antes de iniciar."""
    status: dict[str, bool] = {}

    status["gemini"] = bool(os.environ.get("GEMINI_API_KEY"))

    status["tavily"] = bool(os.environ.get("TAVILY_API_KEY"))
    try:
        import tavily  # noqa
    except ImportError:
        status["tavily"] = False

    if env == "ollama":
        status["ollama"] = bool(os.environ.get("OLLAMA_API_KEY"))
        try:
            import ollama  # noqa
        except ImportError:
            status["ollama"] = False
    else:
        status["ollama"] = False

    status["apify"] = bool(os.environ.get("APIFY_API_TOKEN"))
    try:
        import apify_client  # noqa
    except ImportError:
        status["apify"] = False

    status["manual"] = True  # load.py lida com arquivo ausente silenciosamente

    print("\n[health check] Fontes disponíveis:")
    for fonte, ok in status.items():
        symbol = "OK" if ok else "--"
        print(f"  [{symbol}] {fonte}")

    available = sum(status.values())
    if available == 0:
        print("\n[ERRO] Nenhuma fonte disponível. Verifique .env e dependências.", file=sys.stderr)
        sys.exit(1)

    return status


def _run(cmd: list, label: str) -> dict:
    """
    Executa subprocess e retorna dict de métricas.
    Parseia 'METRICS_JSON: {...}' da última linha de stdout se disponível.
    """
    print(f"\n[{label}] Executando...")
    timeout_s = int(os.environ.get("AGENT_TIMEOUT_S", "120"))
    t0 = datetime.now()
    timed_out = False
    error_msg = None

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            timeout=timeout_s,
        )
        elapsed = round((datetime.now() - t0).total_seconds(), 1)

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            logger.error("[%s] returncode=%d: %s", label, result.returncode, error_msg)
            return {
                "status": "falha",
                "elapsed_s": elapsed,
                "retries": 0,
                "timeout": False,
                "resultados_count": 0,
                "erro": error_msg,
            }

        # Tentar parsear métricas da última linha de stdout
        metrics = {"resultados_count": 0, "retries": 0}
        lines = result.stdout.strip().splitlines()
        for line in reversed(lines):
            if line.startswith("METRICS_JSON:"):
                try:
                    metrics = json.loads(line[len("METRICS_JSON:"):].strip())
                except json.JSONDecodeError:
                    pass
                break

        logger.info("[%s] OK em %.1fs — %d resultados", label, elapsed, metrics.get("resultados_count", 0))
        return {
            "status": "sucesso",
            "elapsed_s": elapsed,
            "retries": metrics.get("retries", 0),
            "timeout": False,
            "resultados_count": metrics.get("resultados_count", 0),
            "erro": None,
        }

    except subprocess.TimeoutExpired:
        elapsed = round((datetime.now() - t0).total_seconds(), 1)
        logger.error("[%s] Timeout após %ds", label, timeout_s)
        return {
            "status": "falha",
            "elapsed_s": elapsed,
            "retries": 0,
            "timeout": True,
            "resultados_count": 0,
            "erro": f"Timeout após {timeout_s}s",
        }
    except Exception as e:
        elapsed = round((datetime.now() - t0).total_seconds(), 1)
        logger.error("[%s] Exceção: %s", label, e)
        return {
            "status": "falha",
            "elapsed_s": elapsed,
            "retries": 0,
            "timeout": False,
            "resultados_count": 0,
            "erro": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Orchestrator Runner")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--skip-gemini", action="store_true")
    parser.add_argument("--skip-tavily", action="store_true")
    parser.add_argument("--skip-ollama-research", action="store_true")
    parser.add_argument("--skip-apify", action="store_true")
    parser.add_argument("--exec-dir", default=None, help="Reusar diretório de execução existente")
    args = parser.parse_args()

    try:
        client = load_profile(args.client_id)
    except FileNotFoundError as e:
        print(f"[ERRO] {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  Dream Squad — Research")
    print(f"  Cliente: {client.get('name', args.client_id)}")
    print(f"  Nicho:   {client.get('niche', '')}")
    print(f"  Data:    {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    env = detect_environment()
    print(f"\n[config] Ambiente: {env}")

    health_status = health_check(env)

    if args.exec_dir:
        exec_d = Path(args.exec_dir)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        exec_d = ROOT / "clients" / args.client_id / "executions" / ts
        exec_d.mkdir(parents=True, exist_ok=True)

    session: dict = {
        "client_id": args.client_id,
        "environment": env,
        "timestamp": datetime.now().isoformat(),
        "exec_dir": str(exec_d),
        "health_check": health_status,
        "stages": {},
        "total_elapsed_s": None,
    }

    t_start = datetime.now()

    # 1. Gemini Researcher
    gemini_output = exec_d / "research" / "gemini_research.yaml"
    if args.skip_gemini:
        session["stages"]["gemini"] = {"status": "pulado"}
    else:
        metrics = _run(
            [sys.executable, "agents/gemini_researcher/research.py",
             "--client-id", args.client_id, "--output", str(gemini_output)],
            "gemini",
        )
        session["stages"]["gemini"] = {**metrics, "output": str(gemini_output)}

    # 2. Tavily Researcher
    tavily_output = exec_d / "research" / "tavily_research.yaml"
    if args.skip_tavily:
        session["stages"]["tavily"] = {"status": "pulado"}
    else:
        metrics = _run(
            [sys.executable, "agents/tavily_researcher/research.py",
             "--client-id", args.client_id, "--output", str(tavily_output)],
            "tavily",
        )
        session["stages"]["tavily"] = {**metrics, "output": str(tavily_output)}

    # 3. Ollama Regional Researcher (apenas ambiente Ollama)
    ollama_output = exec_d / "research" / "ollama_research.yaml"
    if env == "ollama" and not args.skip_ollama_research:
        metrics = _run(
            [sys.executable, "agents/ollama_researcher/research.py",
             "--client-id", args.client_id, "--output", str(ollama_output)],
            "ollama_researcher",
        )
        session["stages"]["ollama_researcher"] = {**metrics, "output": str(ollama_output)}
    else:
        session["stages"]["ollama_researcher"] = {
            "status": "pulado",
            "motivo": "N/A (ambiente anthropic)" if env == "anthropic" else "skip solicitado",
        }

    # 4. Apify Collector
    apify_output = exec_d / "research" / "apify_research.yaml"
    if args.skip_apify:
        session["stages"]["apify"] = {"status": "pulado"}
    else:
        metrics = _run(
            [sys.executable, "agents/apify_collector/collect.py",
             "--client-id", args.client_id, "--output", str(apify_output)],
            "apify",
        )
        session["stages"]["apify"] = {**metrics, "output": str(apify_output)}

    # 5. Manual Input Loader (sempre)
    manual_output = exec_d / "research" / "manual_research.yaml"
    metrics = _run(
        [sys.executable, "agents/manual_input/load.py",
         "--client-id", args.client_id, "--output", str(manual_output)],
        "manual_input",
    )
    session["stages"]["manual_input"] = {**metrics, "output": str(manual_output)}

    session["total_elapsed_s"] = round((datetime.now() - t_start).total_seconds(), 1)

    session_path = exec_d / "session.yaml"
    with open(session_path, "w", encoding="utf-8") as f:
        yaml.dump(session, f, allow_unicode=True, default_flow_style=False)

    print(f"\n{'='*60}")
    print(f"  Etapas Python concluídas em {session['total_elapsed_s']}s")
    print(f"  Diretório de execução: {exec_d}")
    print(f"{'='*60}")

    # Construir lista de inputs disponíveis para Scoring/Merge
    inputs_disponiveis = []
    for fname, label in [
        ("gemini_research.yaml", "Gemini"),
        ("tavily_research.yaml", "Tavily"),
        ("ollama_research.yaml", "Ollama Regional"),
        ("apify_research.yaml", "Apify"),
        ("manual_research.yaml", "Manual Input"),
    ]:
        p = exec_d / "research" / fname
        if p.exists():
            inputs_disponiveis.append(f"     {p}  [{label}]")

    inputs_str = "\n".join(inputs_disponiveis) if inputs_disponiveis else "     (nenhum input disponível)"

    # Instruções para o Claude Code continuar
    if env == "anthropic":
        scoring_instrucao = f"""   Spawne um sub-agente com:
   - Instruções: agents/scoring_merge/instructions.md
   - Cliente: {args.client_id} | Nicho: {client.get('niche', '')}
   - Público: {client.get('audience', {}).get('description', '')}
   - Inputs disponíveis:
{inputs_str}
     clients/{args.client_id}/profile.yaml
   - Output: {exec_d}/research/final_research.md"""
    else:
        scoring_instrucao = f"""   Execute via Ollama:
   - Leia agents/scoring_merge/instructions.md
   - Use ollama.Client.chat() com o modelo {os.environ.get('OLLAMA_MODEL', 'kimi-k2.6:cloud')}
   - Inputs disponíveis:
{inputs_str}
     clients/{args.client_id}/profile.yaml
   - Output: {exec_d}/research/final_research.md"""

    print(f"""
PRÓXIMOS PASSOS (Claude Code):

1. SCORING E MERGE:
{scoring_instrucao}

2. Verifique o resultado em:
   {exec_d}/research/final_research.md
""")

    print("\n--- SESSION_JSON ---")
    print(json.dumps(session, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
