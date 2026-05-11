#!/usr/bin/env python3
"""
Dream Squad — Orchestrator Runner
Coordena as etapas Python do Research: Gemini + Tavily + Ollama Regional + Apify + Manual Input.
Após este script, o Claude Code spawna o sub-agente Scoring/Merge.

Uso:
    python agents/orchestrator/run.py --client-id casadobicho
"""

import os
import re
import sys
import json
import unicodedata
import argparse
import subprocess
import yaml
from pathlib import Path
from datetime import datetime

from agents.utils.paths import load_profile, execution_dir, client_dir
from agents.utils.logging_config import get_logger

ROOT = Path(__file__).parent.parent.parent
logger = get_logger(__name__)


# --- Cooldown de pautas ---

def _load_used_topics(client_id: str) -> list[dict]:
    path = client_dir(client_id) / "research" / "used_topics.json"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _cleanup_used_topics(topics: list[dict]) -> list[dict]:
    """Remove entradas com mais de 14 dias."""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=14)
    cleaned = []
    for t in topics:
        try:
            d = date.fromisoformat(t.get("data_uso", ""))
            if d >= cutoff:
                cleaned.append(t)
        except (ValueError, TypeError):
            continue
    return cleaned


def _save_used_topics(client_id: str, topics: list[dict]) -> None:
    path = client_dir(client_id) / "research" / "used_topics.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(topics, f, ensure_ascii=False, indent=2)


def _extract_topics_from_research(exec_dir: Path, client_id: str) -> list[dict]:
    """Extrai temas dos YAMLs de pesquisa para o cooldown."""
    research_dir = exec_dir / "research"
    if not research_dir.exists():
        return []
    files = [
        "gemini_research.yaml",
        "tavily_research.yaml",
        "ollama_research.yaml",
        "apify_research.yaml",
        "manual_research.yaml",
    ]
    keys = [
        "pesquisa_gemini",
        "pesquisa_tavily",
        "pesquisa_ollama_regional",
        "pesquisa_apify",
        "manual_research",
    ]
    topics = []
    seen = set()
    today = datetime.now().strftime("%Y-%m-%d")
    for fname, key in zip(files, keys):
        p = research_dir / fname
        if not p.exists():
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            container = data.get(key, {})
            for r in container.get("resultados", []):
                tema = r.get("tema", "")
                if not tema or tema in seen:
                    continue
                seen.add(tema)
                # Normalização simples para comparação futura
                normalizado = (
                    unicodedata.normalize("NFD", tema.lower())
                    .encode("ascii", "ignore")
                    .decode("ascii")
                )
                normalizado = " ".join(
                    w for w in re.sub(r"[^\w\s]", " ", normalizado).split()
                    if len(w) > 2
                )
                topics.append({
                    "tema": tema,
                    "tema_normalizado": normalizado,
                    "data_uso": today,
                    "execution_dir": str(exec_dir),
                })
        except Exception:
            continue
    return topics


def _load_pulse() -> str:
    """Lê pulse.md da raiz do projeto, se existir."""
    pulse_path = ROOT / "pulse.md"
    if pulse_path.exists():
        return pulse_path.read_text(encoding="utf-8").strip()
    return ""


def health_check() -> dict:
    """Verifica disponibilidade de cada fonte antes de iniciar."""
    status: dict[str, bool] = {}

    status["gemini"] = bool(os.environ.get("GEMINI_API_KEY"))

    status["tavily"] = bool(os.environ.get("TAVILY_API_KEY"))
    try:
        import tavily  # noqa
    except ImportError:
        status["tavily"] = False

    status["ollama"] = bool(os.environ.get("OLLAMA_API_KEY"))
    if status["ollama"]:
        try:
            import ollama  # noqa
        except ImportError:
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

    pulse = _load_pulse()
    if pulse:
        os.environ["DREAM_SQUAD_PULSE"] = pulse
        print(f"\n[pulse] Contexto manual carregado ({len(pulse)} chars)")

    health_status = health_check()

    if args.exec_dir:
        exec_d = Path(args.exec_dir)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        exec_d = ROOT / "clients" / args.client_id / "executions" / ts
        exec_d.mkdir(parents=True, exist_ok=True)

    session: dict = {
        "client_id": args.client_id,
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

    # 3. Ollama Regional Researcher (disponível em qualquer ambiente, desde que OLLAMA_API_KEY esteja configurada)
    ollama_output = exec_d / "research" / "ollama_research.yaml"
    if health_status.get("ollama") and not args.skip_ollama_research:
        metrics = _run(
            [sys.executable, "agents/ollama_researcher/research.py",
             "--client-id", args.client_id, "--output", str(ollama_output)],
            "ollama_researcher",
        )
        session["stages"]["ollama_researcher"] = {**metrics, "output": str(ollama_output)}
    else:
        motivo = "skip solicitado" if args.skip_ollama_research else "OLLAMA_API_KEY não configurada"
        session["stages"]["ollama_researcher"] = {"status": "pulado", "motivo": motivo}

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

    # 6. Pré-clustering determinístico (antes do Scoring/Merge)
    clusters_output = exec_d / "research" / "clusters_preprocessed.yaml"
    try:
        subprocess.run(
            [sys.executable, "agents/scoring_merge/preprocess.py",
             "--exec-dir", str(exec_d), "--output", str(clusters_output)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
            timeout=30,
            check=True,
        )
        logger.info("Pré-clustering OK: %s", clusters_output)
    except Exception as e:
        logger.warning("Pré-clustering falhou: %s", e)

    # Cooldown: carregar histórico de pautas usadas e copiar para exec_dir
    used_topics = _load_used_topics(args.client_id)
    used_topics = _cleanup_used_topics(used_topics)
    used_topics_path = exec_d / "research" / "used_topics.json"
    with open(used_topics_path, "w", encoding="utf-8") as f:
        json.dump(used_topics, f, ensure_ascii=False, indent=2)

    # Extrair e salvar temas desta execução no histórico global
    new_topics = _extract_topics_from_research(exec_d, args.client_id)
    used_topics.extend(new_topics)
    _save_used_topics(args.client_id, used_topics)

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
        ("clusters_preprocessed.yaml", "Pré-clustering"),
        ("used_topics.json", "Cooldown de Pautas"),
    ]:
        p = exec_d / "research" / fname
        if p.exists():
            inputs_disponiveis.append(f"     {p}  [{label}]")

    inputs_str = "\n".join(inputs_disponiveis) if inputs_disponiveis else "     (nenhum input disponível)"

    # Instruções para o Claude Code continuar com o sub-agente Scoring/Merge
    scoring_instrucao = f"""   Spawne um sub-agente com:
   - Instruções: agents/scoring_merge/instructions.md
   - Cliente: {args.client_id} | Nicho: {client.get('niche', '')}
   - Público: {client.get('audience', {}).get('description', '')}
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
