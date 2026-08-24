"""App de organização de Ordens de Serviço corretivas de ETM (Grid Co.)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, updater
from .comments import DIAGNOSTIC_OPTIONS, STATUS_POS_OS_OPTIONS, TAG_OPTIONS, comments_client
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
    """Evita que o navegador guarde em cache uma versão antiga do index.html /
    app.js / style.css entre atualizações do app — sem isso, alguém que
    atualiza o executável mas abre uma aba "nova" (que ainda reaproveita o
    cache HTTP de antes) pode acabar com um HTML velho carregando um JS novo
    (ou vice-versa). Um descompasso desses é pior que parecer: o JS novo tenta
    grudar listeners em elementos que só existem no HTML novo, dá erro e trava
    a inicialização inteira — o app fica parado sem nenhuma mensagem de erro
    visível. Por isso isso cobre tanto "/" (o index.html) quanto "/static".
    """
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static"):
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


# Rótulo em PT-BR do status da tarefa exatamente como o Fracttal mostra na
# tela dele (campo id_status_work_order_task). Diferente do "status_bucket"
# (que é a nossa classificação de coluna do Planner, considerando também o
# status da OS), este é só uma tradução direta do status bruto do Fracttal.
_STATUS_FRACTTAL_LABEL = {
    0: "Não iniciada",
    1: "Em progresso",
    2: "Pausada",
    3: "Finalizada",
}


def _normalize_os(raw: dict[str, Any], id_to_folio: dict[int, str] | None = None) -> dict[str, Any]:
    usina = raw.get("groups_1_description") or "Usina não identificada"
    # "os_pai" no Fracttal vem como um ID interno (id_work_order), não o
    # folio que aparece pra quem usa. Tentamos "traduzir" esse ID pro folio
    # cruzando com as outras OS já carregadas nesta mesma consulta — só não
    # dá pra resolver se a OS pai não estiver entre as que buscamos agora.
    id_parent_wo = raw.get("id_parent_wo")
    os_pai_folio = None
    if id_parent_wo and id_to_folio:
        try:
            os_pai_folio = id_to_folio.get(int(id_parent_wo))
        except (TypeError, ValueError):
            os_pai_folio = None
    tipo_os = (raw.get("tasks_log_task_type_main") or "").strip()
    tecnico = (raw.get("personnel_description") or "").strip()
    eh_corretiva = tipo_os.lower() == config.CORRECTIVE_TASK_TYPE.lower()
    # "Em análise": ainda não é uma OS corretiva (não foi a campo), mas está
    # atribuída a um dos analistas de ETM — ver config.ANALISTAS_ETM.
    em_analise = not eh_corretiva and tecnico.lower() in config.ANALISTAS_ETM
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
        "status_fracttal": _STATUS_FRACTTAL_LABEL.get(raw.get("id_status_work_order_task")),
        "tipo_os": tipo_os or None,
        "em_analise": em_analise,
        "tecnico": raw.get("personnel_description"),
        "solicitante": raw.get("requested_by"),
        "criado_por": raw.get("created_by"),
        "etiquetas_fracttal": _extract_etiquetas_fracttal(raw),
        "os_pai_id": id_parent_wo or None,
        "os_pai_folio": os_pai_folio,
        "os_filhas": [f for f in (raw.get("children") or []) if f],
        "data_criacao": raw.get("creation_date"),
        "data_inicial": raw.get("initial_date"),
        "data_final": raw.get("final_date"),
        "percentual": raw.get("completed_percentage"),
        "id_work_order": raw.get("id_work_order"),
        "url": f"https://app.fracttal.com/#work_orders/{raw.get('id_work_order')}"
        if raw.get("id_work_order")
        else None,
    }


def _normalize_subtarefa(raw: dict[str, Any]) -> dict[str, Any]:
    """Um item do formulário/checklist de uma OS — a pergunta (description)
    e a resposta que o técnico preencheu (value), às vezes agrupada.
    """
    return {
        "descricao": raw.get("description"),
        "valor": raw.get("value"),
        "grupo": raw.get("group") or None,
        "obrigatoria": raw.get("is_required"),
        "ordem": raw.get("order_number"),
    }


def _build_id_to_folio(raw_orders: list[dict[str, Any]]) -> dict[int, str]:
    return {
        raw["id_work_order"]: raw["wo_folio"]
        for raw in raw_orders
        if raw.get("id_work_order") and raw.get("wo_folio")
    }


def _safe_label_mappings() -> tuple[dict[str, str], dict[str, str], dict[str, list[str]], dict[str, bool]]:
    # Diagnóstico, status pós-OS, etiquetas e acompanhamento são "extras"
    # guardados no GitHub — se estiver fora do ar por algum motivo, isso não
    # pode derrubar o Planner/Histórico inteiro (o app continua funcionando,
    # só sem eles).
    try:
        return comments_client.get_all_label_mappings()
    except Exception as exc:  # noqa: BLE001
        print(f"[main] Falha ao buscar diagnósticos/status/etiquetas/acompanhamento: {exc}")
        return {}, {}, {}, {}


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------
@app.get("/api/planner")
def get_planner(refresh: bool = False) -> dict[str, Any]:
    try:
        raw_orders = fracttal_client.get_relevant_work_orders(force_refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Fracttal: {exc}") from exc

    id_to_folio = _build_id_to_folio(raw_orders)
    diagnosticos, status_pos_os, tags, acompanhamento = _safe_label_mappings()
    columns: dict[str, list[dict[str, Any]]] = {
        "nao_iniciada": [],
        "em_andamento": [],
        "finalizada": [],
        "cancelada": [],
    }
    for raw in raw_orders:
        os_norm = _normalize_os(raw, id_to_folio)
        os_norm["diagnostico"] = diagnosticos.get(str(os_norm["folio"]))
        os_norm["status_pos_os"] = status_pos_os.get(str(os_norm["folio"]))
        os_norm["etiquetas"] = tags.get(str(os_norm["folio"]), [])
        os_norm["em_acompanhamento"] = acompanhamento.get(str(os_norm["folio"]), False)
        # OS cancelada não é trabalho ativo nem pendente — fica escondida por
        # padrão no Planner, mas o front pode optar por mostrá-la (filtro).
        columns[os_norm["status_bucket"]].append(os_norm)

    for bucket in columns.values():
        bucket.sort(key=lambda o: o.get("data_criacao") or "", reverse=True)

    total = len(columns["nao_iniciada"]) + len(columns["em_andamento"]) + len(columns["finalizada"])
    return {
        "nao_iniciadas": columns["nao_iniciada"],
        "em_andamento": columns["em_andamento"],
        "finalizadas": columns["finalizada"],
        "canceladas": columns["cancelada"],
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
        raw_orders = fracttal_client.get_relevant_work_orders(force_refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Fracttal: {exc}") from exc

    id_to_folio = _build_id_to_folio(raw_orders)
    diagnosticos, status_pos_os, tags, acompanhamento = _safe_label_mappings()
    historico = []
    for raw in raw_orders:
        if (raw.get("groups_1_description") or "Usina não identificada") != usina:
            continue
        os_norm = _normalize_os(raw, id_to_folio)
        os_norm["diagnostico"] = diagnosticos.get(str(os_norm["folio"]))
        os_norm["status_pos_os"] = status_pos_os.get(str(os_norm["folio"]))
        os_norm["etiquetas"] = tags.get(str(os_norm["folio"]), [])
        os_norm["em_acompanhamento"] = acompanhamento.get(str(os_norm["folio"]), False)
        historico.append(os_norm)
    historico.sort(key=lambda o: o.get("data_criacao") or "", reverse=True)
    return historico


@app.get("/api/os/{folio}/subtarefas")
def get_subtarefas(folio: str) -> list[dict[str, Any]]:
    """Itens do formulário/checklist de uma OS (pergunta + resposta do
    técnico) — puxado sob demanda (não faz parte do /api/planner).
    """
    try:
        raw_rows = fracttal_client.get_work_order_subtasks(folio)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Fracttal: {exc}") from exc
    raw_rows.sort(key=lambda r: r.get("order_number") or 0)
    return [_normalize_subtarefa(r) for r in raw_rows]


@app.get("/api/usinas/{usina}/chat")
def get_chat_usina(usina: str, refresh: bool = False) -> list[dict[str, Any]]:
    """Todos os comentários de todas as OS dessa usina, num só feed — usado
    pelo painel de chat consolidado que desliza da direita no Histórico.
    """
    try:
        raw_orders = fracttal_client.get_relevant_work_orders(force_refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao consultar Fracttal: {exc}") from exc

    folio_titulo: dict[str, str] = {}
    for raw in raw_orders:
        if (raw.get("groups_1_description") or "Usina não identificada") != usina:
            continue
        folio = raw.get("wo_folio")
        if folio:
            folio_titulo[str(folio)] = raw.get("description") or ""

    try:
        comentarios = comments_client.get_comments_for_folios(list(folio_titulo.keys()))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao carregar comentários: {exc}") from exc

    for c in comentarios:
        c["titulo_os"] = folio_titulo.get(c["folio"])
    return comentarios


# ----------------------------------------------------------------------
# Comentários (compartilhados entre todo o time, guardados no GitHub)
# ----------------------------------------------------------------------
class ComentarioIn(BaseModel):
    autor: str = Field(min_length=1, max_length=80)
    texto: str = Field(min_length=1, max_length=4000)


@app.get("/api/os/{folio}/comentarios")
def listar_comentarios(folio: str) -> list[dict[str, Any]]:
    try:
        return comments_client.list_comments(folio)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao carregar comentários: {exc}") from exc


@app.post("/api/os/{folio}/comentarios")
def criar_comentario(folio: str, comentario: ComentarioIn) -> dict[str, Any]:
    autor = comentario.autor.strip()
    texto = comentario.texto.strip()
    if not autor or not texto:
        raise HTTPException(status_code=422, detail="Nome e comentário não podem ficar em branco.")
    try:
        return comments_client.add_comment(folio, autor, texto)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao salvar comentário: {exc}") from exc


# ----------------------------------------------------------------------
# Diagnóstico (etiqueta única por OS, compartilhada com o time)
# ----------------------------------------------------------------------
class DiagnosticoIn(BaseModel):
    diagnostico: str | None = None


@app.get("/api/diagnosticos/opcoes")
def opcoes_diagnostico() -> list[str]:
    return DIAGNOSTIC_OPTIONS


@app.post("/api/os/{folio}/diagnostico")
def definir_diagnostico(folio: str, corpo: DiagnosticoIn) -> dict[str, Any]:
    try:
        comments_client.set_diagnostico(folio, corpo.diagnostico)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao salvar diagnóstico: {exc}") from exc
    return {"folio": folio, "diagnostico": corpo.diagnostico}


# ----------------------------------------------------------------------
# Status pós-OS (etiqueta única por OS, compartilhada com o time)
# ----------------------------------------------------------------------
class StatusPosOsIn(BaseModel):
    status_pos_os: str | None = None


@app.get("/api/status-pos-os/opcoes")
def opcoes_status_pos_os() -> list[str]:
    return STATUS_POS_OS_OPTIONS


@app.post("/api/os/{folio}/status-pos-os")
def definir_status_pos_os(folio: str, corpo: StatusPosOsIn) -> dict[str, Any]:
    try:
        comments_client.set_status_pos_os(folio, corpo.status_pos_os)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao salvar status pós-OS: {exc}") from exc
    return {"folio": folio, "status_pos_os": corpo.status_pos_os}


# ----------------------------------------------------------------------
# Etiquetas locais (compartilhadas com o time — várias por OS)
# ----------------------------------------------------------------------
class TagToggleIn(BaseModel):
    tag: str


@app.get("/api/tags/opcoes")
def opcoes_tags() -> list[str]:
    return TAG_OPTIONS


@app.post("/api/os/{folio}/tags/toggle")
def alternar_tag(folio: str, corpo: TagToggleIn) -> dict[str, Any]:
    try:
        etiquetas = comments_client.toggle_tag(folio, corpo.tag)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao salvar etiqueta: {exc}") from exc
    return {"folio": folio, "etiquetas": etiquetas}


# ----------------------------------------------------------------------
# Em Acompanhamento (marcador único por OS, independente de status —
# permite continuar de olho numa OS mesmo depois de finalizada no Fracttal)
# ----------------------------------------------------------------------
class AcompanhamentoIn(BaseModel):
    ativo: bool


@app.post("/api/os/{folio}/acompanhamento")
def definir_acompanhamento(folio: str, corpo: AcompanhamentoIn) -> dict[str, Any]:
    try:
        comments_client.set_acompanhamento(folio, corpo.ativo)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erro ao salvar acompanhamento: {exc}") from exc
    return {"folio": folio, "em_acompanhamento": corpo.ativo}


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
