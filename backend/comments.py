"""Comentários, diagnósticos, status pós-OS e etiquetas compartilhados por OS.

Como o app não tem um servidor central (cada pessoa roda sua própria
instância localmente), guardamos tudo isso no GitHub: cada OS vira uma Issue
no repositório privado (título "OS {folio}"):
- Cada comentário da pessoa vira um comentário daquela Issue.
- O diagnóstico (Falha de Equipamento / Falha de Comunicação / Sujidade /
  Outro) vira uma "label" da própria Issue — só uma por vez.
- O status pós-OS (Chamado de Garantia / Alinhamento com o Cliente /
  Regularizado) também vira uma label única, independente do diagnóstico.
- As etiquetas locais (OS em campo / Stand By / Validação Final) também
  viram labels da Issue — várias podem estar ativas ao mesmo tempo.

Assim, qualquer pessoa que abrir a mesma OS em qualquer PC do time vê os
mesmos comentários, o mesmo diagnóstico, o mesmo status pós-OS e as mesmas
etiquetas.

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

STATUS_POS_OS_OPTIONS = ["Chamado de Garantia", "Alinhamento com o Cliente", "Regularizado"]
_STATUS_POS_OS_SET = set(STATUS_POS_OS_OPTIONS)

TAG_OPTIONS = ["OS em campo", "Stand By", "Validação Final"]
_TAG_SET = set(TAG_OPTIONS)

# "Em Acompanhamento": marcador independente de status — usado pra continuar
# de olho numa OS mesmo depois de finalizada no Fracttal (ex: ficou pendência
# de garantia com o cliente). É um liga/desliga só, então tratamos como uma
# "categoria" de uma label só, reaproveitando o mecanismo de _set_single_label.
ACOMPANHAMENTO_LABEL = "Em Acompanhamento"
_ACOMPANHAMENTO_SET = {ACOMPANHAMENTO_LABEL}

# "Finalizado pela Engenharia": encerra a OS pro time de Engenharia sem
# precisar escolher um diagnóstico específico — usado principalmente pro
# botão de "encerrar em lote" as OS antigas já finalizadas no Fracttal.
# Junto com o diagnóstico, é um dos dois jeitos de uma OS sair das
# "Estações em Aberto" e contar como "encerrada pela Engenharia".
FINALIZADO_ENGENHARIA_LABEL = "Finalizado pela Engenharia"
_FINALIZADO_ENGENHARIA_SET = {FINALIZADO_ENGENHARIA_LABEL}
_LABELS_ENCERRAMENTO_ENGENHARIA = _DIAGNOSTIC_SET | _FINALIZADO_ENGENHARIA_SET


class CommentsClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        # folio -> {"number": int, "labels": set[str]}
        self._issue_cache: dict[str, dict[str, Any]] = {}
        self._issue_cache_at: float = 0.0
        self._issue_cache_ttl = 60.0  # 1 minuto
        self._lock = threading.Lock()

        # folio -> data de encerramento pela Engenharia (diagnóstico ou
        # "Finalizado pela Engenharia") — exige 1 chamada de API por OS
        # encerrada (Timeline do GitHub não tem versão "em lote"), então
        # cacheamos por mais tempo que o resto (é só pra um relatório).
        self._closed_dates_cache: dict[str, str] | None = None
        self._closed_dates_cache_at: float = 0.0
        self._closed_dates_cache_ttl = 5 * 60  # 5 minutos
        self._closed_dates_lock = threading.Lock()

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

    def get_comments_for_folios(self, folios: list[str]) -> list[dict[str, Any]]:
        """Todos os comentários das OS informadas, cada um marcado com seu
        folio — usado pelo chat consolidado da usina, no Histórico.
        """
        self._refresh_issue_cache()
        resultado: list[dict[str, Any]] = []
        for folio in folios:
            folio = str(folio)
            info = self._issue_cache.get(folio)
            if info is None:
                continue
            resp = self._session.get(
                self._api_url(f"/issues/{info['number']}/comments"),
                headers=_HEADERS,
                params={"per_page": 100},
                timeout=20,
            )
            resp.raise_for_status()
            for raw in resp.json():
                comentario = self._parse_comment(raw)
                comentario["folio"] = folio
                resultado.append(comentario)
        resultado.sort(key=lambda c: c.get("data") or "")
        return resultado

    # ------------------------------------------------------------------
    # Diagnóstico / Status pós-OS (uma label cada, por OS) e Etiquetas
    # (várias labels por OS) — todas guardadas como labels da Issue.
    # ------------------------------------------------------------------
    def get_all_label_mappings(
        self,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, list[str]], dict[str, bool], dict[str, bool]]:
        """Busca diagnóstico, status pós-OS, etiquetas, acompanhamento e
        finalizado-pela-Engenharia de uma vez só (uma única atualização de
        cache). folio -> valor em cada um.
        """
        self._refresh_issue_cache()
        diagnosticos: dict[str, str] = {}
        status_pos_os: dict[str, str] = {}
        tags: dict[str, list[str]] = {}
        acompanhamento: dict[str, bool] = {}
        finalizado_engenharia: dict[str, bool] = {}
        for folio, info in self._issue_cache.items():
            diagnostico = next((lb for lb in info["labels"] if lb in _DIAGNOSTIC_SET), None)
            if diagnostico:
                diagnosticos[folio] = diagnostico
            status = next((lb for lb in info["labels"] if lb in _STATUS_POS_OS_SET), None)
            if status:
                status_pos_os[folio] = status
            os_tags = [lb for lb in info["labels"] if lb in _TAG_SET]
            if os_tags:
                tags[folio] = os_tags
            if ACOMPANHAMENTO_LABEL in info["labels"]:
                acompanhamento[folio] = True
            if FINALIZADO_ENGENHARIA_LABEL in info["labels"]:
                finalizado_engenharia[folio] = True
        return diagnosticos, status_pos_os, tags, acompanhamento, finalizado_engenharia

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

    def _set_single_label(self, folio: str, novo_valor: str | None, categoria: set[str]) -> None:
        """Garante no máximo uma label da `categoria` ativa na OS por vez —
        usado tanto pro diagnóstico quanto pro status pós-OS.
        """
        folio = str(folio)
        if novo_valor is not None and novo_valor not in categoria:
            raise ValueError(f"Valor inválido: {novo_valor!r}")

        info = self._get_or_create_issue(folio)
        number = info["number"]
        valor_atual = next((lb for lb in info["labels"] if lb in categoria), None)

        if valor_atual and valor_atual != novo_valor:
            self._remove_label(number, valor_atual)
        if novo_valor and novo_valor != valor_atual:
            self._add_label(number, novo_valor)

        with self._lock:
            labels = self._issue_cache[folio]["labels"]
            if valor_atual:
                labels.discard(valor_atual)
            if novo_valor:
                labels.add(novo_valor)

    def _invalidar_cache_datas_fechamento(self) -> None:
        with self._closed_dates_lock:
            self._closed_dates_cache = None

    def set_diagnostico(self, folio: str, diagnostico: str | None) -> None:
        self._set_single_label(folio, diagnostico, _DIAGNOSTIC_SET)
        self._invalidar_cache_datas_fechamento()

    def _labeled_timestamp(self, info: dict[str, Any], categoria: set[str]) -> str | None:
        """Data em que a última label de `categoria` foi aplicada a essa
        Issue — lida do histórico de eventos (Timeline API do GitHub), já
        que não guardamos isso nós mesmos.
        """
        resp = self._session.get(
            self._api_url(f"/issues/{info['number']}/timeline"),
            headers=_HEADERS,
            params={"per_page": 100},
            timeout=20,
        )
        resp.raise_for_status()
        eventos = resp.json()
        aplicacoes = [
            e for e in eventos if e.get("event") == "labeled" and (e.get("label") or {}).get("name") in categoria
        ]
        if not aplicacoes:
            return None
        return aplicacoes[-1].get("created_at")

    def get_diagnostico_timestamp(self, folio: str) -> str | None:
        """Data em que a Engenharia definiu o diagnóstico dessa OS pela
        última vez. Usado sob demanda, ao abrir o modal.
        """
        folio = str(folio)
        info = self._find_issue(folio)
        if info is None:
            return None
        return self._labeled_timestamp(info, _DIAGNOSTIC_SET)

    def get_encerramento_engenharia_timestamp(self, folio: str) -> str | None:
        """Data em que a Engenharia encerrou essa OS, seja por diagnóstico
        ou por "Finalizado pela Engenharia" — o que tiver acontecido por
        último. Usado sob demanda, ao abrir o modal.
        """
        folio = str(folio)
        info = self._find_issue(folio)
        if info is None:
            return None
        return self._labeled_timestamp(info, _LABELS_ENCERRAMENTO_ENGENHARIA)

    def get_closed_by_engineering_dates(self, folios: list[str]) -> dict[str, str]:
        """folio -> data em que a Engenharia encerrou aquela OS (diagnóstico
        OU "Finalizado pela Engenharia", o que tiver acontecido por último) —
        só para as OS informadas (espera-se que já estejam encerradas de
        algum dos dois jeitos). Cacheado por mais tempo (ver __init__) porque
        isso é 1 chamada de API por OS — usado no relatório de Fechamentos.
        """
        now = time.time()
        with self._closed_dates_lock:
            if (
                self._closed_dates_cache is not None
                and (now - self._closed_dates_cache_at) < self._closed_dates_cache_ttl
            ):
                return self._closed_dates_cache

            self._refresh_issue_cache()
            resultado: dict[str, str] = {}
            for folio in folios:
                folio = str(folio)
                info = self._issue_cache.get(folio)
                if info is None:
                    continue
                data = self._labeled_timestamp(info, _LABELS_ENCERRAMENTO_ENGENHARIA)
                if data:
                    resultado[folio] = data

            self._closed_dates_cache = resultado
            self._closed_dates_cache_at = now
            return resultado

    def set_status_pos_os(self, folio: str, status: str | None) -> None:
        self._set_single_label(folio, status, _STATUS_POS_OS_SET)

    def set_acompanhamento(self, folio: str, ativo: bool) -> None:
        self._set_single_label(folio, ACOMPANHAMENTO_LABEL if ativo else None, _ACOMPANHAMENTO_SET)

    def set_finalizado_engenharia(self, folio: str, ativo: bool) -> None:
        self._set_single_label(folio, FINALIZADO_ENGENHARIA_LABEL if ativo else None, _FINALIZADO_ENGENHARIA_SET)
        self._invalidar_cache_datas_fechamento()

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
