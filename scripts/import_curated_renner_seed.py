"""
Script utilitario para importar seeds curados da Renner para o catalogo local.

O objetivo deste script e permitir cargas controladas e reproduziveis sem
precisar abrir o formulario manual para cada perfume.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

# Responsabilidade:
#   Garantir que a raiz do projeto esteja no import path quando o script for
#   executado diretamente a partir da pasta `scripts/`.
# Parametros:
#   Nenhum.
# Retorno:
#   Nenhum.
# Contexto de uso:
#   Evita depender de instalacao do projeto como pacote apenas para rodar a
#   importacao operacional em ambiente local ou servidor.
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.services.curated_renner_import_service import CuratedRennerImportService
from backend.services.curated_renner_import_service import resolve_builtin_curated_seed_file
from backend.services.runtime_context import build_runtime_services
from backend.utils.fetcher import Fetcher


def build_argument_parser() -> argparse.ArgumentParser:
    """
    Responsabilidade:
        Construir o parser de argumentos aceitos pelo script de importacao.

    Parametros:
        Nenhum.

    Retorno:
        Instancia de ArgumentParser configurada com as opcoes suportadas.

    Contexto de uso:
        Mantem a definicao da interface de linha de comando isolada, o que
        facilita leitura do script e futuras extensoes operacionais.
    """

    parser = argparse.ArgumentParser(description="Importa um seed curado da Renner para o catalogo local.")
    parser.add_argument(
        "--seed-file",
        required=False,
        help="Caminho do arquivo JSON com a lista curada de produtos da Renner.",
    )
    parser.add_argument(
        "--seed-name",
        required=False,
        help="Nome de um seed interno embarcado no codigo, sem a extensao .json.",
    )
    return parser


def run_import(seed_file_path: Path) -> int:
    """
    Responsabilidade:
        Executar a importacao de um seed curado usando o storage atual do app.

    Parametros:
        seed_file_path: Caminho do JSON que descreve os produtos a importar.

    Retorno:
        Codigo de saida do processo, seguindo a convencao 0 para sucesso.

    Contexto de uso:
        Funcao principal do script para permitir uso manual e testes futuros
        sem depender do bloco `if __name__ == "__main__"`.
    """

    runtime_services = build_runtime_services()
    import_service = CuratedRennerImportService(
        fetcher=Fetcher(default_timeout_seconds=20.0, user_agent="Mozilla/5.0"),
        product_store=runtime_services.product_store,
    )
    entries = import_service.load_entries_from_file(seed_file_path)
    results = import_service.import_entries(entries)

    successful_results = [result for result in results if result.success]
    failed_results = [result for result in results if not result.success]

    print(f"Importacao concluida: {len(successful_results)} sucesso(s), {len(failed_results)} falha(s).")
    for result in results:
        print(result.message)

    return 0 if not failed_results else 1


def _resolve_seed_file_from_arguments(parsed_arguments: argparse.Namespace) -> Path:
    """
    Responsabilidade:
        Traduzir os argumentos do CLI no caminho final do seed a importar.

    Parametros:
        parsed_arguments: Namespace ja validado pelo argparse.

    Retorno:
        Path absoluto do arquivo de seed que sera processado.

    Contexto de uso:
        Mantem o script flexivel para ler tanto arquivos externos quanto seeds
        internos embarcados no codigo do projeto.
    """

    raw_seed_file = str(getattr(parsed_arguments, "seed_file", "") or "").strip()
    if raw_seed_file:
        return Path(raw_seed_file)

    raw_seed_name = str(getattr(parsed_arguments, "seed_name", "") or "").strip()
    if raw_seed_name:
        return resolve_builtin_curated_seed_file(raw_seed_name)

    raise ValueError("Informe --seed-file ou --seed-name para executar a importacao.")


def main(argv: Sequence[str] | None = None) -> int:
    """
    Responsabilidade:
        Orquestrar leitura de argumentos e execucao da importacao curada.

    Parametros:
        argv: Lista opcional de argumentos para uso programatico em testes.

    Retorno:
        Codigo de saida inteiro para o processo chamador.

    Contexto de uso:
        Mantem o ponto de entrada do script curto e didatico para operadores.
    """

    argument_parser = build_argument_parser()
    parsed_arguments = argument_parser.parse_args(argv)
    return run_import(_resolve_seed_file_from_arguments(parsed_arguments))


if __name__ == "__main__":
    raise SystemExit(main())
