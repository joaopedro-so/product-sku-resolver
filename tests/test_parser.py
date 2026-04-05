"""
Testes das estratégias básicas de extração de SKU e parsing de PageData.
"""

from backend.utils.parser import (
    extract_brand_from_structured_data,
    extract_product_image_url,
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


def test_extract_brand_from_structured_data() -> None:
    """
    Responsabilidade:
        Garantir extração de marca dentro do JSON-LD quando metatags falham.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reproduz páginas da Renner em que `brand.name` existe apenas no bloco
        estruturado do produto e, sem esse fallback, o matcher derruba o sync.
    """

    html = (
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","brand":{"@type":"Brand","name":"Lancôme"}}'
        "</script>"
    )
    assert extract_brand_from_structured_data(html) == "Lancôme"


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
        <meta property="og:image" content="//cdn.loja.exemplo/produto.jpg" />
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
    assert page_data.image_url == "https://cdn.loja.exemplo/produto.jpg"


def test_parse_page_data_prefers_title_variant_when_og_title_is_stale() -> None:
    """
    Responsabilidade:
        Garantir que a variante siga o `<title>` quando o `og:title` estiver
        preso na variante padrão da página.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reproduz comportamento real da Renner em páginas com query `sku`.
    """

    html = """
    <html>
      <head>
        <title>Perfume CK One Unissex Eau de Toilette 200ml</title>
        <meta property="og:title" content="Ck One: um perfume para ela e para ele 50ml - Lojas Renner" />
      </head>
    </html>
    """

    page_data = parse_page_data("https://loja.exemplo/produto?sku=519045328", html)

    assert page_data.variant == "200ml"


def test_parse_page_data_extracts_brand_from_structured_data_when_meta_is_missing() -> None:
    """
    Responsabilidade:
        Garantir que a marca seja lida do JSON-LD quando a página não publica
        `product:brand`, `brand` ou `og:brand`.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reproduz o caso real do La Vie Est Belle Rose Extra, em que o HTML da
        Renner mantém a marca apenas no bloco estruturado do produto.
    """

    html = """
    <html>
      <head>
        <title>Perfume La Vie Est Belle Rose Extra Eau de Parfum 50ml</title>
        <meta property="og:title" content="Perfume La Vie Est Belle Rose Extra Eau de Parfum 50ml" />
        <script type="application/ld+json">
          {
            "@context":"https://schema.org",
            "@type":"Product",
            "brand":{"@type":"Brand","name":"Lancôme"},
            "sku":"927395028"
          }
        </script>
      </head>
    </html>
    """

    page_data = parse_page_data(
        "https://www.lojasrenner.com.br/p/la-vie-est-belle-rose-extra-eau-de-parfum/-/A-927394990-br.lr?sku=927395028",
        html,
    )

    assert page_data.brand == "Lancôme"
    assert page_data.sku == "927395028"


def test_parse_page_data_extracts_available_variants_from_same_page() -> None:
    """
    Responsabilidade:
        Garantir que o parser extraia todas as variantes publicadas no HTML.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reproduz páginas agrupadas da Renner, como Fame In Love, em que 30ml,
        50ml e 80ml compartilham a mesma página pai e precisam ser resolvidos
        individualmente no sync por variante.
    """

    html = """
    <html>
      <head>
        <title>Rabanne Fame In Love Parfum Elixir 30ml</title>
        <meta property="product:brand" content="Rabanne" />
        <meta property="og:title" content="Rabanne Fame In Love Parfum Elixir 30ml" />
      </head>
      <body>
        <div class="ProductAttributes_contentMain__6Ci0T">
          <label>
            <input type="radio" name="size" data-name="30ml" data-sku="931259416" data-aggkey="TAM30ML" data-type="size" />
          </label>
          <label>
            <input type="radio" name="size" data-name="50ml" data-sku="931259424" data-aggkey="TAM50ML" data-type="size" />
          </label>
          <label>
            <input type="radio" name="size" data-name="80ml" data-sku="931259408" data-aggkey="TAM80ML" data-type="size" />
          </label>
        </div>
        <form id="js-product-form" class="hide">
          <input type="hidden" name="product" value="931259395" />
          <input type="hidden" name="sku" value="931259416" />
        </form>
      </body>
    </html>
    """

    page_data = parse_page_data(
        "https://www.lojasrenner.com.br/p/rabanne-fame-in-love-parfum-elixir/-/A-931259395-br.lr",
        html,
    )

    assert [variant.label for variant in page_data.available_variants] == ["30ml", "50ml", "80ml"]
    assert [variant.sku for variant in page_data.available_variants] == ["931259416", "931259424", "931259408"]
    assert page_data.available_variants[2].site_variant_id == "TAM80ML"


def test_extract_product_image_url_normalizes_protocol_relative_path() -> None:
    """
    Responsabilidade:
        Garantir normalização de imagem principal para URL absoluta utilizável.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Protege a renderização do dashboard quando o varejista usa URLs de
        imagem com protocolo omitido em metadados Open Graph.
    """

    html = """
    <html>
      <head>
        <meta property="og:image" content="//cdn.loja.exemplo/imagem-principal.jpg" />
      </head>
    </html>
    """

    image_url = extract_product_image_url("https://loja.exemplo/produto", html)

    assert image_url == "https://cdn.loja.exemplo/imagem-principal.jpg"
