"""Checagem e aplicação de atualizações via GitHub Releases.

Fluxo:
1. O app consulta a release mais recente do repositório privado no GitHub.
2. Se a versão da release for maior que a versão atual (backend/version.py),
   oferece a atualização ao usuário (via banner na interface).
3. Se o usuário aceitar, baixa o instalador (.exe) daquela release pra uma
   pasta temporária, dispara a instalação silenciosa e fecha o app atual.
   O usuário reabre o app manualmente depois (igual à maioria dos apps
   desktop com auto-update) — não tentamos reabrir sozinhos.

Nota sobre uma abordagem anterior: cheguei a tentar reabrir o app
automaticamente ao final, o que exige encerrar os processos do app ANTES do
instalador tentar sobrescrever o .exe (senão o arquivo fica travado). Um app
PyInstaller --onefile roda como dois processos com o mesmo nome de imagem, e
tentar matar esses processos de dentro deles mesmos (via taskkill/subprocess)
se mostrou não-confiável no Windows. Como confirmado em teste manual, quando
o app está completamente fechado o instalador sobrescreve o arquivo sem
problema — por isso a versão atual do fluxo é mais simples: só fechar.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import requests

from . import config
from .version import APP_VERSION

_HEADERS = {
    "Authorization": f"Bearer {config.GITHUB_UPDATE_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def _parse_version(tag: str) -> tuple[int, ...]:
    """Converte 'v1.2.3' ou '1.2.3' em (1, 2, 3) pra comparação."""
    cleaned = tag.strip().lstrip("vV")
    parts = []
    for p in cleaned.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def check_for_update() -> dict[str, Any]:
    """Consulta a release mais recente. Nunca levanta exceção — em caso de
    falha (sem internet, repo indisponível, etc.) apenas informa que não há
    atualização disponível, sem quebrar o app.
    """
    base_result = {
        "update_available": False,
        "current_version": APP_VERSION,
        "latest_version": None,
        "notas": None,
        "error": None,
    }
    try:
        resp = requests.get(
            f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_REPO}/releases/latest",
            headers=_HEADERS,
            timeout=10,
        )
        if resp.status_code == 404:
            # Nenhuma release publicada ainda
            return base_result
        resp.raise_for_status()
        data = resp.json()

        latest_tag = data.get("tag_name", "")
        latest_version = _parse_version(latest_tag)
        current_version = _parse_version(APP_VERSION)

        asset = next(
            (a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")),
            None,
        )

        base_result["latest_version"] = latest_tag.lstrip("vV") or None
        base_result["notas"] = data.get("body")

        if latest_version > current_version and asset is not None:
            base_result["update_available"] = True
            base_result["_asset_url"] = asset["url"]  # API url, exige auth pra baixar
            base_result["_asset_name"] = asset["name"]

        return base_result
    except Exception as exc:  # noqa: BLE001
        base_result["error"] = str(exc)
        return base_result


def _download_asset(asset_api_url: str, dest: Path) -> None:
    # Assets de release em repositório privado precisam ser baixados via API
    # (não pela browser_download_url pública) com Accept: octet-stream.
    headers = dict(_HEADERS)
    headers["Accept"] = "application/octet-stream"
    with requests.get(asset_api_url, headers=headers, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


def _exit_app_soon(delay_seconds: float = 0.5) -> None:
    def _exit() -> None:
        time.sleep(delay_seconds)
        os._exit(0)  # encerramento imediato, libera o .exe pro instalador sobrescrever

    threading.Thread(target=_exit, daemon=True).start()


def apply_update(asset_api_url: str, asset_name: str) -> None:
    """Baixa o instalador da release, dispara a instalação silenciosa e
    encerra o app atual. O usuário reabre manualmente quando quiser —
    o app não tenta se reabrir sozinho (ver nota no topo do arquivo).
    """
    tmp_dir = Path(tempfile.gettempdir()) / "etm-gridco-update"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    installer_path = tmp_dir / asset_name

    _download_asset(asset_api_url, installer_path)

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        creationflags=creationflags,
        close_fds=True,
    )

    _exit_app_soon()
