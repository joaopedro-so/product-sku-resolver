"""
Servico utilitario para resolver caminhos persistentes do projeto.

Este modulo evita que storages importantes dependam do diretório atual do
processo. Isso e essencial para garantir que um produto salvo hoje continue
aparecendo depois de refresh, reinicio ou mudanca da forma como o servidor foi
iniciado.
"""

from __future__ import annotations

from pathlib import Path


def resolve_project_root() -> Path:
    """
    Responsabilidade:
        Descobrir a raiz fisica do repositório a partir deste modulo.

    Parametros:
        Nenhum.

    Retorno:
        Caminho absoluto da raiz do projeto.

    Contexto de uso:
        Serve como ancora estavel para arquivos persistentes como products.json,
        impedindo que o app leia e grave em locais diferentes conforme o cwd.
    """

    return Path(__file__).resolve().parents[2]


def resolve_default_data_file(relative_path_inside_data: str) -> Path:
    """
    Responsabilidade:
        Construir um caminho absoluto dentro da pasta `data` do projeto.

    Parametros:
        relative_path_inside_data: Nome do arquivo ou subcaminho dentro de `data`.

    Retorno:
        Path absoluto apontando para o arquivo persistente esperado.

    Contexto de uso:
        Mantem todos os fallbacks de persistencia apontando para o mesmo lugar,
        mesmo quando o app e iniciado fora da raiz do repositório.
    """

    normalized_relative_path = str(relative_path_inside_data).strip().replace("\\", "/").lstrip("/")
    return resolve_project_root() / "data" / normalized_relative_path


def resolve_project_file(relative_project_path: str) -> Path:
    """
    Responsabilidade:
        Construir um caminho absoluto para qualquer arquivo versionado no projeto.

    Parametros:
        relative_project_path: Subcaminho relativo a raiz do repositorio.

    Retorno:
        Path absoluto apontando para o arquivo ou pasta desejada.

    Contexto de uso:
        Utilizado quando o app precisa ler recursos embarcados no codigo, como
        seeds internos de importacao que nao devem depender do volume `/app/data`.
    """

    normalized_relative_path = str(relative_project_path).strip().replace("\\", "/").lstrip("/")
    return resolve_project_root() / normalized_relative_path
