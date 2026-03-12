"""
Camada de matching entre produto cadastrado e dados extraídos da página.

Este módulo valida identidade estável (brand, name, variant) e calcula score
explicável para rastreabilidade de decisões no fluxo de resolução.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

from backend.models.product import ProductRecord
from backend.utils.parser import PageData

NAME_WEIGHT = 0.5
BRAND_WEIGHT = 0.3
VARIANT_WEIGHT = 0.2
DEFAULT_MATCH_THRESHOLD = 0.7


@dataclass(slots=True)
class MatchResult:
    """
    Responsabilidade:
        Representar resultado completo do matching com rastreabilidade.

    Parâmetros:
        matched: Flag final indicando se a página corresponde ao produto.
        score: Pontuação agregada com pesos explícitos por atributo.
        reasons: Evidências positivas encontradas durante a comparação.
        conflicts: Divergências identificadas entre esperado e extraído.
        brand_matched: Resultado da comparação de marca.
        name_matched: Resultado da comparação de nome.
        variant_matched: Resultado da comparação de variante.

    Retorno:
        Estrutura de auditoria para consumo por resolver e API.

    Contexto de uso:
        Usada para evitar atualização de SKU quando identidade não for confiável.
    """

    matched: bool
    score: float
    reasons: List[str]
    conflicts: List[str]
    brand_matched: bool
    name_matched: bool
    variant_matched: bool


def normalize_text(raw_text: Optional[str]) -> str:
    """
    Responsabilidade:
        Normalizar texto para comparação robusta entre fontes heterogêneas.

    Parâmetros:
        raw_text: Texto original vindo de cadastro ou parsing da página.

    Retorno:
        Texto sem acentos, em caixa baixa e com espaços normalizados.

    Contexto de uso:
        Base para matching tolerante a diferenças de acentuação e formatação.
    """

    if not raw_text:
        return ""

    decomposed_text = unicodedata.normalize("NFKD", raw_text)
    without_accents = "".join(
        character for character in decomposed_text if not unicodedata.combining(character)
    )

    lowered_text = without_accents.lower()
    alphanumeric_text = re.sub(r"[^a-z0-9\s]", " ", lowered_text)
    return re.sub(r"\s+", " ", alphanumeric_text).strip()


def normalize_variant(raw_variant: Optional[str]) -> str:
    """
    Responsabilidade:
        Normalizar variante preservando equivalência entre formatos comuns.

    Parâmetros:
        raw_variant: Variante textual original (ex.: "200 ml" ou "200ml").

    Retorno:
        Variante normalizada em formato compacto (ex.: "200ml").

    Contexto de uso:
        Reduz falsos negativos em comparação de volume/peso no matcher.
    """

    normalized_variant = normalize_text(raw_variant)
    if not normalized_variant:
        return ""

    # Decisão técnica:
    # Compactamos espaços entre número e unidade para considerar equivalentes
    # formatos comuns como "200 ml" e "200ml".
    compact_variant = re.sub(r"(\d+)\s+(ml|g|kg|l)\b", r"\1\2", normalized_variant)
    return compact_variant


def _contains_or_equals(expected: str, observed: str) -> bool:
    """
    Responsabilidade:
        Verificar correspondência textual flexível entre esperado e observado.

    Parâmetros:
        expected: Valor esperado já normalizado.
        observed: Valor observado já normalizado.

    Retorno:
        True quando há igualdade ou contenção bidirecional; senão False.

    Contexto de uso:
        Evita rigidez excessiva no matching de nome/marca entre fontes distintas.
    """

    if not expected or not observed:
        return False

    return expected == observed or expected in observed or observed in expected


def match_product_with_page(
    expected_product: ProductRecord,
    observed_page_data: PageData,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> MatchResult:
    """
    Responsabilidade:
        Comparar identidade do produto cadastrado com dados da página extraída.

    Parâmetros:
        expected_product: Produto de referência persistido no cadastro.
        observed_page_data: Dados parseados da página baixada via fetcher.
        match_threshold: Limiar mínimo para considerar correspondência válida.

    Retorno:
        MatchResult com score, flags e rastreabilidade detalhada.

    Contexto de uso:
        Etapa crítica do resolver para impedir atualização indevida de SKU.
    """

    reasons: List[str] = []
    conflicts: List[str] = []

    normalized_expected_brand = normalize_text(expected_product.brand)
    normalized_expected_name = normalize_text(expected_product.name)
    normalized_expected_variant = normalize_variant(expected_product.variant)

    normalized_observed_brand = normalize_text(observed_page_data.brand)
    normalized_observed_name = normalize_text(observed_page_data.name)
    normalized_observed_variant = normalize_variant(observed_page_data.variant)

    brand_matched = _contains_or_equals(normalized_expected_brand, normalized_observed_brand)
    name_matched = _contains_or_equals(normalized_expected_name, normalized_observed_name)
    variant_matched = _contains_or_equals(normalized_expected_variant, normalized_observed_variant)

    score = 0.0
    if name_matched:
        score += NAME_WEIGHT
        reasons.append("Nome compatível com o cadastro")
    else:
        conflicts.append("Nome divergente entre cadastro e página")

    if brand_matched:
        score += BRAND_WEIGHT
        reasons.append("Marca compatível com o cadastro")
    else:
        conflicts.append("Marca divergente entre cadastro e página")

    if variant_matched:
        score += VARIANT_WEIGHT
        reasons.append("Variante compatível com o cadastro")
    else:
        conflicts.append("Variante divergente entre cadastro e página")

    matched = score >= match_threshold
    if matched:
        reasons.append(f"Score final {score:.2f} acima do limiar {match_threshold:.2f}")
    else:
        conflicts.append(f"Score final {score:.2f} abaixo do limiar {match_threshold:.2f}")

    return MatchResult(
        matched=matched,
        score=round(score, 4),
        reasons=reasons,
        conflicts=conflicts,
        brand_matched=brand_matched,
        name_matched=name_matched,
        variant_matched=variant_matched,
    )
