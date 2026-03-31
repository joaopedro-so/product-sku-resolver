"""
Testes do servico de agrupamento por produto pai e variantes.
"""

from backend.models.product import ProductRecord
from backend.services.product_group_service import ProductGroupService


def test_group_service_agrupa_variantes_do_mesmo_perfume_em_um_unico_pai() -> None:
    """
    Responsabilidade:
        Garantir que diferentes volumes do mesmo perfume formem um unico grupo.

    Parametros:
        Nenhum.

    Retorno:
        Nenhum; valida agrupamento, ordenacao e selecao de variantes.

    Contexto de uso:
        Protege a nova camada semantica usada pela lista de prateleiras e
        detalhe do produto, evitando cards duplicados por volume.
    """

    group_service = ProductGroupService()
    grouped_products = group_service.group_products(
        [
            ProductRecord(
                alias="good_girl_80ml",
                brand="Carolina Herrera",
                name="Good Girl",
                variant="80ml",
                last_known_url="https://example.com/good-girl?sku=80",
                last_known_sku="80",
                shelf_number=5,
            ),
            ProductRecord(
                alias="good_girl_30ml",
                brand="Carolina Herrera",
                name="Good Girl",
                variant="30ml",
                last_known_url="https://example.com/good-girl?sku=30",
                last_known_sku="30",
                shelf_number=5,
            ),
        ]
    )

    assert len(grouped_products) == 1
    assert grouped_products[0].parent_name == "Good Girl"
    assert [variant.label for variant in grouped_products[0].variants] == ["30ml", "80ml"]
    assert group_service.choose_default_variant(grouped_products[0]).alias == "good_girl_30ml"


def test_group_service_mantem_familias_diferentes_como_grupos_separados() -> None:
    """
    Responsabilidade:
        Garantir que familias distintas nao sejam fundidas pelo agrupamento.

    Parametros:
        Nenhum.

    Retorno:
        Nenhum; valida separacao entre perfumes diferentes da mesma marca.

    Contexto de uso:
        Evita regressao em casos como Good Girl e Very Good Girl, que compartilham
        marca mas representam produtos pai diferentes na operacao.
    """

    group_service = ProductGroupService()
    grouped_products = group_service.group_products(
        [
            ProductRecord(
                alias="good_girl_50ml",
                brand="Carolina Herrera",
                name="Good Girl",
                variant="50ml",
                last_known_url="https://example.com/good-girl?sku=50",
                last_known_sku="50",
                shelf_number=5,
            ),
            ProductRecord(
                alias="very_good_girl_80ml",
                brand="Carolina Herrera",
                name="Very Good Girl",
                variant="80ml",
                last_known_url="https://example.com/very-good-girl?sku=80",
                last_known_sku="80",
                shelf_number=5,
            ),
        ]
    )

    assert len(grouped_products) == 2
    assert {group.parent_name for group in grouped_products} == {"Good Girl", "Very Good Girl"}


def test_group_service_prioriza_page_family_sku_para_identidade_do_produto_pai() -> None:
    """
    Responsabilidade:
        Garantir que o identificador estável da página una variantes do mesmo pai.

    Parametros:
        Nenhum.

    Retorno:
        Nenhum; valida agrupamento por `page_family_sku` mesmo com URLs distintas.

    Contexto de uso:
        Protege o caso real em que a página possui um SKU pai estável e o
        código exibido muda por variante, evitando confundir o código da
        variante com a identidade da família de produto.
    """

    group_service = ProductGroupService()
    grouped_products = group_service.group_products(
        [
            ProductRecord(
                alias="perfume_60ml",
                brand="Marca",
                name="Perfume X",
                variant="60ml",
                last_known_url="https://example.com/perfume-x?sku=abc",
                last_known_sku="abc",
                page_family_sku="page-123",
            ),
            ProductRecord(
                alias="perfume_100ml",
                brand="Marca",
                name="Perfume X",
                variant="100ml",
                last_known_url="https://example.com/perfume-x-100?sku=def",
                last_known_sku="def",
                page_family_sku="page-123",
            ),
        ]
    )

    assert len(grouped_products) == 1
    assert grouped_products[0].parent_page_sku == "page-123"
    assert [variant.product.variant_code for variant in grouped_products[0].variants] == ["abc", "def"]
