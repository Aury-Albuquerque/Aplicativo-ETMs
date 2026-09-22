"""Configuração do app.

Em desenvolvimento, as credenciais vêm do arquivo .env na raiz do projeto.
No executável empacotado para o time (instalador), não existe .env junto —
por decisão da Grid Co., a credencial de conta da empresa (não pessoal) fica
embutida como valor padrão abaixo, já que o uso é só interno.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Credenciais padrão da conta Fracttal da Grid Co., usadas quando não há
# variáveis de ambiente/.env configuradas (caso do app instalado no time).
_DEFAULT_CLIENT_ID = "G0814m2Vq3Mj5DO6qT"
_DEFAULT_CLIENT_SECRET = "OrjrMKcDrGLwDkWtnBBQGqK9gFrJPT0y"

FRACTTAL_CLIENT_ID = os.getenv("FRACTTAL_CLIENT_ID") or _DEFAULT_CLIENT_ID
FRACTTAL_CLIENT_SECRET = os.getenv("FRACTTAL_CLIENT_SECRET") or _DEFAULT_CLIENT_SECRET

FRACTTAL_TOKEN_URL = "https://one.fracttal.com/oauth/token"
FRACTTAL_API_BASE = "https://app.fracttal.com/api"

# Texto usado para identificar ativos de Estação Meteorológica pela descrição
ETM_DESCRIPTION_MARKERS = ["estação meteorológica", "estacao meteorologica"]

# Valor exato do campo tasks_log_task_type_main que identifica OS corretivas
CORRECTIVE_TASK_TYPE = "Corretiva"

# OS de ETM também aparecem tipadas como "Administrativa" no Fracttal (ex:
# coleta/análise de dados, abertura de chamado de garantia) — são trabalho
# de ETM de verdade, só não passam pelo campo. Trazemos elas também.
ADMINISTRATIVE_TASK_TYPE = "Administrativa"

# Antes de uma OS de ETM virar corretiva (ida a campo), ela passa por uma
# etapa de análise, feita por essas pessoas. Trazemos também as OS de ETM
# atribuídas a elas, mesmo que ainda não estejam marcadas como "Corretiva",
# pra dar visibilidade dessa fila de análise no Planner.
ANALISTAS_ETM = {"joão vieira", "aury albuquerque"}

# OS cujo SOLICITANTE (requested_by) é uma dessas pessoas conta como "Campo"
# mesmo que o técnico responsável seja um analista de ETM — nesses casos a
# solicitação já nasce como uma ida a campo, não uma análise de engenharia.
SOLICITANTES_CAMPO_FORCADO = {"joão vieira"}

# ----------------------------------------------------------------------
# Atualização automática (releases do GitHub)
# ----------------------------------------------------------------------
# Repositório privado onde as versões do app são publicadas. O token abaixo é
# somente-leitura (permissão "Contents: Read-only" nesse único repositório) —
# mesmo que alguém extraia esse valor do .exe, o máximo que consegue fazer é
# ler esse repositório, que só contém o código do app e os instaladores.
GITHUB_REPO = "Aury-Albuquerque/Aplicativo-ETMs"
_DEFAULT_GITHUB_TOKEN = "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"
GITHUB_UPDATE_TOKEN = os.getenv("GITHUB_UPDATE_TOKEN") or _DEFAULT_GITHUB_TOKEN
GITHUB_API_BASE = "https://api.github.com"

# ----------------------------------------------------------------------
# Publicação de releases (uso local, só na máquina de build)
# ----------------------------------------------------------------------
# Token com permissão "Contents: Read and write" nesse repo — precisa disso
# pra criar a Release e subir o instalador como asset. Diferente dos dois
# acima, ESTE NUNCA tem fallback hardcoded aqui: só existe se vier do .env
# local. Ele não pode ir embutido no .exe (senão qualquer pessoa que
# instalou o app conseguiria extrair um token capaz de escrever no repo).
GITHUB_RELEASE_TOKEN = os.getenv("GITHUB_RELEASE_TOKEN")

# ----------------------------------------------------------------------
# Comentários compartilhados por OS (guardados como Issues do mesmo repo)
# ----------------------------------------------------------------------
# Token separado, com permissão SÓ de "Issues: Read and write" (sem acesso
# ao código) — mesmo que alguém extraia esse valor do .exe, o máximo que
# consegue é ler/criar comentários, nunca alterar o código do app.
_DEFAULT_GITHUB_COMMENTS_TOKEN = (
    "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"
)
GITHUB_COMMENTS_TOKEN = os.getenv("GITHUB_COMMENTS_TOKEN") or _DEFAULT_GITHUB_COMMENTS_TOKEN

if not FRACTTAL_CLIENT_ID or not FRACTTAL_CLIENT_SECRET:
    raise RuntimeError(
        "FRACTTAL_CLIENT_ID / FRACTTAL_CLIENT_SECRET não configurados. "
        "Verifique o arquivo .env na raiz do projeto."
    )
