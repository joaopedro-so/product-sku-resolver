"""
Testes da camada de busca desacoplada para redescoberta de URL.
"""

from backend.models.product import ProductRecord
from backend.models.search_result import SearchResult
from backend.search.renner_provider import RennerSearchProvider


def test_search_result_structure() -> None:
    """
    Responsabilidade:
        Validar contrato mínimo do modelo SearchResult.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante compatibilidade entre provider de busca e resolver.
    """

    result = SearchResult(
        url="https://lojasrenner.com.br/p/produto",
        title="Perfume Exemplo",
        source="renner_provider_ddg",
    )

    assert result.url == "https://lojasrenner.com.br/p/produto"
    assert result.title == "Perfume Exemplo"
    assert result.source == "renner_provider_ddg"


def test_renner_provider_builds_expected_query() -> None:
    """
    Responsabilidade:
        Verificar geração de query com brand, name e variant do produto.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Assegura estratégia de busca alinhada ao domínio da Renner.
    """

    product = ProductRecord(
        alias="one_million_200ml",
        brand="Paco Rabanne",
        name="One Million",
        variant="200ml",
        last_known_url="https://lojasrenner.com.br/p/antigo",
        last_known_sku="SKU-OLD",
    )
    provider = RennerSearchProvider()

    query = provider.build_query(product)

    assert query == "site:lojasrenner.com.br Paco Rabanne One Million 200ml"


def test_renner_provider_prioriza_nome_tecnico_na_query() -> None:
    """
    Responsabilidade:
        Garantir que a busca externa use o nome técnico quando ele existir.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum; valida a composição da query focada em matching com o site.

    Contexto de uso:
        Evita que um `displayName` curto ou comercial enfraqueça a qualidade
        da redescoberta de URL em produtos manuais ou religados.
    """

    product = ProductRecord(
        alias="the_icon_edt_100ml",
        brand="Antonio Banderas",
        name="The Icon",
        match_name="Antonio Banderas The Icon Eau de Toilette 100ml",
        variant="100ml",
        last_known_url="https://lojasrenner.com.br/p/antigo",
        last_known_sku="SKU-OLD",
    )
    provider = RennerSearchProvider()

    query = provider.build_query(product)

    assert query == "site:lojasrenner.com.br Antonio Banderas The Icon Eau de Toilette 100ml"
