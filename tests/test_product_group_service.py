"""
Testes do servico de agrupamento por produto pai e variantes.
"""

import json
from pathlib import Path

from backend.models.product import ProductRecord
from backend.services.manual_product_group_service import ManualProductGroupService
from backend.services.product_group_service import ProductGroupService


def _build_group_service_with_manual_file(tmp_path: Path, payload: dict) -> ProductGroupService:
    """
    Responsabilidade:
        Criar o servico de agrupamento apontando para um arquivo manual isolado.

    Parametros:
        tmp_path: Diretorio temporario usado pelo pytest para isolar arquivos.
        payload: Conteudo JSON que sera salvo como override manual.

    Retorno:
        ProductGroupService configurado para consumir o arquivo temporario.

    Contexto de uso:
        Mantem os testes deterministas sem depender do arquivo real versionado
        em `data/manual_product_groups.json`.
    """

    manual_group_file = tmp_path / "manual_product_groups.json"
    manual_group_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return ProductGroupService(
        manual_group_service=ManualProductGroupService(storage_file_path=manual_group_file)
    )


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


def test_group_service_aplica_override_manual_antes_do_agrupamento_automatico(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a curadoria manual una apenas as variantes corretas.

    Parametros:
        tmp_path: Diretorio temporario usado para o arquivo de override.

    Retorno:
        Nenhum; valida precedencia do agrupamento manual e fallback automatico.

    Contexto de uso:
        Protege cenarios reais em que o site trata volumes iguais como paginas
        separadas e o app precisa reconstruir a estrutura correta do perfume.
    """

    group_service = _build_group_service_with_manual_file(
        tmp_path=tmp_path,
        payload={
            "groups": [
                {
                    "group_id": "the_icon_edt",
                    "family_name": "The Icon",
                    "display_name": "The Icon Eau de Toilette",
                    "brand": "Antonio Banderas",
                    "product_type": "Eau de Toilette",
                    "variant_members": [
                        {"alias": "the_icon_edt_50ml", "label": "50ml", "display_order": 2},
                        {"alias": "the_icon_edt_100ml", "label": "100ml", "display_order": 1},
                    ],
                }
            ]
        },
    )
    grouped_products = group_service.group_products(
        [
            ProductRecord(
                alias="the_icon_edt_50ml",
                brand="Antonio Banderas",
                name="The Icon Eau de Toilette",
                variant="50ml",
                last_known_url="https://example.com/the-icon-edt-50",
                last_known_sku="sku-edt-50",
                shelf_number=2,
            ),
            ProductRecord(
                alias="the_icon_edt_100ml",
                brand="Antonio Banderas",
                name="The Icon Eau de Toilette",
                variant="100ml",
                last_known_url="https://example.com/the-icon-edt-100",
                last_known_sku="sku-edt-100",
                shelf_number=2,
            ),
            ProductRecord(
                alias="the_icon_edp_100ml",
                brand="Antonio Banderas",
                name="The Icon Eau de Parfum",
                variant="100ml",
                last_known_url="https://example.com/the-icon-edp-100",
                last_known_sku="sku-edp-100",
                shelf_number=2,
            ),
            ProductRecord(
                alias="the_icon_attitude_100ml",
                brand="Antonio Banderas",
                name="The Icon Attitude",
                variant="100ml",
                last_known_url="https://example.com/the-icon-attitude-100",
                last_known_sku="sku-attitude-100",
                shelf_number=2,
            ),
        ]
    )

    assert len(grouped_products) == 3
    assert [group.parent_name for group in grouped_products] == [
        "The Icon Attitude",
        "The Icon Eau de Parfum",
        "The Icon Eau de Toilette",
    ]

    manual_group = next(group for group in grouped_products if group.parent_name == "The Icon Eau de Toilette")
    assert manual_group.family_name == "The Icon"
    assert manual_group.product_type == "Eau de Toilette"
    assert manual_group.is_manual_override is True
    assert [variant.alias for variant in manual_group.variants] == [
        "the_icon_edt_100ml",
        "the_icon_edt_50ml",
    ]
    assert [variant.label for variant in manual_group.variants] == ["100ml", "50ml"]


def test_group_service_mantem_agrupamento_automatico_para_itens_sem_override(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o fallback automatico continue funcionando para o restante.

    Parametros:
        tmp_path: Diretorio temporario usado para o arquivo de override.

    Retorno:
        Nenhum; valida convivencia entre grupos manuais e automaticos.

    Contexto de uso:
        Protege a escalabilidade da curadoria, permitindo evolucao gradual sem
        obrigar o time a cadastrar overrides para todo o catalogo.
    """

    group_service = _build_group_service_with_manual_file(
        tmp_path=tmp_path,
        payload={
            "groups": [
                {
                    "group_id": "the_icon_edt",
                    "display_name": "The Icon Eau de Toilette",
                    "brand": "Antonio Banderas",
                    "variant_members": [
                        {"alias": "the_icon_edt_50ml", "label": "50ml"},
                        {"alias": "the_icon_edt_100ml", "label": "100ml"},
                    ],
                }
            ]
        },
    )
    grouped_products = group_service.group_products(
        [
            ProductRecord(
                alias="the_icon_edt_50ml",
                brand="Antonio Banderas",
                name="The Icon Eau de Toilette",
                variant="50ml",
                last_known_url="https://example.com/the-icon-edt-50",
                last_known_sku="sku-edt-50",
                shelf_number=2,
            ),
            ProductRecord(
                alias="the_icon_edt_100ml",
                brand="Antonio Banderas",
                name="The Icon Eau de Toilette",
                variant="100ml",
                last_known_url="https://example.com/the-icon-edt-100",
                last_known_sku="sku-edt-100",
                shelf_number=2,
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
            ProductRecord(
                alias="good_girl_80ml",
                brand="Carolina Herrera",
                name="Good Girl",
                variant="80ml",
                last_known_url="https://example.com/good-girl?sku=80",
                last_known_sku="80",
                shelf_number=5,
            ),
        ]
    )

    assert len(grouped_products) == 2
    assert {group.parent_name for group in grouped_products} == {
        "Good Girl",
        "The Icon Eau de Toilette",
    }
    automatic_group = next(group for group in grouped_products if group.parent_name == "Good Girl")
    assert automatic_group.is_manual_override is False
    assert [variant.label for variant in automatic_group.variants] == ["30ml", "80ml"]
