"""
Testes do bootstrap de caminhos persistentes do runtime.
"""

from __future__ import annotations

from pathlib import Path

from backend.services.runtime_context import _resolve_history_path, _resolve_storage_path
from backend.services.storage_path_service import resolve_default_data_file


def test_runtime_context_resolve_storage_path_independe_do_cwd(monkeypatch, tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o storage padrao nao dependa do diretorio atual do processo.

    Parametros:
        monkeypatch: Fixture do pytest para alterar o cwd temporariamente.
        tmp_path: Diretorio temporario usado como cwd alternativo.

    Retorno:
        Nenhum; valida que o fallback aponta para a raiz real do projeto.

    Contexto de uso:
        Protege o bug em que o app salvava produtos em arquivos diferentes
        conforme a forma de inicializacao do servidor.
    """

    monkeypatch.chdir(tmp_path)

    resolved_path = _resolve_storage_path()

    assert resolved_path == resolve_default_data_file("products.json")
    assert resolved_path.is_absolute()


def test_runtime_context_resolve_history_path_independe_do_cwd(monkeypatch, tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir consistencia tambem para o historico compartilhado do app.

    Parametros:
        monkeypatch: Fixture do pytest para alterar o cwd temporariamente.
        tmp_path: Diretorio temporario usado como cwd alternativo.

    Retorno:
        Nenhum; valida o fallback absoluto do arquivo de historico.

    Contexto de uso:
        Mantem o runtime inteiro ancorado na mesma raiz de persistencia.
    """

    monkeypatch.chdir(tmp_path)

    resolved_path = _resolve_history_path()

    assert resolved_path == resolve_default_data_file("history.json")
    assert resolved_path.is_absolute()
