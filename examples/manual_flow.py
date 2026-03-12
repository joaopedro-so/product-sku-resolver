"""
Script didático para cadastro e resolução de SKU ponta a ponta.

Este exemplo mostra como usar as camadas já implementadas sem depender da API:
1) cadastrar (ou atualizar) um produto no storage
2) executar a resolução para o alias informado
3) exibir resultado rastreável do matcher/resolver
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def configure_project_path() -> None:
    """
    Responsabilidade:
        Garantir que a raiz do projeto esteja no sys.path para imports locais.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Permite executar o script diretamente via `python examples/manual_flow.py`
        sem exigir instalação prévia do pacote em ambiente virtual.
    """

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


configure_project_path()

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver
from backend.utils.fetcher import Fetcher


def build_argument_parser() -> argparse.ArgumentParser:
    """
    Responsabilidade:
        Criar parser de argumentos para execução do fluxo manual.

    Parâmetros:
        Nenhum.

    Retorno:
        Instância de ArgumentParser configurada com todas as opções do script.

    Contexto de uso:
        Mantém a interface de linha de comando explícita e fácil de reutilizar
        em ambiente local para testes rápidos e demonstrações.
    """

    parser = argparse.ArgumentParser(
        description="Cadastro + resolução de SKU usando last_known_url",
    )
    parser.add_argument("--alias", required=True, help="Alias interno do produto")
    parser.add_argument("--brand", required=True, help="Marca estável do produto")
    parser.add_argument("--name", required=True, help="Nome estável do produto")
    parser.add_argument("--variant", required=True, help="Variante estável (ex.: 200ml)")
    parser.add_argument("--url", required=True, help="URL conhecida da página do produto")
    parser.add_argument(
        "--seed-sku",
        default="unknown",
        help="SKU inicial para cadastro (antes da resolução)",
    )
    parser.add_argument(
        "--storage-path",
        default="data/products.json",
        help="Caminho do arquivo JSON de produtos",
    )
    return parser


def register_product(store: ProductStoreService, args: argparse.Namespace) -> ProductRecord:
    """
    Responsabilidade:
        Cadastrar ou atualizar produto no storage antes da etapa de resolução.

    Parâmetros:
        store: Serviço responsável por persistência de produtos.
        args: Namespace com dados fornecidos por linha de comando.

    Retorno:
        ProductRecord persistido para uso na etapa seguinte.

    Contexto de uso:
        Garante que o resolver tenha um produto base com identidade estável
        e URL conhecida para iniciar o processo de atualização de SKU.
    """

    product_to_save = ProductRecord(
        alias=args.alias.strip(),
        brand=args.brand.strip(),
        name=args.name.strip(),
        variant=args.variant.strip(),
        last_known_url=args.url.strip(),
        last_known_sku=str(args.seed_sku).strip(),
    )

    return store.upsert_product(product_to_save)


def main() -> int:
    """
    Responsabilidade:
        Orquestrar fluxo manual de cadastro e resolução para um produto.

    Parâmetros:
        Nenhum (os dados vêm da linha de comando).

    Retorno:
        Código de saída do processo (0 para sucesso, 1 para erro).

    Contexto de uso:
        Entrada principal do script para validar rapidamente o comportamento
        do sistema em ambiente local, antes de integrar com API.
    """

    parser = build_argument_parser()
    args = parser.parse_args()

    try:
        storage_path = Path(args.storage_path)
        product_store = ProductStoreService(storage_path)

        saved_product = register_product(product_store, args)
        print(f"[INFO] Produto cadastrado/atualizado: {saved_product.alias}")

        resolver = ProductResolver(product_store=product_store, fetcher=Fetcher())
        resolve_result = resolver.resolve_sku_for_alias(saved_product.alias)

        print("\n[RESULTADO]")
        print(f"success: {resolve_result.success}")
        print(f"message: {resolve_result.message}")
        print(f"error_code: {resolve_result.error_code}")

        if resolve_result.match_result is not None:
            print(f"score: {resolve_result.match_result.score}")
            print(f"brand_matched: {resolve_result.match_result.brand_matched}")
            print(f"name_matched: {resolve_result.match_result.name_matched}")
            print(f"variant_matched: {resolve_result.match_result.variant_matched}")
            print(f"reasons: {resolve_result.match_result.reasons}")
            print(f"conflicts: {resolve_result.match_result.conflicts}")

        if resolve_result.product is not None:
            print(f"updated_sku: {resolve_result.product.last_known_sku}")
            print(f"updated_url: {resolve_result.product.last_known_url}")

        return 0 if resolve_result.success else 1
    except Exception as error:
        # Tratamento de erro:
        # Capturamos exceções inesperadas para fornecer feedback legível no
        # terminal, mantendo comportamento amigável para quem está testando.
        print(f"[ERRO] Falha na execução do fluxo manual: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
