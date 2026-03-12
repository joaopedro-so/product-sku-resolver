"""
Testes das estratégias básicas de extração de SKU e parsing de PageData.
"""

from backend.utils.parser import (
    extract_sku_basic,
    extract_sku_from_structured_data,
    extract_sku_from_text_patterns,
    extract_sku_from_url_query,
    parse_page_data,
)


def test_extract_sku_from_url_query() -> None:
    """
    Responsabilidade:
        Garantir extração de SKU quando ele está no query param da URL.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Valida o primeiro fallback por ser o mais barato computacionalmente.
    """

    url = "https://loja.exemplo/produto?sku=546594103"
    assert extract_sku_from_url_query(url) == "546594103"


def test_extract_sku_from_text_patterns() -> None:
    """
    Responsabilidade:
        Garantir extração de SKU em padrões textuais do HTML.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre o segundo fallback quando query param não existe.
    """

    html = '<div data-sku="ABC-123"></div>'
    assert extract_sku_from_text_patterns(html) == "ABC-123"


def test_extract_sku_from_structured_data() -> None:
    """
    Responsabilidade:
        Garantir extração de SKU em JSON-LD estruturado.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre o terceiro fallback para páginas com marcação semântica.
    """

    html = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","sku":"STR-777"}'
        "</script>"
    )
    assert extract_sku_from_structured_data(html) == "STR-777"


def test_extract_sku_basic_with_configurable_fallback() -> None:
    """
    Responsabilidade:
        Garantir uso do fallback configurável quando outras estratégias falham.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Protege o comportamento mínimo esperado em casos sem sinal de SKU.
    """

    html = "<html><body>Sem sku explícito</body></html>"
    assert (
        extract_sku_basic(
            page_url="https://loja.exemplo/produto",
            html_content=html,
            configured_fallback_sku="DEFAULT-001",
        )
        == "DEFAULT-001"
    )


def test_parse_page_data_extracts_core_fields() -> None:
    """
    Responsabilidade:
        Validar parsing básico de metadados e SKU em estrutura PageData.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante contrato mínimo para etapa de matching e resolução.
    """

    html = """
    <html>
      <head>
        <title>One Million 200 ml - Loja Exemplo</title>
        <meta property="product:brand" content="Paco Rabanne" />
        <meta property="og:title" content="One Million 200 ml" />
      </head>
      <body>
        <span data-sku="546594103"></span>
      </body>
    </html>
    """

    page_data = parse_page_data("https://loja.exemplo/produto", html)

    assert page_data.brand == "Paco Rabanne"
    assert page_data.name == "One Million 200 ml"
    assert page_data.variant == "200ml"
    assert page_data.sku == "546594103"
