"""
Servico de importacao de seeds internos do catalogo operacional.

Este modulo existe para carregar produtos ja curados manualmente, inclusive
itens legacy que nao dependem mais do site da Renner, sem passar pelo fluxo de
validacao remota usado nos seeds de importacao curada do site.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService
from backend.services.storage_path_service import resolve_project_file


@dataclass(slots=True)
class InternalCatalogSeedImportResult:
    """
    Responsabilidade:
        Representar o resultado de importacao de um produto interno.

    Parametros:
        alias: Alias do item processado.
        success: Indica se o registro foi persistido com sucesso.
        message: Mensagem operacional curta para log ou feedback web.
        product: Produto persistido quando a importacao foi bem-sucedida.

    Retorno:
        Estrutura simples para relatar sucesso ou falha por item.

    Contexto de uso:
        Utilizada pelas rotas administrativas do dashboard para importar seeds
        locais para a Railway sem depender de shell.
    """

    alias: str
    success: bool
    message: str
    product: Optional[ProductRecord] = None


class InternalCatalogSeedService:
    """
    Responsabilidade:
        Importar seeds internos contendo registros completos do catalogo.

    Parametros:
        product_store: Storage definitivo onde os produtos serao gravados.

    Retorno:
        Servico pronto para carregar e aplicar seeds internos versionados.

    Contexto de uso:
        Reutilizado quando a operacao precisa popular a Railway com itens que
        ja foram curados localmente, incluindo produtos legacy e imagens.
    """

    def __init__(self, product_store: ProductStoreService) -> None:
        """
        Responsabilidade:
            Guardar o storage compartilhado que recebera os produtos do seed.

        Parametros:
            product_store: Servico responsavel pela persistencia final.

        Retorno:
            Nenhum.

        Contexto de uso:
            A injecao do store facilita testes e reaproveita toda a logica ja
            existente de validacao, upsert e reconciliacao do catalogo.
        """

        self.product_store = product_store

    def load_products_from_file(self, seed_file_path: Path) -> List[ProductRecord]:
        """
        Responsabilidade:
            Ler um arquivo JSON de seed interno e convertelo em ProductRecord.

        Parametros:
            seed_file_path: Caminho do arquivo versionado com os produtos.

        Retorno:
            Lista de ProductRecord pronta para importacao.

        Contexto de uso:
            Mantem a validacao estrutural do seed em um ponto unico, evitando
            que rotas web precisem lidar com detalhes de parsing do JSON.
        """

        try:
            content = seed_file_path.read_text(encoding="utf-8")
            raw_payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de seed interno contem JSON invalido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de seed interno") from error

        raw_products = raw_payload.get("products", [])
        if not isinstance(raw_products, list):
            raise ValueError("Arquivo de seed interno deve conter uma lista em 'products'")

        loaded_products: List[ProductRecord] = []
        for raw_product in raw_products:
            if not isinstance(raw_product, dict):
                continue
            loaded_products.append(ProductRecord.from_dict(raw_product))

        return loaded_products

    def import_products(self, products: List[ProductRecord]) -> List[InternalCatalogSeedImportResult]:
        """
        Responsabilidade:
            Persistir uma lista de produtos internos no storage atual.

        Parametros:
            products: Lista de produtos completos carregados do seed.

        Retorno:
            Lista de resultados por item processado.

        Contexto de uso:
            Permite que uma falha isolada nao interrompa a importacao inteira,
            deixando o feedback operacional mais claro para a loja.
        """

        results: List[InternalCatalogSeedImportResult] = []
        for product in products:
            try:
                persisted_product = self.product_store.upsert_product(product)
            except Exception as error:
                results.append(
                    InternalCatalogSeedImportResult(
                        alias=product.alias,
                        success=False,
                        message=f"Falha ao importar '{product.alias}': {error}",
                        product=None,
                    )
                )
                continue

            results.append(
                InternalCatalogSeedImportResult(
                    alias=persisted_product.alias,
                    success=True,
                    message=f"Produto '{persisted_product.alias}' importado com sucesso.",
                    product=persisted_product,
                )
            )

        return results


def resolve_builtin_internal_catalog_seed_file(seed_name: str) -> Path:
    """
    Responsabilidade:
        Resolver o caminho de um seed interno de catalogo versionado no projeto.

    Parametros:
        seed_name: Nome logico do seed sem extensao nem caminho.

    Retorno:
        Path absoluto do arquivo JSON correspondente.

    Contexto de uso:
        Permite que o dashboard importe seeds embarcados no codigo mesmo quando
        o volume `/app/data` da Railway estiver separado do repositorio.
    """

    normalized_seed_name = str(seed_name).strip().replace("\\", "/").split("/")[-1]
    if not normalized_seed_name:
        raise ValueError("O nome do seed interno nao pode ser vazio")

    return resolve_project_file(f"backend/resources/imports/{normalized_seed_name}.json")
