"""Cliente de integração com a API do Fracttal.

Responsável por:
- Autenticar via OAuth2 client_credentials (com cache do token até expirar)
- Buscar os ativos que são Estações Meteorológicas (ETM)
- Buscar as Ordens de Serviço corretivas associadas a essas ETMs
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from . import config

_PAGE_LIMIT = 100
_MAX_WORKERS = 8


class FracttalClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = threading.Lock()

        # Cache simples da lista de ETMs (não muda com frequência)
        self._etm_cache: list[dict[str, Any]] | None = None
        self._etm_cache_at: float = 0.0
        self._etm_cache_ttl = 15 * 60  # 15 minutos

        # Cache das OS corretivas (essa sim reflete "ao vivo" o Fracttal, mas
        # como buscar todas as ETMs é ~125 chamadas, evitamos refazer isso a
        # cada clique do usuário — só quando ele pede "Atualizar" ou o cache
        # expira). Isso é compartilhado entre o Planner e o Histórico.
        self._orders_cache: list[dict[str, Any]] | None = None
        self._orders_cache_at: float = 0.0
        self._orders_cache_ttl = 3 * 60  # 3 minutos

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------
    def _get_token(self) -> str:
        with self._token_lock:
            if self._token and time.time() < self._token_expires_at - 30:
                return self._token

            resp = self._session.post(
                config.FRACTTAL_TOKEN_URL,
                auth=(config.FRACTTAL_CLIENT_ID, config.FRACTTAL_CLIENT_SECRET),
                data={"grant_type": "client_credentials"},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 7200)
            return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._session.get(
            f"{config.FRACTTAL_API_BASE}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_all_pages(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Percorre todas as páginas de um endpoint paginado do Fracttal."""
        params = dict(params or {})
        start = 0
        results: list[dict[str, Any]] = []
        while True:
            params["start"] = start
            params["limit"] = _PAGE_LIMIT
            data = self._get(path, params)
            page_items = data.get("data", []) or []
            results.extend(page_items)
            total = data.get("total", len(results))
            start += _PAGE_LIMIT
            if start >= total or not page_items:
                break
        return results

    # ------------------------------------------------------------------
    # Ativos (ETMs)
    # ------------------------------------------------------------------
    def get_etm_assets(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Retorna a lista de ativos identificados como Estação Meteorológica.

        A lista completa de ativos da empresa é grande (~20 mil), então
        mantemos um cache em memória de alguns minutos para não varrer tudo
        a cada clique. Use force_refresh=True para ignorar o cache.
        """
        now = time.time()
        if (
            not force_refresh
            and self._etm_cache is not None
            and (now - self._etm_cache_at) < self._etm_cache_ttl
        ):
            return self._etm_cache

        # field_1 é o campo "Nome" do ativo no Fracttal; nas ETMs ele vem
        # preenchido exatamente como "Estação Meteorológica", então filtramos
        # direto na API em vez de varrer o catálogo inteiro (~20 mil ativos).
        etms = self._get_all_pages("/items", {"field_1": "Estação Meteorológica"})

        # Segurança extra: confirma pela descrição, caso o filtro do Fracttal
        # algum dia passe a ser mais permissivo (contains) do que exato.
        etms = [
            item
            for item in etms
            if any(
                marker in (item.get("description") or "").lower()
                for marker in config.ETM_DESCRIPTION_MARKERS
            )
        ]
        self._etm_cache = etms
        self._etm_cache_at = now
        return etms

    def get_usinas(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Agrupa as ETMs por usina (groups_1_description)."""
        etms = self.get_etm_assets(force_refresh=force_refresh)
        usinas: dict[str, dict[str, Any]] = {}
        for etm in etms:
            nome = etm.get("groups_1_description") or "Usina não identificada"
            if nome not in usinas:
                usinas[nome] = {"nome": nome, "etms": []}
            usinas[nome]["etms"].append(
                {"code": etm.get("code"), "descricao": etm.get("description")}
            )
        return sorted(usinas.values(), key=lambda u: u["nome"])

    # ------------------------------------------------------------------
    # Ordens de Serviço
    # ------------------------------------------------------------------
    def _get_work_orders_for_asset(self, code: str) -> list[dict[str, Any]]:
        return self._get_all_pages("/work_orders", {"code_asset": code})

    def get_all_etm_work_orders(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Busca todas as OS de todas as ETMs (não filtra tipo/status).

        Faz as chamadas em paralelo (uma por ETM) para não ser lento demais,
        já que a API do Fracttal não permite filtrar por múltiplos ativos
        de uma vez.
        """
        etms = self.get_etm_assets(force_refresh=force_refresh)
        codes = [etm["code"] for etm in etms if etm.get("code")]

        all_orders: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            futures = {pool.submit(self._get_work_orders_for_asset, code): code for code in codes}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    all_orders.extend(future.result())
                except requests.HTTPError as exc:
                    # Não deixa uma ETM com erro derrubar a consulta inteira
                    print(f"[fracttal_client] Falha ao buscar OS de {code}: {exc}")
        return all_orders

    def get_corrective_work_orders(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force_refresh
            and self._orders_cache is not None
            and (now - self._orders_cache_at) < self._orders_cache_ttl
        ):
            return self._orders_cache

        orders = self.get_all_etm_work_orders(force_refresh=force_refresh)
        corretivas = [
            o
            for o in orders
            if (o.get("tasks_log_task_type_main") or "").strip().lower()
            == config.CORRECTIVE_TASK_TYPE.lower()
        ]
        self._orders_cache = corretivas
        self._orders_cache_at = now
        return corretivas


fracttal_client = FracttalClient()
