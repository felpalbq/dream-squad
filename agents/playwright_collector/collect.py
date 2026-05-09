#!/usr/bin/env python3
"""
Dream Squad — Playwright Collector
Coleta screenshots de Instagram e Twitter/X com perfil Chrome do operador.
Sites regionais são cobertos pelo Ollama Researcher (agents/ollama_researcher/).
"""

import asyncio
import random
import os
import sys
import argparse
import yaml
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright, Page, BrowserContext

try:
    from playwright_stealth import Stealth as _Stealth
    _STEALTH = _Stealth()
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.utils.paths import load_profile


# ── anti-detecção ─────────────────────────────────────────────────────────────

def _normal_clamp(mean: float, std: float, lo: float, hi: float) -> float:
    """Delay com distribuição normal, nunca fixo."""
    return max(lo, min(hi, random.normalvariate(mean, std)))


async def _pause(lo: float, hi: float):
    await asyncio.sleep(lo + random.random() * (hi - lo))


async def _bezier_move(page: Page, x0: float, y0: float, x1: float, y1: float):
    """Move o mouse em curva de Bézier quadrática — nunca linha reta."""
    steps = random.randint(18, 35)
    cx = x0 + (x1 - x0) * 0.5 + random.uniform(-90, 90)
    cy = y0 + (y1 - y0) * 0.5 + random.uniform(-90, 90)
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.008, 0.04))


async def _human_scroll(page: Page, total_px: int = 800, direction: str = "down"):
    """Scroll gradual com pausas aleatórias simulando leitura."""
    scrolled = 0
    sign = 1 if direction == "down" else -1
    while scrolled < total_px:
        chunk = random.randint(70, 180)
        await page.mouse.wheel(0, sign * chunk)
        scrolled += chunk
        await asyncio.sleep(_normal_clamp(0.25, 0.1, 0.08, 0.7))
        if random.random() < 0.18:
            await asyncio.sleep(_normal_clamp(1.4, 0.5, 0.7, 2.8))


def _is_blocked(url: str) -> bool:
    signals = ["checkpoint", "challenge", "captcha", "verify", "login", "accounts/login"]
    return any(s in url.lower() for s in signals)


# ── contexto do navegador ─────────────────────────────────────────────────────

async def launch_browser(playwright) -> BrowserContext:
    """Abre Chrome com perfil persistente do operador."""
    profile_path = os.environ.get("CHROME_PROFILE_PATH", "")
    executable_path = os.environ.get("CHROME_EXECUTABLE_PATH", "")

    if not profile_path or not Path(profile_path).exists():
        raise RuntimeError(
            f"CHROME_PROFILE_PATH inválido ou não encontrado: '{profile_path}'\n"
            "Configure a variável de ambiente com o caminho correto ao perfil Chrome."
        )

    kwargs: dict = {
        "user_data_dir": profile_path,
        "headless": False,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions-except=",
        ],
        "no_viewport": True,
        "slow_mo": 0,
    }
    if executable_path:
        kwargs["executable_path"] = executable_path

    context = await playwright.chromium.launch_persistent_context(**kwargs)

    if HAS_STEALTH:
        await _STEALTH.apply_stealth_async(context)
    else:
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

    return context


# ── instagram ─────────────────────────────────────────────────────────────────

async def collect_instagram(
    context: BrowserContext,
    client_config: dict,
    exec_dir: Path,
    posts_to_capture: int = 8,
) -> dict:
    """Captura screenshots do grid e posts dos perfis de referência do cliente."""
    profiles = client_config.get("instagram_reference_profiles", [])
    out_dir = exec_dir / "instagram" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "fonte": "instagram",
        "client_id": client_config.get("client_id", ""),
        "data_coleta": datetime.now().isoformat(),
        "perfis": [],
    }

    for idx, profile_info in enumerate(profiles):
        url = profile_info["url"]
        handle = profile_info.get("handle", url.rstrip("/").split("/")[-1])
        safe_handle = handle.lstrip("@").replace("/", "_")
        entry = {"perfil": handle, "url": url, "screenshots": [], "status": "pendente"}

        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await _pause(3, 8)

            if _is_blocked(page.url):
                entry["status"] = "bloqueado"
                entry["erro"] = f"Redirecionado para: {page.url}"
                result["perfis"].append(entry)
                await page.close()
                continue

            p1 = out_dir / f"{safe_handle}_grid_01.png"
            await page.screenshot(path=str(p1), full_page=False)
            entry["screenshots"].append(str(p1))

            await _human_scroll(page, _normal_clamp(550, 100, 350, 800))
            await _pause(2, 5)
            p2 = out_dir / f"{safe_handle}_grid_02.png"
            await page.screenshot(path=str(p2), full_page=False)
            entry["screenshots"].append(str(p2))

            post_links = await page.query_selector_all("article a[href*='/p/'], a[href*='/reel/']")
            post_links = post_links[:posts_to_capture]

            for post_idx, link in enumerate(post_links):
                try:
                    href = await link.get_attribute("href")
                    if not href:
                        continue
                    post_url = href if href.startswith("http") else f"https://www.instagram.com{href}"

                    await link.click()
                    await _pause(2, 4)
                    await page.wait_for_load_state("networkidle", timeout=15_000)

                    post_path = out_dir / f"{safe_handle}_post_{post_idx + 1:03d}.png"
                    await page.screenshot(path=str(post_path), full_page=False)
                    entry["screenshots"].append(str(post_path))

                    await page.go_back()
                    await _pause(2, 5)

                except Exception as e:
                    print(f"  [AVISO] Post {post_idx+1} falhou: {e}", file=sys.stderr)

            entry["status"] = "sucesso"

        except Exception as e:
            entry["status"] = "falha"
            entry["erro"] = str(e)
            print(f"[ERRO] Instagram {handle}: {e}", file=sys.stderr)
        finally:
            await page.close()

        result["perfis"].append(entry)

        if idx < len(profiles) - 1:
            await _pause(5, 12)

    return result


# ── twitter/x ─────────────────────────────────────────────────────────────────

async def collect_twitter(context: BrowserContext, exec_dir: Path) -> dict:
    """Captura screenshots do feed Twitter/X curado do operador."""
    out_dir = exec_dir / "twitter" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "fonte": "twitter",
        "data_coleta": datetime.now().isoformat(),
        "screenshots": [],
        "status": "pendente",
    }

    page = await context.new_page()
    try:
        await page.goto("https://x.com/home", wait_until="networkidle", timeout=30_000)
        await _pause(3, 7)

        if _is_blocked(page.url):
            result["status"] = "bloqueado"
            result["erro"] = f"Redirecionado para: {page.url}"
            return result

        max_shots = 6
        for i in range(max_shots):
            shot_path = out_dir / f"tw_{i + 1:03d}.png"
            await page.screenshot(path=str(shot_path), full_page=False)
            result["screenshots"].append(str(shot_path))

            scroll_px = int(_normal_clamp(650, 120, 400, 1000))
            await _human_scroll(page, scroll_px)
            await _pause(2, 5)
            if i % 2 == 1:
                await _pause(2, 6)

        result["status"] = "sucesso"

    except Exception as e:
        result["status"] = "falha"
        result["erro"] = str(e)
        print(f"[ERRO] Twitter: {e}", file=sys.stderr)
    finally:
        await page.close()

    return result


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Dream Squad — Playwright Collector")
    parser.add_argument("--client-id", required=True)
    parser.add_argument(
        "--source",
        choices=["instagram", "twitter", "all"],
        default="all",
    )
    parser.add_argument("--exec-dir", required=True, help="Diretório raiz da execução")
    args = parser.parse_args()

    client_config = load_profile(args.client_id)
    exec_dir = Path(args.exec_dir)
    exec_dir.mkdir(parents=True, exist_ok=True)

    collection: dict = {}

    async with async_playwright() as pw:
        context = await launch_browser(pw)
        try:
            if args.source in ("instagram", "all"):
                print("[collect] Instagram...", file=sys.stderr)
                posts_max = client_config.get("research", {}).get("top_posts_to_capture", 8)
                collection["instagram"] = await collect_instagram(
                    context, client_config, exec_dir, posts_max
                )

            if args.source in ("twitter", "all"):
                print("[collect] Twitter/X...", file=sys.stderr)
                collection["twitter"] = await collect_twitter(context, exec_dir)

        finally:
            await context.close()

    output_path = exec_dir / "collection.yaml"
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(collection, f, allow_unicode=True, default_flow_style=False)

    print(yaml.dump(collection, allow_unicode=True, default_flow_style=False))


if __name__ == "__main__":
    asyncio.run(main())
