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


def test_update_product_sku_and_url_preserva_prateleira_manual(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a atualizacao operacional de SKU nao remova a localizacao.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida preservacao da prateleira e da ordem manual.

    Contexto de uso:
        Evita regressao no fluxo de sincronizacao, onde apenas SKU e URL devem
        mudar enquanto a organizacao fisica continua sob controle manual.
    """

    store = ProductStoreService(tmp_path / "products.json")
    original_product = ProductRecord(
        alias="example",
        brand="Marca",
        name="Produto",
        variant="Variante",
        last_known_url="https://antiga",
        last_known_sku="000",
        shelf_number=7,
        display_order=4,
    )
    store.upsert_product(original_product)

    updated_product = store.update_product_sku_and_url(
        product_alias="example",
        new_sku="999",
        new_url="https://nova",
    )

    assert updated_product.shelf_number == 7
    assert updated_product.display_order == 4


def test_replace_product_permite_trocar_alias_sem_duplicar_registro(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar substituicao completa do produto quando o alias muda na edicao.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante que o fluxo de edicao web nao deixa o alias antigo persistido.
    """

    store = ProductStoreService(tmp_path / "products.json")
    original_product = ProductRecord(
        alias="produto_antigo",
        brand="Marca",
        name="Produto",
        variant="100ml",
        last_known_url="https://antiga",
        last_known_sku="001",
    )
    store.upsert_product(original_product)

    updated_product = ProductRecord(
        alias="produto_novo",
        brand="Marca atualizada",
        name="Produto atualizado",
        variant="150ml",
        last_known_url="https://nova",
        last_known_sku="002",
    )

    store.replace_product("produto_antigo", updated_product)

    assert store.get_by_alias("produto_antigo") is None
    found_product = store.get_by_alias("produto_novo")
    assert found_product is not None
    assert found_product.brand == "Marca atualizada"
    assert len(store.list_products()) == 1


def test_upsert_persiste_localizacao_manual_de_prateleira(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a localizacao manual de prateleira seja persistida no storage.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida leitura do produto com shelf_number e display_order.

    Contexto de uso:
        Protege o novo fluxo operacional de atribuicao manual de prateleira.
    """

    store = ProductStoreService(tmp_path / "products.json")
    product = ProductRecord(
        alias="produto_com_prateleira",
        brand="Paco Rabanne",
        name="Produto",
        variant="100ml",
        last_known_url="https://exemplo.com/produto",
        last_known_sku="123",
        shelf_number=4,
        display_order=2,
    )

    store.upsert_product(product)

    found_product = store.get_by_alias("produto_com_prateleira")
    assert found_product is not None
    assert found_product.shelf_number == 4
    assert found_product.display_order == 2


def test_delete_product_remove_registro_existente(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar a exclusao definitiva de um produto persistido no storage.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida remocao do alias e reducao da lista persistida.

    Contexto de uso:
        Protege a acao administrativa de exclusao usada pelo dashboard.
    """

    store = ProductStoreService(tmp_path / "products.json")
    product = ProductRecord(
        alias="produto_excluir",
        brand="Marca",
        name="Produto",
        variant="100ml",
        last_known_url="https://exemplo.com/produto",
        last_known_sku="321",
    )
    store.upsert_product(product)

    removed_product = store.delete_product("produto_excluir")

    assert removed_product.alias == "produto_excluir"
    assert store.get_by_alias("produto_excluir") is None
    assert store.list_products() == []
