"""
Interface de linha de comando para operação local do SKU Resolver.

A CLI reutiliza os mesmos serviços da API para evitar divergência de regra
entre interfaces de consumo humano e integração HTTP.
"""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from backend.models.product import ProductRecord
from backend.models.sku_event import SkuEvent
from backend.services.runtime_context import RuntimeServices, build_runtime_services


def build_parser() -> argparse.ArgumentParser:
    """
    Responsabilidade:
        Construir parser principal e subcomandos da CLI.

    Parâmetros:
        Nenhum.

    Retorno:
        ArgumentParser configurado com comandos operacionais.

    Contexto de uso:
        Chamado no início da execução para interpretar argumentos de terminal.
    """

    parser = argparse.ArgumentParser(prog="python -m cli", description="Operações locais do Product SKU Resolver")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="Lista produtos cadastrados")

    add_parser = subparsers.add_parser("add", help="Adiciona ou atualiza um produto")
    add_parser.add_argument("--alias", required=True)
    add_parser.add_argument("--brand", required=True)
    add_parser.add_argument("--name", required=True)
    add_parser.add_argument("--variant", required=True)
    add_parser.add_argument("--url", required=True)
    add_parser.add_argument("--sku", required=True)

    update_parser = subparsers.add_parser("update", help="Atualiza SKU de um produto")
    update_parser.add_argument("alias")

    subparsers.add_parser("update-all", help="Atualiza SKU de todos os produtos")
    subparsers.add_parser("monitor", help="Executa um ciclo de monitoramento")

    history_parser = subparsers.add_parser("history", help="Lista histórico de um alias")
    history_parser.add_argument("alias")

    subparsers.add_parser("history-all", help="Lista todo o histórico")

    return parser


def _serialize_product(product: ProductRecord) -> str:
    """
    Responsabilidade:
        Converter ProductRecord em JSON legível para saída de terminal.

    Parâmetros:
        product: Produto de domínio a ser serializado para impressão.

    Retorno:
        String JSON formatada com encoding UTF-8 legível.

    Contexto de uso:
        Reaproveitada por comandos list e add para consistência visual.
    """

    return json.dumps(product.to_dict(), ensure_ascii=False)


def _serialize_event(event: SkuEvent) -> str:
    """
    Responsabilidade:
        Converter SkuEvent em JSON legível para saída em terminal.

    Parâmetros:
        event: Evento de histórico a ser serializado para impressão.

    Retorno:
        String JSON com dados de auditoria do evento.

    Contexto de uso:
        Utilizada pelos comandos history e history-all.
    """

    return json.dumps(event.to_dict(), ensure_ascii=False)


def _run_list_command(services: RuntimeServices) -> int:
    """
    Responsabilidade:
        Executar listagem de produtos cadastrados no storage.

    Parâmetros:
        services: Container com dependências compartilhadas da aplicação.

    Retorno:
        Código de saída de processo (0 para sucesso).

    Contexto de uso:
        Implementação do comando `python -m cli list`.
    """

    products = services.product_store.list_products()
    for product in products:
        print(_serialize_product(product))

    print(f"Total de produtos: {len(products)}")
    return 0


def _run_add_command(parsed_args: argparse.Namespace, services: RuntimeServices) -> int:
    """
    Responsabilidade:
        Inserir ou atualizar produto pelo alias informado na linha de comando.

    Parâmetros:
        parsed_args: Namespace com argumentos validados pelo argparse.
        services: Container com dependências compartilhadas da aplicação.

    Retorno:
        Código de saída de processo (0 para sucesso).

    Contexto de uso:
        Implementação do comando `python -m cli add`.
    """

    normalized_product = ProductRecord(
        alias=parsed_args.alias.strip(),
        brand=parsed_args.brand.strip(),
        name=parsed_args.name.strip(),
        variant=parsed_args.variant.strip(),
        last_known_url=parsed_args.url.strip(),
        last_known_sku=parsed_args.sku.strip(),
    )

    saved_product = services.product_store.upsert_product(normalized_product)
    print("Produto salvo com sucesso")
    print(_serialize_product(saved_product))
    return 0


def _run_update_command(parsed_args: argparse.Namespace, services: RuntimeServices) -> int:
    """
    Responsabilidade:
        Atualizar SKU de um único produto com base no alias informado.

    Parâmetros:
        parsed_args: Namespace contendo alias alvo da atualização.
        services: Container com dependências compartilhadas da aplicação.

    Retorno:
        Código de saída (0 em sucesso, 1 em falha operacional).

    Contexto de uso:
        Implementação do comando `python -m cli update <alias>`.
    """

    resolver_result = services.resolver.resolve_sku_for_alias(parsed_args.alias)
    print(resolver_result.message)

    if resolver_result.success and resolver_result.product is not None:
        print(_serialize_product(resolver_result.product))
        return 0

    if resolver_result.error_code:
        print(f"error_code={resolver_result.error_code}")

    return 1


def _run_update_all_command(services: RuntimeServices) -> int:
    """
    Responsabilidade:
        Atualizar SKU de todos os produtos cadastrados em lote.

    Parâmetros:
        services: Container com dependências compartilhadas da aplicação.

    Retorno:
        Código de saída (0 quando todos sucessos, 1 se houver falhas).

    Contexto de uso:
        Implementação do comando `python -m cli update-all`.
    """

    all_products = services.product_store.list_products()
    has_failures = False

    for product in all_products:
        resolver_result = services.resolver.resolve_sku_for_alias(product.alias)
        status_label = "OK" if resolver_result.success else "FALHA"
        print(f"[{status_label}] {product.alias} - {resolver_result.message}")
        if not resolver_result.success:
            has_failures = True

    print(f"Total processado: {len(all_products)}")
    return 1 if has_failures else 0


def _run_monitor_command(services: RuntimeServices) -> int:
    """
    Responsabilidade:
        Executar um ciclo de monitoramento automático sob demanda.

    Parâmetros:
        services: Container com monitor_service e dependências de histórico.

    Retorno:
        Código de saída (0 em execução sem erro global).

    Contexto de uso:
        Implementação do comando `python -m cli monitor`.
    """

    summary = services.monitor_service.run()
    print(
        "Monitor executado: "
        f"processados={summary.processed_count} "
        f"sucessos={summary.success_count} "
        f"erros={summary.error_count} "
        f"eventos={len(summary.emitted_events)}"
    )
    return 0


def _run_history_alias_command(parsed_args: argparse.Namespace, services: RuntimeServices) -> int:
    """
    Responsabilidade:
        Listar histórico de eventos filtrado por alias específico.

    Parâmetros:
        parsed_args: Namespace com alias alvo da consulta.
        services: Container com history_store inicializado.

    Retorno:
        Código de saída (0 para execução bem-sucedida).

    Contexto de uso:
        Implementação do comando `python -m cli history <alias>`.
    """

    events = services.history_store.list_events_by_alias(parsed_args.alias)
    for event in events:
        print(_serialize_event(event))

    print(f"Total de eventos: {len(events)}")
    return 0


def _run_history_all_command(services: RuntimeServices) -> int:
    """
    Responsabilidade:
        Listar todos os eventos persistidos no histórico de monitoramento.

    Parâmetros:
        services: Container com history_store inicializado.

    Retorno:
        Código de saída (0 para execução bem-sucedida).

    Contexto de uso:
        Implementação do comando `python -m cli history-all`.
    """

    events = services.history_store.list_events()
    for event in events:
        print(_serialize_event(event))

    print(f"Total de eventos: {len(events)}")
    return 0


def run_cli(argv: Sequence[str] | None = None, services: RuntimeServices | None = None) -> int:
    """
    Responsabilidade:
        Orquestrar execução da CLI delegando para subcomandos específicos.

    Parâmetros:
        argv: Argumentos opcionais para testes automatizados.
        services: Container opcional para injeção de dependências em testes.

    Retorno:
        Código inteiro de saída do processo de linha de comando.

    Contexto de uso:
        Função principal chamada pelo módulo `python -m cli`.
    """

    parser = build_parser()
    parsed_args = parser.parse_args(argv)
    runtime_services = services or build_runtime_services()

    try:
        if parsed_args.command == "list":
            return _run_list_command(runtime_services)
        if parsed_args.command == "add":
            return _run_add_command(parsed_args, runtime_services)
        if parsed_args.command == "update":
            return _run_update_command(parsed_args, runtime_services)
        if parsed_args.command == "update-all":
            return _run_update_all_command(runtime_services)
        if parsed_args.command == "monitor":
            return _run_monitor_command(runtime_services)
        if parsed_args.command == "history":
            return _run_history_alias_command(parsed_args, runtime_services)
        if parsed_args.command == "history-all":
            return _run_history_all_command(runtime_services)

        print("Comando não suportado")
        return 1
    except Exception as error:
        print(f"Falha inesperada na CLI: {error}")
        return 1


def main() -> None:
    """
    Responsabilidade:
        Servir como entrypoint síncrono executável da interface CLI.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum; encerra processo com código retornado por run_cli.

    Contexto de uso:
        Chamado em execução direta do módulo `python -m cli`.
    """

    raise SystemExit(run_cli())
