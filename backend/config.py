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

if not FRACTTAL_CLIENT_ID or not FRACTTAL_CLIENT_SECRET:
    raise RuntimeError(
        "FRACTTAL_CLIENT_ID / FRACTTAL_CLIENT_SECRET não configurados. "
        "Verifique o arquivo .env na raiz do projeto."
    )
