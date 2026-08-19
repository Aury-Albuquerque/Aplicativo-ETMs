"""Comentários compartilhados por OS.

Como o app não tem um servidor central (cada pessoa roda sua própria
instância localmente), guardamos os comentários no GitHub: cada OS vira uma
Issue no repositório privado (título "OS {folio}"), e cada comentário da
pessoa vira um comentário daquela Issue. Assim, qualquer pessoa que abrir a
mesma OS em qualquer PC do time vê os mesmos comentários.

O nome de quem escreveu fica embutido no início do corpo do comentário (o
GitHub sempre atribui a autoria ao dono do token, não a quem digitou no
app), então fazemos nós mesmos essa marcação e extraímos de volta na leitura.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

import requests

from . import config

_HEADERS = {
    "Authorization": f"Bearer {config.GITHUB_COMMENTS_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

_ISSUE_TITLE_PREFIX = "OS "
_COMMENT_PATTERN = re.compile(r"^\*\*(?P<autor>.+?):\*\*\n(?P<texto>[\s\S]*)$")


class CommentsClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._issue_cache: dict[str, int] = {}
        self._issue_cache_at: float = 0.0
        self._issue_cache_ttl = 60.0  # 1 minuto
        self._lock = threading.Lock()

    def _api_url(self, path: str) -> str:
        return f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_REPO}{path}"

    def _refresh_issue_cache(self, force: bool = False) -> None:
        now = time.time()
        if not force and self._issue_cache and (now - self._issue_cache_at) < self._issue_cache_ttl:
            return

        mapping: dict[str, int] = {}
        page = 1
        while True:
            resp = self._session.get(
                self._api_url("/issues"),
                headers=_HEADERS,
                params={"state": "all", "per_page": 100, "page": page},
                timeout=20,
            )
            resp.raise_for_status()
            issues = resp.json()
            if not issues:
                break
            for issue in issues:
                title = issue.get("title") or ""
                if title.startswith(_ISSUE_TITLE_PREFIX):
                    folio = title[len(_ISSUE_TITLE_PREFIX):].strip()
                    mapping[folio] = issue["number"]
            if len(issues) < 100:
                break
            page += 1

        self._issue_cache = mapping
        self._issue_cache_at = now

    def _find_issue_number(self, folio: str) -> int | None:
        self._refresh_issue_cache()
        if folio in self._issue_cache:
            return self._issue_cache[folio]
        return None

    def _get_or_create_issue_number(self, folio: str) -> int:
        with self._lock:
            number = self._find_issue_number(folio)
            if number is not None:
                return number

            resp = self._session.post(
                self._api_url("/issues"),
                headers=_HEADERS,
                json={
                    "title": f"{_ISSUE_TITLE_PREFIX}{folio}",
                    "body": f"Comentários da OS {folio}, gerados automaticamente pelo app de ETM da Grid Co.",
                },
                timeout=20,
            )
            resp.raise_for_status()
            number = resp.json()["number"]
            self._issue_cache[folio] = number
            return number

    @staticmethod
    def _parse_comment(raw: dict[str, Any]) -> dict[str, Any]:
        body = raw.get("body") or ""
        match = _COMMENT_PATTERN.match(body)
        if match:
            autor = match.group("autor").strip()
            texto = match.group("texto").strip()
        else:
            autor = "Desconhecido"
            texto = body.strip()
        return {
            "id": raw.get("id"),
            "autor": autor,
            "texto": texto,
            "data": raw.get("created_at"),
        }

    def list_comments(self, folio: str) -> list[dict[str, Any]]:
        folio = str(folio)
        number = self._find_issue_number(folio)
        if number is None:
            return []
        resp = self._session.get(
            self._api_url(f"/issues/{number}/comments"),
            headers=_HEADERS,
            params={"per_page": 100},
            timeout=20,
        )
        resp.raise_for_status()
        return [self._parse_comment(c) for c in resp.json()]

    def add_comment(self, folio: str, autor: str, texto: str) -> dict[str, Any]:
        folio = str(folio)
        number = self._get_or_create_issue_number(folio)
        body = f"**{autor}:**\n{texto}"
        resp = self._session.post(
            self._api_url(f"/issues/{number}/comments"),
            headers=_HEADERS,
            json={"body": body},
            timeout=20,
        )
        resp.raise_for_status()
        return self._parse_comment(resp.json())


comments_client = CommentsClient()
