"""
Utilitários para geração de código de barras Code 128 em SVG.

Este módulo implementa uma versão didática do Code 128 subset B para evitar
dependências externas no dashboard web e manter o rendering determinístico.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional
from urllib.parse import quote


# Tabela oficial de padrões do Code 128.
# Cada string representa a largura sequencial de barras e espaços.
CODE128_PATTERNS: List[str] = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]

START_CODE_B = 104
STOP_CODE = 106


def _normalize_barcode_value(raw_value: str) -> str:
    """
    Responsabilidade:
        Normalizar o valor recebido antes da geração do código de barras.

    Parâmetros:
        raw_value: Texto bruto informado pela camada de apresentação.

    Retorno:
        String limpa, sem espaços extras nas extremidades.

    Contexto de uso:
        Garante consistência entre cache, validação e geração do SVG.
    """

    return str(raw_value).strip()


def _is_code128_subset_b_supported(barcode_value: str) -> bool:
    """
    Responsabilidade:
        Validar se o valor pode ser codificado no subset B do Code 128.

    Parâmetros:
        barcode_value: Texto já normalizado para verificação.

    Retorno:
        True quando todos os caracteres estão no intervalo ASCII suportado.

    Contexto de uso:
        Evita renderização inválida no dashboard quando o SKU contiver algum
        caractere fora do conjunto simples que decidimos suportar.
    """

    return all(32 <= ord(character) <= 126 for character in barcode_value)


def _encode_code128_subset_b(barcode_value: str) -> List[int]:
    """
    Responsabilidade:
        Converter o valor textual em sequência de códigos do Code 128-B.

    Parâmetros:
        barcode_value: Valor textual que será transformado em barras.

    Retorno:
        Lista de inteiros contendo start code, payload, checksum e stop.

    Contexto de uso:
        Núcleo da lógica de codificação, isolado para facilitar testes e
        manutenção sem misturar cálculo de checksum com rendering SVG.
    """

    normalized_value = _normalize_barcode_value(barcode_value)
    if not normalized_value:
        raise ValueError("O valor do código de barras está vazio")

    if not _is_code128_subset_b_supported(normalized_value):
        raise ValueError("O valor informado contém caracteres não suportados no Code 128-B")

    encoded_codes: List[int] = [START_CODE_B]
    for character in normalized_value:
        # Regra de codificação:
        # No subset B, o valor do símbolo é o ASCII menos 32.
        encoded_codes.append(ord(character) - 32)

    checksum_value = START_CODE_B
    for position, symbol_code in enumerate(encoded_codes[1:], start=1):
        checksum_value += symbol_code * position

    encoded_codes.append(checksum_value % 103)
    encoded_codes.append(STOP_CODE)
    return encoded_codes


def _build_code128_modules(barcode_value: str) -> List[int]:
    """
    Responsabilidade:
        Expandir os símbolos do Code 128 em larguras de módulos.

    Parâmetros:
        barcode_value: Texto que será convertido em barras e espaços.

    Retorno:
        Lista de larguras sequenciais alternando barra preta e espaço.

    Contexto de uso:
        Etapa intermediária entre a codificação lógica e o desenho do SVG.
    """

    encoded_codes = _encode_code128_subset_b(barcode_value)
    expanded_modules: List[int] = []

    for symbol_code in encoded_codes:
        expanded_modules.extend(int(module_width) for module_width in CODE128_PATTERNS[symbol_code])

    return expanded_modules


def _build_code128_svg(
    barcode_value: str,
    module_width_px: int,
    bar_height_px: int,
    quiet_zone_modules: int = 10,
) -> str:
    """
    Responsabilidade:
        Desenhar o SVG do Code 128 a partir das larguras de módulos.

    Parâmetros:
        barcode_value: Texto a ser representado no código de barras.
        module_width_px: Largura em pixels de um módulo básico.
        bar_height_px: Altura útil das barras em pixels.
        quiet_zone_modules: Espaço em branco lateral exigido para leitura.

    Retorno:
        String SVG pronta para embutir no HTML.

    Contexto de uso:
        Utilizada pela camada web para renderizar imagem escalável e nítida,
        importante para um código de barras realmente bipável.
    """

    module_sequence = _build_code128_modules(barcode_value)
    quiet_zone_px = quiet_zone_modules * module_width_px
    total_modules = sum(module_sequence)
    total_width_px = (total_modules * module_width_px) + (quiet_zone_px * 2)

    current_x = quiet_zone_px
    svg_rectangles: List[str] = []
    is_black_bar = True

    for module_size in module_sequence:
        current_segment_width = module_size * module_width_px

        if is_black_bar:
            svg_rectangles.append(
                f'<rect x="{current_x}" y="0" width="{current_segment_width}" '
                f'height="{bar_height_px}" fill="#111827" />'
            )

        current_x += current_segment_width
        is_black_bar = not is_black_bar

    # Decisão técnica:
    # O fundo branco explícito melhora contraste em telas e impressão,
    # aumentando a chance de leitura por leitores ópticos simples.
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_width_px}" height="{bar_height_px}" '
        f'viewBox="0 0 {total_width_px} {bar_height_px}" '
        f'role="img" aria-label="Código de barras do SKU {barcode_value}">'
        f'<rect x="0" y="0" width="{total_width_px}" height="{bar_height_px}" fill="#ffffff" />'
        f'{"".join(svg_rectangles)}'
        f"</svg>"
    )


@lru_cache(maxsize=512)
def build_code128_svg_data_uri(
    barcode_value: str,
    module_width_px: int = 3,
    bar_height_px: int = 120,
) -> Optional[str]:
    """
    Responsabilidade:
        Gerar um `data URI` SVG do Code 128 para uso direto em templates.

    Parâmetros:
        barcode_value: Valor textual que será convertido em código de barras.
        module_width_px: Largura base de cada módulo em pixels.
        bar_height_px: Altura das barras em pixels.

    Retorno:
        `data URI` com SVG quando o valor for válido; caso contrário, None.

    Contexto de uso:
        Exposta ao dashboard para renderização inline sem arquivo estático,
        sem JavaScript e sem dependências externas.
    """

    normalized_value = _normalize_barcode_value(barcode_value)
    if not normalized_value or normalized_value.lower() == "unknown":
        return None

    if module_width_px <= 0 or bar_height_px <= 0:
        raise ValueError("As dimensões do código de barras devem ser positivas")

    if not _is_code128_subset_b_supported(normalized_value):
        return None

    svg_markup = _build_code128_svg(
        barcode_value=normalized_value,
        module_width_px=module_width_px,
        bar_height_px=bar_height_px,
    )
    return f"data:image/svg+xml;utf8,{quote(svg_markup)}"
