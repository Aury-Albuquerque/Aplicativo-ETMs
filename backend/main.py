"""App de organização de Ordens de Serviço corretivas de ETM (Grid Co.)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import updater
from .fracttal_client import extract_cliente, fracttal_client

# Quando empacotado com PyInstaller (--onefile), os arquivos de dados (o
# frontend) são extraídos para uma pasta temporária apontada por
# sys._MEIPASS. Em desenvolvimento, usamos a estrutura normal do projeto.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS"))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="ETM Grid Co.")


@app.middleware("http")
async def no_cache_estaticos(request, call_next):
    """Evita que o navegador guarde em cache uma versão antiga do app.js /
    style.css entre atualizações do app — sem isso, alguém que atualiza o
    executável mas mantém a mesma aba aberta pode acabar rodando JS velho
    contra o backend novo (e vice-versa), causando erros difíceis de explicar.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


# ----------------------------------------------------------------------
# Normalização
# ----------------------------------------------------------------------
# O status "real" de uma OS é o do work order (id_status_work_order), não o
# da tarefa individual (id_status_work_order_task). Uma OS pode ter a tarefa
# marcada como concluída (task_status=DONE) e mesmo assim a OS continuar
# "Em Revisão" no Fracttal — ou seja, ainda não está de fato finalizada.
# Por isso classificamos assim:
#   - id_status_work_order == 3 (Finalizada)              -> "finalizada"
#   - id_status_work_order == 4 (Cancelada)                -> "cancelada" (fora do Planner)
#   - id_status_work_order in (1 Processo, 2 Revisão):
#       - id_status_work_order_task == 0 (tarefa não iniciada) -> "nao_iniciada"
#       - qualquer outro status de tarefa                       -> "em_andamento"
def _status_bucket(raw: dict[str, Any]) -> str:
    status_os = raw.get("id_status_work_order")
    status_task = raw.get("id_status_work_order_task")

    if status_os == 3:
        return "finalizada"
    if status_os == 4:
        return "cancelada"
    if status_task == 0:
        return "nao_iniciada"
    return "em_andamento"


def _extract_etiquetas_fracttal(raw: dict[str, Any]) -> list[str]:
    """Etiquetas nativas do Fracttal (campo 'labels' da OS) — ex: "REQUER
    APROVAÇÃO", "EM VERIFICAÇÃO" etc, definidas dentro do próprio Fracttal.
    Diferente das etiquetas locais do app, essas vêm prontas de lá.
    """
    labels = raw.get("labels") or []
    return [
        label.get("description")
        for label in labels
        if label.get("enabled", True) and label.get("description")
    ]


def _normalize_os(raw: dict[str, Any]) -> dict[str, Any]:
    usina = raw.get("groups_1_description") or "Usina não identificada"
    return {
        "folio": raw.get("wo_folio"),
        "titulo": raw.get("description"),
        "nota": raw.get("task_note") or raw.get("note"),
        "usina": usina,
        "cliente": extract_cliente(usina),
        "etm_codigo": raw.get("code"),
        "etm_descricao": raw.get("items_log_description"),
        "status_id": raw.get("id_status_work_order_task"),
        "status_os_id": raw.get("id_status_work_order"),
        "status_bucket": _status_bucket(raw),
        "status_texto": raw.get("task_status"),
        "tecnico": raw.get("personnel_description"),
        "solicitante": raw.get("requested_by"),
        "criado_por": raw.get("created_by"),
        "etiquetas_fracttal": _extract_etiquetas_fracttal(raw),
        "data_criacao": raw.get("creation_date"),
        "data_inicial": raw.get("initial_date"),
        "data_final": raw.get("final_date"),
        "percentual": raw.get("completed_percentage"),
        "url": f"https://apps.fracttal.com/#work_orders/{raw.get('id_work_order')}"
        if raw.get("id_work_order")
        else None,
    }


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------
@app.get("/api/planner")
def get_planner(refresh: bool = False) -> dict[str, Any]:
    try:
        raw_orders = fracttal_client.get_corrective_work_orders(force_refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Fracttal: {exc}") from exc

    columns: dict[str, list[dict[str, Any]]] = {
        "nao_iniciada": [],
        "em_andamento": [],
        "finalizada": [],
    }
    for raw in raw_orders:
        os_norm = _normalize_os(raw)
        bucket = os_norm["status_bucket"]
        if bucket == "cancelada":
            # OS cancelada não é trabalho ativo nem pendente — fica de fora
            # do Planner (mas continua aparecendo no Histórico da usina).
            continue
        columns[bucket].append(os_norm)

    for bucket in columns.values():
        bucket.sort(key=lambda o: o.get("data_criacao") or "", reverse=True)

    total = sum(len(b) for b in columns.values())
    return {
        "nao_iniciadas": columns["nao_iniciada"],
        "em_andamento": columns["em_andamento"],
        "finalizadas": columns["finalizada"],
        "total": total,
    }


@app.get("/api/usinas")
def get_usinas(refresh: bool = False) -> list[dict[str, Any]]:
    try:
        return fracttal_client.get_usinas(force_refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Fracttal: {exc}") from exc


@app.get("/api/usinas/{usina}/historico")
def get_historico_usina(usina: str, refresh: bool = False) -> list[dict[str, Any]]:
    try:
        raw_orders = fracttal_client.get_corrective_work_orders(force_refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Fracttal: {exc}") from exc

    historico = [
        _normalize_os(raw)
        for raw in raw_orders
        if (raw.get("groups_1_description") or "Usina não identificada") == usina
    ]
    historico.sort(key=lambda o: o.get("data_criacao") or "", reverse=True)
    return historico


# ----------------------------------------------------------------------
# Atualização
# ----------------------------------------------------------------------
@app.get("/api/update-check")
def update_check() -> dict[str, Any]:
    result = updater.check_for_update()
    # Não expõe a url interna do asset (exige o token) pro frontend.
    result.pop("_asset_url", None)
    result.pop("_asset_name", None)
    return result


@app.post("/api/update/apply")
def update_apply() -> dict[str, Any]:
    result = updater.check_for_update()
    if not result.get("update_available"):
        raise HTTPException(status_code=409, detail="Nenhuma atualização disponível no momento.")

    asset_url = result.get("_asset_url")
    asset_name = result.get("_asset_name")
    if not asset_url or not asset_name:
        raise HTTPException(status_code=502, detail="Release encontrada, mas sem instalador (.exe) anexado.")

    try:
        updater.apply_update(asset_url, asset_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Falha ao baixar/aplicar atualização: {exc}") from exc

    # O processo atual vai se encerrar sozinho em ~1,5s (ver updater.py) para
    # o instalador conseguir sobrescrever o executável.
    return {"status": "atualizando", "latest_version": result.get("latest_version")}


# ----------------------------------------------------------------------
# Frontend (SPA simples)
# ----------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "templates" / "index.html")
