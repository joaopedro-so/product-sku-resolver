"""
Testes unitários da camada de matching de identidade de produto.
"""

from backend.models.product import ProductRecord
from backend.services.matcher import match_product_with_page, normalize_text
from backend.utils.parser import PageData


def _build_expected_product() -> ProductRecord:
    """
    Responsabilidade:
        Construir produto base reutilizável para cenários de matching.

    Parâmetros:
        Nenhum.

    Retorno:
        ProductRecord com identidade estável de referência.

    Contexto de uso:
        Evita duplicação de fixture textual nos testes unitários.
    """

    return ProductRecord(
        alias="one_million_200ml",
        brand="Paco Rabanne",
        name="One Million",
        variant="200ml",
        last_known_url="https://loja.exemplo/produto",
        last_known_sku="000",
    )


def test_normalize_text_handles_accents_and_case() -> None:
    """
    Responsabilidade:
        Garantir normalização robusta para acentos, caixa e espaços.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Base para reduzir falso negativo causado por variações de escrita.
    """

    assert normalize_text("  ÁGUA   de  Colônia ") == "agua de colonia"


def test_match_score_positive_case() -> None:
    """
    Responsabilidade:
        Validar score completo quando brand, name e variant coincidem.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante respeito aos pesos explícitos definidos para matching.
    """

    expected_product = _build_expected_product()
    observed_page = PageData(
        url="https://loja.exemplo/produto",
        title="One Million 200 ml",
        brand="Paco Rabanne",
        name="One Million",
        variant="200 ml",
        sku="111",
    )

    result = match_product_with_page(expected_product, observed_page)

    assert result.matched is True
    assert result.score == 1.0
    assert result.brand_matched is True
    assert result.name_matched is True
    assert result.variant_matched is True


def test_match_negative_case() -> None:
    """
    Responsabilidade:
        Garantir mismatch quando identidade da página não corresponde.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Evita atualização indevida de SKU com página de outro produto.
    """

    expected_product = _build_expected_product()
    observed_page = PageData(
        url="https://loja.exemplo/outro",
        title="Alien 90ml",
        brand="Mugler",
        name="Alien",
        variant="90ml",
        sku="222",
    )

    result = match_product_with_page(expected_product, observed_page)

    assert result.matched is False
    assert result.score == 0.0
    assert len(result.conflicts) >= 1


def test_match_handles_accents_and_case() -> None:
    """
    Responsabilidade:
        Validar matching positivo mesmo com acento e caixa divergentes.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Protege compatibilidade entre cadastro limpo e conteúdo heterogêneo.
    """

    expected_product = ProductRecord(
        alias="agua_colonia_200ml",
        brand="Pácô Rabánne",
        name="Água de Colônia",
        variant="200ml",
        last_known_url="https://loja.exemplo/produto",
        last_known_sku="000",
    )

    observed_page = PageData(
        url="https://loja.exemplo/produto",
        title="AGUA DE COLONIA 200 ML",
        brand="paco rabanne",
        name="agua de colonia",
        variant="200 ml",
        sku="333",
    )

    result = match_product_with_page(expected_product, observed_page)

    assert result.matched is True
    assert result.score == 1.0


def test_variant_equivalence_200ml_and_200_ml() -> None:
    """
    Responsabilidade:
        Confirmar equivalência semântica entre formatos de variante comuns.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Evita penalização por formatação textual de unidade de medida.
    """

    expected_product = _build_expected_product()
    observed_page = PageData(
        url="https://loja.exemplo/produto",
        title="One Million 200 ml",
        brand="Paco Rabanne",
        name="One Million",
        variant="200 ml",
        sku="444",
    )

    result = match_product_with_page(expected_product, observed_page)

    assert result.variant_matched is True


def test_match_uses_title_and_name_as_fallback_identity_signals() -> None:
    """
    Responsabilidade:
        Garantir matching robusto quando a marca não vem em campo dedicado.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reproduz cenário real de varejista em que nome e marca aparecem
        distribuídos entre `title` e `name`, mas não em `brand`.
    """

    expected_product = ProductRecord(
        alias="lancome_belle_30ml",
        brand="LANCOME",
        name="La Vie Est Belle Eau De Parfum",
        variant="30ml",
        last_known_url="https://loja.exemplo/produto",
        last_known_sku="unknown",
    )

    observed_page = PageData(
        url="https://loja.exemplo/produto?sku=532004934",
        title="Perfume Perfume La Vie Est Belle Eau De Parfum Feminino 30ml",
        brand=None,
        name="Lâncome La Vie est Belle: uma fragrância inspiradora 30ml - Lojas Renner",
        variant="30ml",
        sku="532004934",
    )

    result = match_product_with_page(expected_product, observed_page)

    assert result.matched is True
    assert result.brand_matched is True
    assert result.name_matched is True
    assert result.variant_matched is True


def test_match_accepts_brand_alias_inside_expected_name_core() -> None:
    """
    Responsabilidade:
        Garantir matching quando a marca abreviada faz parte do nome esperado.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reproduz casos como "CK Her", em que o site usa "Calvin Klein Her"
        e o cadastro operacional mantém a versão abreviada.
    """

    expected_product = ProductRecord(
        alias="calvin_klein_ck_her_50ml",
        brand="Calvin Klein",
        name="CK Her",
        variant="50ml",
        last_known_url="https://loja.exemplo/produto",
        last_known_sku="unknown",
    )

    observed_page = PageData(
        url="https://loja.exemplo/produto?sku=519032834",
        title="Perfume Calvin Klein Her Feminino Eau de Toilette 50ml",
        brand=None,
        name="Perfume Calvin Klein Her Feminino Eau de Toilette 50ml - Lojas Renner",
        variant="50ml",
        sku="519032834",
    )

    result = match_product_with_page(expected_product, observed_page)

    assert result.matched is True
    assert result.brand_matched is True
    assert result.name_matched is True
    assert result.variant_matched is True
