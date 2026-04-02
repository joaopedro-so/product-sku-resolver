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
CODE_WEIGHT = 0.25
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


def _build_observed_identity_text(observed_page_data: PageData) -> str:
    """
    Responsabilidade:
        Consolidar sinais textuais observados da página em um único campo.

    Parâmetros:
        observed_page_data: Dados extraídos do HTML pelo parser.

    Retorno:
        Texto normalizado contendo título, nome e marca observados.

    Contexto de uso:
        Permite matching mais robusto quando o varejista distribui a identidade
        do produto entre múltiplos campos semânticos da página.
    """

    candidate_parts = [
        normalize_text(observed_page_data.brand),
        normalize_text(observed_page_data.name),
        normalize_text(observed_page_data.title),
    ]
    populated_parts = [part for part in candidate_parts if part]
    return " ".join(populated_parts).strip()


def _build_brand_aliases(raw_brand: str) -> List[str]:
    """
    Responsabilidade:
        Derivar aliases simples da marca para matching mais tolerante.

    Parâmetros:
        raw_brand: Marca original cadastrada no produto esperado.

    Retorno:
        Lista normalizada de aliases úteis, incluindo sigla quando aplicável.

    Contexto de uso:
        Algumas páginas mostram a marca por extenso enquanto o nome do perfume
        no cadastro usa uma sigla curta, como "CK". Esse helper reduz falso
        negativo sem depender de mapeamentos manuais espalhados.
    """

    normalized_brand = normalize_text(raw_brand)
    if not normalized_brand:
        return []

    aliases = {normalized_brand}
    brand_parts = [part for part in normalized_brand.split() if part]
    if len(brand_parts) >= 2:
        initials = "".join(part[0] for part in brand_parts if part)
        if len(initials) >= 2:
            aliases.add(initials)

    return sorted(aliases, key=len, reverse=True)


def _strip_brand_aliases(raw_text: str, brand_aliases: List[str]) -> str:
    """
    Responsabilidade:
        Remover aliases de marca do texto para comparar o núcleo do nome.

    Parâmetros:
        raw_text: Texto normalizado que pode conter a marca embutida.
        brand_aliases: Aliases derivados da marca esperada.

    Retorno:
        Texto sem os aliases da marca, com espaços recompactados.

    Contexto de uso:
        Perfumes como "CK Her" podem aparecer no site como
        "Calvin Klein Her". Ao remover a marca dos dois lados, o matcher
        compara apenas a parte realmente distintiva do nome.
    """

    cleaned_text = raw_text
    for alias in brand_aliases:
        if not alias:
            continue
        cleaned_text = re.sub(rf"\b{re.escape(alias)}\b", " ", cleaned_text)

    return re.sub(r"\s+", " ", cleaned_text).strip()


def _is_informative_core_name(raw_text: str) -> bool:
    """
    Responsabilidade:
        Validar se o núcleo do nome ainda carrega informação útil.

    Parâmetros:
        raw_text: Texto já sem a marca, pronto para análise.

    Retorno:
        True quando houver conteúdo minimamente confiável; senão False.

    Contexto de uso:
        Evita aceitar como match textos vazios ou restos muito curtos depois de
        remover a marca do nome do perfume.
    """

    normalized_text = normalize_text(raw_text)
    if len(normalized_text) < 3:
        return False

    informative_tokens = [token for token in normalized_text.split() if len(token) >= 3]
    return bool(informative_tokens)


def _match_variant_with_context(
    expected_variant: str,
    observed_variant: str,
    observed_identity_text: str,
) -> bool:
    """
    Responsabilidade:
        Comparar variante com fallback contextual para produtos de kit.

    Parâmetros:
        expected_variant: Variante esperada já normalizada do cadastro.
        observed_variant: Variante parseada da página já normalizada.
        observed_identity_text: Texto agregado da página com title/name/brand.

    Retorno:
        `True` quando a variante for compatível no modo estrito ou contextual.

    Contexto de uso:
        Alguns kits da Renner expõem volumes dos componentes no HTML e deixam
        de repetir a variante "KIT" no campo parseado. Sem esse fallback, o
        matcher reprova a mesma página mesmo quando o item continua sendo o
        kit correto com o mesmo código operacional.
    """

    if _contains_or_equals(expected_variant, observed_variant):
        return True

    # Decisão técnica:
    # Para kits, aceitamos a presença do marcador textual "kit" no texto
    # agregado da página como evidência de variante, porque o parser pode
    # capturar apenas "50ml" ou "250ml" a partir dos componentes internos.
    if expected_variant == "kit" and "kit" in observed_identity_text.split():
        return True

    return False


def _codes_match_with_sufficient_context(
    expected_product: ProductRecord,
    observed_page_data: PageData,
    brand_matched: bool,
    name_matched: bool,
    variant_matched: bool,
) -> bool:
    """
    Responsabilidade:
        Verificar se o código igual pode reforçar o match com segurança.

    Parâmetros:
        expected_product: Produto persistido usado como referência.
        observed_page_data: Dados da página já parseados.
        brand_matched: Resultado atual da comparação de marca.
        name_matched: Resultado atual da comparação de nome.
        variant_matched: Resultado atual da comparação de variante.

    Retorno:
        `True` quando houver código idêntico e contexto mínimo confiável.

    Contexto de uso:
        O código não deve ser a identidade primária do produto, mas ele é um
        sinal importante em páginas problemáticas da Renner/Ashua, sobretudo
        para kits e páginas que omitem parte do nome comercial no título.
    """

    expected_code = normalize_text(expected_product.variant_code or expected_product.last_known_sku)
    observed_code = normalize_text(observed_page_data.sku)
    if not expected_code or expected_code != observed_code:
        return False

    # Decisão técnica:
    # Exigimos pelo menos marca correta e mais um sinal de contexto para não
    # transformar igualdade de código em critério isolado de aceitação.
    return brand_matched and (name_matched or variant_matched)


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
    normalized_observed_identity_text = _build_observed_identity_text(observed_page_data)
    brand_aliases = _build_brand_aliases(expected_product.brand)
    normalized_expected_name_core = _strip_brand_aliases(
        normalized_expected_name,
        brand_aliases,
    )
    normalized_observed_name_core = _strip_brand_aliases(
        normalized_observed_identity_text,
        brand_aliases,
    )

    # Decisão técnica:
    # Alguns varejistas expõem marca e nome em campos diferentes do HTML
    # (ex.: título da página, og:title e alt de imagem). Por isso usamos
    # também um texto agregado como fallback para reduzir falsos negativos.
    brand_matched = _contains_or_equals(
        normalized_expected_brand,
        normalized_observed_brand,
    ) or _contains_or_equals(
        normalized_expected_brand,
        normalized_observed_identity_text,
    )
    name_matched = _contains_or_equals(
        normalized_expected_name,
        normalized_observed_name,
    ) or _contains_or_equals(
        normalized_expected_name,
        normalized_observed_identity_text,
    ) or (
        _is_informative_core_name(normalized_expected_name_core)
        and _contains_or_equals(
            normalized_expected_name_core,
            normalized_observed_name_core,
        )
    )
    variant_matched = _match_variant_with_context(
        expected_variant=normalized_expected_variant,
        observed_variant=normalized_observed_variant,
        observed_identity_text=normalized_observed_identity_text,
    )
    code_matched = _codes_match_with_sufficient_context(
        expected_product=expected_product,
        observed_page_data=observed_page_data,
        brand_matched=brand_matched,
        name_matched=name_matched,
        variant_matched=variant_matched,
    )

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

    if code_matched:
        score += CODE_WEIGHT
        reasons.append("Código atual compatível com a página validada")

    score = min(score, 1.0)
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
