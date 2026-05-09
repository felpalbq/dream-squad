#!/usr/bin/env python3
"""
Dream Squad — Visual Analyzer (modo Ollama/Kimi K2.6)
Análise multimodal de screenshots via API Ollama cloud com raciocínio explícito (think=True).
Usado apenas quando DREAM_SQUAD_ENV=ollama.
"""

import base64
import os
import sys
import argparse
import yaml
from pathlib import Path
from datetime import datetime

from ollama import Client

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.utils.paths import load_profile


def _make_client() -> Client:
    api_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
    api_key = os.environ.get("OLLAMA_API_KEY", "")
    if api_key:
        return Client(host=api_base, headers={"Authorization": f"Bearer {api_key}"})
    return Client(host=api_base)


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _load_instructions() -> str:
    p = Path(__file__).parent / "instructions.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _build_prompt(client_profile: dict, source: str, instructions: str) -> str:
    return f"""Você é o Agente de Análise Visual do sistema Dream Squad.

CONTEXTO DO CLIENTE:
- client_id: {client_profile.get('client_id', '')}
- Nicho: {client_profile.get('niche', '')}
- Persona: {client_profile.get('persona', {}).get('instagram_handle', '')}
- Público-alvo: {client_profile.get('audience', {}).get('description', '')}
- Tom de voz: {', '.join(client_profile.get('voice', {}).get('tone', []))}
- Data atual: {datetime.now().strftime('%Y-%m-%d')}
- Fonte desta imagem: {source}

{instructions}

Analise o screenshot fornecido e retorne APENAS o YAML estruturado conforme o formato acima.
Sem texto adicional. Sem code fences."""


def _call_ollama(image_path: str, prompt: str, client: Client, model: str) -> dict:
    b64 = _encode_image(image_path)

    response = client.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": prompt,
            "images": [b64],
        }],
        options={"temperature": 0.1},
        think=True,
    )

    if response.message.thinking:
        preview = response.message.thinking[:300].replace("\n", " ")
        print(f"  [think] {preview}...", file=sys.stderr)

    raw = response.message.content.strip()

    if raw.startswith("```yaml"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]

    return yaml.safe_load(raw.strip())


def _extract_screenshots(collection: dict) -> list[tuple[str, str]]:
    """Retorna lista de (path, fonte) de screenshots de Instagram e Twitter."""
    pairs = []

    ig = collection.get("instagram", {})
    if ig.get("status") != "falha":
        for perfil in ig.get("perfis", []):
            if perfil.get("status") == "sucesso":
                for p in perfil.get("screenshots", []):
                    pairs.append((p, "instagram"))

    tw = collection.get("twitter", {})
    if tw.get("status") == "sucesso":
        for p in tw.get("screenshots", []):
            pairs.append((p, "twitter"))

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Visual Analyzer — Ollama mode")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--collection-yaml", required=True, help="YAML gerado pelo Playwright Collector")
    parser.add_argument("--output", required=True, help="Path do .yaml de saída")
    args = parser.parse_args()

    model = os.environ.get("OLLAMA_MODEL", "kimi-k2.6:cloud")
    client = _make_client()
    profile = load_profile(args.client_id)
    instructions = _load_instructions()

    with open(args.collection_yaml, encoding="utf-8") as f:
        collection = yaml.safe_load(f)

    screenshots = _extract_screenshots(collection)
    print(f"[visual_analyzer] {len(screenshots)} screenshots para analisar", file=sys.stderr)

    pautas = []
    counter = 1

    for img_path, source in screenshots:
        if not Path(img_path).exists():
            print(f"  [AVISO] Arquivo não encontrado: {img_path}", file=sys.stderr)
            continue

        prompt = _build_prompt(profile, source, instructions)

        try:
            result = _call_ollama(img_path, prompt, client, model)

            items = []
            if isinstance(result, list):
                items = result
            elif isinstance(result, dict):
                inner = result.get("analise_visual", result)
                items = inner.get("pautas_identificadas", [inner] if "pauta" in inner else [])

            for item in items:
                item["id"] = f"pauta_{counter:03d}"
                pautas.append(item)
                counter += 1

            print(f"  [OK] {img_path} → {len(items)} pauta(s)", file=sys.stderr)

        except Exception as e:
            print(f"  [ERRO] {img_path}: {e}", file=sys.stderr)

    output_data = {
        "analise_visual": {
            "client_id": args.client_id,
            "nicho": profile.get("niche", ""),
            "data_analise": datetime.now().isoformat(),
            "total_screenshots": len(screenshots),
            "pautas_identificadas": pautas,
        }
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(output_data, f, allow_unicode=True, default_flow_style=False)

    print(f"[visual_analyzer] {len(pautas)} pautas → {out_path}")


if __name__ == "__main__":
    main()
