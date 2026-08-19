"""Comentários, diagnósticos e etiquetas compartilhados por OS.

Como o app não tem um servidor central (cada pessoa roda sua própria
instância localmente), guardamos tudo isso no GitHub: cada OS vira uma Issue
no repositório privado (título "OS {folio}"):
- Cada comentário da pessoa vira um comentário daquela Issue.
- O diagnóstico (Falha de Equipamento / Falha de Comunicação / Sujidade /
  Outro) vira uma "label" da própria Issue — só uma por vez.
- As etiquetas locais (OS em campo / Stand By / Validação Final) também
  viram labels da Issue — várias podem estar ativas ao mesmo tempo.

Assim, qualquer pessoa que abrir a mesma OS em qualquer PC do time vê os
mesmos comentários, o mesmo diagnóstico e as mesmas etiquetas.

O nome de quem escreveu um comentário fica embutido no início do corpo dele
(o GitHub sempre atribui a autoria ao dono do token, não a quem digitou no
app), então fazemos nós mesmos essa marcação e extraímos de volta na leitura.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any
from urllib.parse import quote

import requests

from . import config

_HEADERS = {
    "Authorization": f"Bearer {config.GITHUB_COMMENTS_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

_ISSUE_TITLE_PREFIX = "OS "
_COMMENT_PATTERN = re.compile(r"^\*\*(?P<autor>.+?):\*\*\n(?P<texto>[\s\S]*)$")

DIAGNOSTIC_OPTIONS = ["Falha de Equipamento", "Falha de Comunicação", "Sujidade", "Outro"]
_DIAGNOSTIC_SET = set(DIAGNOSTIC_OPTIONS)

TAG_OPTIONS = ["OS em campo", "Stand By", "Validação Final"]
_TAG_SET = set(TAG_OPTIONS)


class CommentsClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        # folio -> {"number": int, "labels": set[str]}
        self._issue_cache: dict[str, dict[str, Any]] = {}
        self._issue_cache_at: float = 0.0
        self._issue_cache_ttl = 60.0  # 1 minuto
        self._lock = threading.Lock()

    def _api_url(self, path: str) -> str:
        return f"{config.GITHUB_API_BASE}/repos/{config.GITHUB_REPO}{path}"

    def _refresh_issue_cache(self, force: bool = False) -> None:
        now = time.time()
        if not force and self._issue_cache and (now - self._issue_cache_at) < self._issue_cache_ttl:
            return

        mapping: dict[str, dict[str, Any]] = {}
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
                    label_names = {lb.get("name") for lb in issue.get("labels") or []}
                    mapping[folio] = {"number": issue["number"], "labels": label_names}
            if len(issues) < 100:
                break
            page += 1

        self._issue_cache = mapping
        self._issue_cache_at = now

    def _find_issue(self, folio: str) -> dict[str, Any] | None:
        self._refresh_issue_cache()
        return self._issue_cache.get(folio)

    def _get_or_create_issue(self, folio: str) -> dict[str, Any]:
        with self._lock:
            info = self._find_issue(folio)
            if info is not None:
                return info

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
            info = {"number": number, "labels": set()}
            self._issue_cache[folio] = info
            return info

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

    # ------------------------------------------------------------------
    # Comentários
    # ------------------------------------------------------------------
    def list_comments(self, folio: str) -> list[dict[str, Any]]:
        folio = str(folio)
        info = self._find_issue(folio)
        if info is None:
            return []
        resp = self._session.get(
            self._api_url(f"/issues/{info['number']}/comments"),
            headers=_HEADERS,
            params={"per_page": 100},
            timeout=20,
        )
        resp.raise_for_status()
        return [self._parse_comment(c) for c in resp.json()]

    def add_comment(self, folio: str, autor: str, texto: str) -> dict[str, Any]:
        folio = str(folio)
        number = self._get_or_create_issue(folio)["number"]
        body = f"**{autor}:**\n{texto}"
        resp = self._session.post(
            self._api_url(f"/issues/{number}/comments"),
            headers=_HEADERS,
            json={"body": body},
            timeout=20,
        )
        resp.raise_for_status()
        return self._parse_comment(resp.json())

    # ------------------------------------------------------------------
    # Diagnóstico (label única por OS) e Etiquetas (múltiplas por OS)
    # ------------------------------------------------------------------
    def get_diagnosticos_mapping(self) -> dict[str, str]:
        """folio -> diagnóstico, só para as OS que já têm um definido."""
        self._refresh_issue_cache()
        resultado: dict[str, str] = {}
        for folio, info in self._issue_cache.items():
            diagnostico = next((lb for lb in info["labels"] if lb in _DIAGNOSTIC_SET), None)
            if diagnostico:
                resultado[folio] = diagnostico
        return resultado

    def get_tags_mapping(self) -> dict[str, list[str]]:
        """folio -> lista de etiquetas locais ativas."""
        self._refresh_issue_cache()
        resultado: dict[str, list[str]] = {}
        for folio, info in self._issue_cache.items():
            tags = [lb for lb in info["labels"] if lb in _TAG_SET]
            if tags:
                resultado[folio] = tags
        return resultado

    def get_diagnosticos_e_tags(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        """Busca os dois de uma vez só (uma única atualização de cache)."""
        self._refresh_issue_cache()
        diagnosticos: dict[str, str] = {}
        tags: dict[str, list[str]] = {}
        for folio, info in self._issue_cache.items():
            diagnostico = next((lb for lb in info["labels"] if lb in _DIAGNOSTIC_SET), None)
            if diagnostico:
                diagnosticos[folio] = diagnostico
            os_tags = [lb for lb in info["labels"] if lb in _TAG_SET]
            if os_tags:
                tags[folio] = os_tags
        return diagnosticos, tags

    def _add_label(self, number: int, label: str) -> None:
        resp = self._session.post(
            self._api_url(f"/issues/{number}/labels"),
            headers=_HEADERS,
            json={"labels": [label]},
            timeout=20,
        )
        resp.raise_for_status()

    def _remove_label(self, number: int, label: str) -> None:
        resp = self._session.delete(
            self._api_url(f"/issues/{number}/labels/{quote(label, safe='')}"),
            headers=_HEADERS,
            timeout=20,
        )
        # 404 significa que a label já não estava lá — sem problema.
        if resp.status_code not in (200, 404):
            resp.raise_for_status()

    def set_diagnostico(self, folio: str, diagnostico: str | None) -> None:
        folio = str(folio)
        if diagnostico is not None and diagnostico not in _DIAGNOSTIC_SET:
            raise ValueError(f"Diagnóstico inválido: {diagnostico!r}")

        info = self._get_or_create_issue(folio)
        number = info["number"]
        diagnostico_atual = next((lb for lb in info["labels"] if lb in _DIAGNOSTIC_SET), None)

        if diagnostico_atual and diagnostico_atual != diagnostico:
            self._remove_label(number, diagnostico_atual)
        if diagnostico and diagnostico != diagnostico_atual:
            self._add_label(number, diagnostico)

        with self._lock:
            labels = self._issue_cache[folio]["labels"]
            labels.discard(diagnostico_atual) if diagnostico_atual else None
            if diagnostico:
                labels.add(diagnostico)

    def toggle_tag(self, folio: str, tag: str) -> list[str]:
        """Ativa/desativa uma etiqueta local na OS. Retorna a lista atualizada."""
        folio = str(folio)
        if tag not in _TAG_SET:
            raise ValueError(f"Etiqueta inválida: {tag!r}")

        info = self._get_or_create_issue(folio)
        number = info["number"]
        ativa = tag in info["labels"]

        if ativa:
            self._remove_label(number, tag)
        else:
            self._add_label(number, tag)

        with self._lock:
            labels = self._issue_cache[folio]["labels"]
            if ativa:
                labels.discard(tag)
            else:
                labels.add(tag)
            return sorted(lb for lb in labels if lb in _TAG_SET)


comments_client = CommentsClient()
