"""App de organização de Ordens de Serviço corretivas de ETM (Grid Co.)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .fracttal_client import fracttal_client

# Quando empacotado com PyInstaller (--onefile), os arquivos de dados (o
# frontend) são extraídos para uma pasta temporária apontada por
# sys._MEIPASS. Em desenvolvimento, usamos a estrutura normal do projeto.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS"))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="ETM Grid Co.")

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


def _normalize_os(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "folio": raw.get("wo_folio"),
        "titulo": raw.get("description"),
        "nota": raw.get("task_note") or raw.get("note"),
        "usina": raw.get("groups_1_description") or "Usina não identificada",
        "etm_codigo": raw.get("code"),
        "etm_descricao": raw.get("items_log_description"),
        "status_id": raw.get("id_status_work_order_task"),
        "status_os_id": raw.get("id_status_work_order"),
        "status_bucket": _status_bucket(raw),
        "status_texto": raw.get("task_status"),
        "tecnico": raw.get("personnel_description"),
        "solicitante": raw.get("requested_by"),
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
# Frontend (SPA simples)
# ----------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "templates" / "index.html")
