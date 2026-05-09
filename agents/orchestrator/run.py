#!/usr/bin/env python3
"""
Dream Squad — Orchestrator Runner
Coordena as etapas Python do Research: coleta Playwright + Gemini + Ollama Regional.
Após este script, o Claude Code spawna os sub-agentes LLM (Visual Analyzer e Scoring/Merge).

Uso:
    python agents/orchestrator/run.py --client-id casadobicho [--source all] [--skip-gemini] [--skip-ollama-research]
"""

import os
import sys
import argparse
import subprocess
import yaml
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.utils.paths import load_profile, execution_dir

ROOT = Path(__file__).parent.parent.parent


def detect_environment() -> str:
    """Retorna 'anthropic' ou 'ollama'. Solicita confirmação se ambíguo."""
    env = os.environ.get("DREAM_SQUAD_ENV", "").strip().lower()
    if env in ("anthropic", "ollama"):
        return env

    print("\n⚠️  DREAM_SQUAD_ENV não definida.")
    print("Qual ambiente está ativo?")
    print("  1. anthropic (Claude Sonnet nativo)")
    print("  2. ollama    (Kimi K2.6 via Ollama cloud)")
    choice = input("Digite 1 ou 2: ").strip()
    return "ollama" if choice == "2" else "anthropic"


def estimate_cost(num_screenshots: int, env: str) -> float:
    """Estimativa grosseira de custo USD por execução."""
    if env == "anthropic":
        vision_cost = num_screenshots * 0.003
        text_cost = 0.10
        return round(vision_cost + text_cost, 3)
    else:
        return round(num_screenshots * 0.001 + 0.05, 3)


def _run(cmd: list, label: str) -> tuple[bool, str]:
    """Executa subprocess e retorna (sucesso, output)."""
    print(f"\n[{label}] Executando...")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
        )
        if result.returncode != 0:
            print(f"  [ERRO] {result.stderr.strip()}", file=sys.stderr)
            return False, ""
        return True, result.stdout
    except Exception as e:
        print(f"  [ERRO] {e}", file=sys.stderr)
        return False, ""


def count_screenshots(exec_dir: Path) -> int:
    return len(list(exec_dir.rglob("*.png")))


def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Orchestrator Runner")
    parser.add_argument("--client-id", required=True)
    parser.add_argument(
        "--source",
        choices=["instagram", "twitter", "all"],
        default="all",
    )
    parser.add_argument("--skip-gemini", action="store_true")
    parser.add_argument("--skip-ollama-research", action="store_true", help="Pula Ollama Regional Researcher")
    parser.add_argument("--skip-collect", action="store_true", help="Pula coleta (usa execução existente)")
    parser.add_argument("--exec-dir", default=None, help="Diretório de execução existente (para --skip-collect)")
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

    threshold = float(os.environ.get("COST_ALERT_THRESHOLD", "0.50"))

    if args.exec_dir:
        exec_d = Path(args.exec_dir)
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        exec_d = ROOT / "clients" / args.client_id / "executions" / ts
        exec_d.mkdir(parents=True, exist_ok=True)

    session = {
        "client_id": args.client_id,
        "environment": env,
        "timestamp": datetime.now().isoformat(),
        "exec_dir": str(exec_d),
        "stages": {},
    }

    t_start = datetime.now()

    # 1. Coleta Playwright (Instagram + Twitter)
    if not args.skip_collect:
        t0 = datetime.now()
        ok, output = _run(
            [
                sys.executable,
                "agents/playwright_collector/collect.py",
                "--client-id", args.client_id,
                "--source", args.source,
                "--exec-dir", str(exec_d),
            ],
            "playwright",
        )
        elapsed = round((datetime.now() - t0).total_seconds(), 1)
        session["stages"]["playwright"] = {
            "status": "sucesso" if ok else "falha",
            "elapsed_s": elapsed,
        }
        if ok:
            print(f"  [OK] Coleta concluída em {elapsed}s")
        else:
            print(f"  [AVISO] Coleta falhou. Research continua com fontes disponíveis.")

    collection_yaml = exec_d / "collection.yaml"
    collection_data: dict = {}
    if collection_yaml.exists():
        with open(collection_yaml, encoding="utf-8") as f:
            collection_data = yaml.safe_load(f) or {}

    # 2. Gemini Researcher
    if not args.skip_gemini:
        gemini_output = exec_d / "research" / "gemini_research.yaml"
        t0 = datetime.now()
        ok, _ = _run(
            [
                sys.executable,
                "agents/gemini_researcher/research.py",
                "--client-id", args.client_id,
                "--output", str(gemini_output),
            ],
            "gemini",
        )
        elapsed = round((datetime.now() - t0).total_seconds(), 1)
        session["stages"]["gemini"] = {
            "status": "sucesso" if ok else "falha",
            "output": str(gemini_output),
            "elapsed_s": elapsed,
        }
        if ok:
            print(f"  [OK] Gemini research em {elapsed}s → {gemini_output}")

    # 3. Ollama Regional Researcher (apenas ambiente Ollama)
    ollama_research_output = exec_d / "research" / "ollama_research.yaml"
    if env == "ollama" and not args.skip_ollama_research:
        t0 = datetime.now()
        ok, _ = _run(
            [
                sys.executable,
                "agents/ollama_researcher/research.py",
                "--client-id", args.client_id,
                "--output", str(ollama_research_output),
            ],
            "ollama_researcher",
        )
        elapsed = round((datetime.now() - t0).total_seconds(), 1)
        session["stages"]["ollama_researcher"] = {
            "status": "sucesso" if ok else "falha",
            "output": str(ollama_research_output),
            "elapsed_s": elapsed,
        }
        if ok:
            print(f"  [OK] Ollama Regional research em {elapsed}s → {ollama_research_output}")

    # 4. Estimativa de custo
    n_shots = count_screenshots(exec_d)
    estimated_cost = estimate_cost(n_shots, env)
    session["estimated_cost_usd"] = estimated_cost
    session["screenshots_count"] = n_shots

    print(f"\n[custo] {n_shots} screenshots → estimativa: USD {estimated_cost:.3f}")
    if estimated_cost > threshold:
        print(f"\n⚠️  ALERTA: custo estimado (USD {estimated_cost:.3f}) ultrapassa threshold (USD {threshold:.2f})")
        resp = input("Continuar? (s/N): ").strip().lower()
        if resp != "s":
            print("Execução interrompida pelo operador.")
            sys.exit(0)

    session_path = exec_d / "session.yaml"
    with open(session_path, "w", encoding="utf-8") as f:
        yaml.dump(session, f, allow_unicode=True, default_flow_style=False)

    total_elapsed = round((datetime.now() - t_start).total_seconds(), 1)

    print(f"\n{'='*60}")
    print(f"  Etapas Python concluídas em {total_elapsed}s")
    print(f"  Diretório de execução: {exec_d}")
    print(f"{'='*60}")

    # Instruções para o Claude Code continuar
    print(f"""
PRÓXIMOS PASSOS (Claude Code):

1. ANÁLISE VISUAL ({env} mode):""")

    if env == "anthropic":
        print(f"""   Spawne um sub-agente com:
   - Instruções: agents/visual_analyzer/instructions.md
   - Cliente: {args.client_id} | Nicho: {client.get('niche', '')}
   - Público: {client.get('audience', {}).get('description', '')}
   - Analise TODOS os screenshots em: {exec_d}
   - Salve output em: {exec_d}/research/visual_analysis.yaml""")
    else:
        print(f"""   Execute:
   python agents/visual_analyzer/analyze_ollama.py \\
     --client-id {args.client_id} \\
     --collection-yaml {exec_d}/collection.yaml \\
     --output {exec_d}/research/visual_analysis.yaml""")

    if env == "ollama":
        print(f"""
2. PRÉ-PROCESSAMENTO (deduplicação semântica):
   Execute após a análise visual:
   python agents/scoring_merge/preprocess.py \\
     --visual {exec_d}/research/visual_analysis.yaml \\
     --output {exec_d}/research/deduplicated_visual_analysis.yaml""")

    step_num = 3 if env == "ollama" else 2
    dedup_input = f"{exec_d}/research/deduplicated_visual_analysis.yaml (ou visual_analysis.yaml se preprocess falhou)" if env == "ollama" else f"{exec_d}/research/visual_analysis.yaml"
    ollama_input_line = f"\n     {exec_d}/research/ollama_research.yaml (se existir)" if env == "ollama" else ""

    print(f"""
{step_num}. SCORING E MERGE:
   Spawne sub-agente com:
   - Instruções: agents/scoring_merge/instructions.md
   - Inputs:
     {dedup_input}
     {exec_d}/research/gemini_research.yaml{ollama_input_line}
     clients/{args.client_id}/profile.yaml
   - Output: {exec_d}/research/final_research.md

{step_num + 1}. Verifique o resultado em:
   {exec_d}/research/final_research.md
""")

    import json
    print("\n--- SESSION_JSON ---")
    print(json.dumps(session, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
