"""Ponto de entrada do executável instalado.

Sobe o servidor local do app de ETM e abre o navegador padrão automaticamente.
Fechar esta janela de console encerra o app.
"""
from __future__ import annotations

import socket
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8123


def _porta_livre(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((HOST, porta)) != 0


def _abrir_navegador_quando_pronto(url: str) -> None:
    # Espera o servidor aceitar conexões antes de abrir o navegador.
    for _ in range(100):
        if not _porta_livre(PORT):
            break
        time.sleep(0.1)
    time.sleep(0.3)
    webbrowser.open(url)


def main() -> None:
    porta = PORT
    if not _porta_livre(porta):
        # App já está rodando (outra instância aberta) — só reabre o navegador.
        print(f"O app já está rodando em http://{HOST}:{porta}. Abrindo no navegador...")
        webbrowser.open(f"http://{HOST}:{porta}")
        return

    print("Iniciando o app de ETM da Grid Co...")
    print(f"Endereço local: http://{HOST}:{porta}")
    print("Não feche esta janela enquanto estiver usando o app.\n")

    threading.Thread(
        target=_abrir_navegador_quando_pronto, args=(f"http://{HOST}:{porta}",), daemon=True
    ).start()

    from backend.main import app  # import tardio para logs aparecerem antes

    uvicorn.run(app, host=HOST, port=porta, log_level="warning")


if __name__ == "__main__":
    main()
