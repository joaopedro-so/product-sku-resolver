"""
Testes do serviço de armazenamento de produtos.
"""

from pathlib import Path

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService


def test_upsert_and_get_by_alias(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar inserção e recuperação de produto por alias.

    Parâmetros:
        tmp_path: Diretório temporário fornecido pelo pytest.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante que a primeira camada de storage funciona antes da integração
        com API e resolver.
    """

    store = ProductStoreService(tmp_path / "products.json")
    product = ProductRecord(
        alias="one_million_200ml",
        brand="Paco Rabanne",
        name="One Million",
        variant="200ml",
        last_known_url="https://loja.exemplo/produto",
        last_known_sku="123",
    )

    store.upsert_product(product)
    found_product = store.get_by_alias("one_million_200ml")

    assert found_product is not None
    assert found_product.last_known_sku == "123"


def test_update_product_sku_and_url(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar atualização de SKU e URL mantendo identidade estável.

    Parâmetros:
        tmp_path: Diretório temporário fornecido pelo pytest.

    Retorno:
        Nenhum.

    Contexto de uso:
        Assegura regra de negócio de separar dados estáveis de mutáveis.
    """

    store = ProductStoreService(tmp_path / "products.json")
    original_product = ProductRecord(
        alias="example",
        brand="Marca",
        name="Produto",
        variant="Variante",
        last_known_url="https://antiga",
        last_known_sku="000",
    )
    store.upsert_product(original_product)

    updated_product = store.update_product_sku_and_url(
        product_alias="example",
        new_sku="999",
        new_url="https://nova",
    )

    assert updated_product.brand == "Marca"
    assert updated_product.name == "Produto"
    assert updated_product.variant == "Variante"
    assert updated_product.last_known_sku == "999"
    assert updated_product.last_known_url == "https://nova"
