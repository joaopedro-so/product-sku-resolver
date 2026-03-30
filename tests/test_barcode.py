"""
Testes unitários do gerador de código de barras Code 128.
"""

from urllib.parse import unquote

from backend.utils.barcode import build_code128_svg_data_uri


def test_build_code128_svg_data_uri_returns_svg_data_uri_for_valid_sku() -> None:
    """
    Responsabilidade:
        Garantir geração de SVG inline para SKU válido e suportado.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Protege o contrato usado pelos templates do dashboard web.
    """

    data_uri = build_code128_svg_data_uri("532004934", module_width_px=2, bar_height_px=80)

    assert data_uri is not None
    assert data_uri.startswith("data:image/svg+xml;utf8,")
    assert "<svg" in unquote(data_uri)


def test_build_code128_svg_data_uri_ignores_unknown_placeholder() -> None:
    """
    Responsabilidade:
        Evitar renderização de código de barras para placeholder sem valor real.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Mantém a interface limpa quando o SKU ainda não foi resolvido.
    """

    assert build_code128_svg_data_uri("unknown") is None
