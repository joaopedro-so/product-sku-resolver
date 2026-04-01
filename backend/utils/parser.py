"""
Utilitários de parsing HTML para extração de SKU e metadados de página.

A estratégia de SKU segue ordem de fallback para robustez:
1) query param da URL
2) padrões textuais no HTML
3) dados estruturados no HTML
4) fallback configurável
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from typing import Iterable, Optional
from urllib.parse import parse_qs, urljoin, urlparse


@dataclass(slots=True)
class PageData:
    """
    Responsabilidade:
        Representar dados mínimos extraídos da página para validação e resolução.

    Parâmetros:
        url: URL final da página após fetch/redirecionamentos.
        title: Título HTML da página, útil para matching e depuração.
        brand: Marca inferida da página por metadados/padrões textuais.
        name: Nome do produto inferido da página por metadados/título.
        variant: Variante inferida (ex.: 200ml) para reforçar validação.
        sku: SKU extraído pela estratégia de fallback configurada.
        image_url: URL absoluta da imagem principal do produto quando disponível.

    Retorno:
        Instância de PageData com campos opcionais em caso de ausência de sinais.

    Contexto de uso:
        Usado pelo matcher e pelo resolver para validar identidade antes de
        atualizar SKU e URL no armazenamento.
    """

    url: str
    title: Optional[str]
    brand: Optional[str]
    name: Optional[str]
    variant: Optional[str]
    sku: Optional[str]
    image_url: Optional[str] = None
    description: Optional[str] = None


def _normalize_spaces(text: str) -> str:
    """
    Responsabilidade:
        Normalizar espaços e entidades HTML em texto bruto extraído da página.

    Parâmetros:
        text: Texto bruto potencialmente com entidades e espaçamento irregular.

    Retorno:
        Texto limpo com espaços colapsados para facilitar comparações.

    Contexto de uso:
        Função utilitária de parsing para reduzir ruído no conteúdo HTML antes
        da inferência de campos como title, brand e name.
    """

    decoded_text = unescape(text)
    return re.sub(r"\s+", " ", decoded_text).strip()


def _extract_html_head(html_content: str, max_fallback_chars: int = 50000) -> str:
    """
    Responsabilidade:
        Isolar o trecho do `<head>` para reduzir custo de parsing textual.

    Parâmetros:
        html_content: Documento HTML bruto completo.
        max_fallback_chars: Quantidade máxima usada quando `<head>` não existir.

    Retorno:
        String contendo o bloco `<head>` ou um recorte inicial do HTML.

    Contexto de uso:
        Utilizada por extrações de título e metatags para evitar regex custosa
        sobre páginas muito grandes e com muitos scripts inline.
    """

    lowered_html = html_content.lower()
    head_start = lowered_html.find("<head")
    if head_start == -1:
        return html_content[:max_fallback_chars]

    head_open_end = lowered_html.find(">", head_start)
    if head_open_end == -1:
        return html_content[:max_fallback_chars]

    head_close_start = lowered_html.find("</head>", head_open_end)
    if head_close_start == -1:
        return html_content[:max_fallback_chars]

    return html_content[head_start : head_close_start + len("</head>")]


def extract_sku_from_url_query(page_url: str, candidate_keys: Optional[Iterable[str]] = None) -> Optional[str]:
    """
    Responsabilidade:
        Extrair SKU diretamente dos parâmetros da URL quando presente.

    Parâmetros:
        page_url: URL da página de produto onde o SKU pode estar na query.
        candidate_keys: Lista de chaves aceitas para SKU (ex.: sku, id, productId).

    Retorno:
        SKU encontrado como string ou None quando não existe correspondência.

    Contexto de uso:
        Primeiro fallback por ser barato e menos sensível a mudanças de HTML.
    """

    keys_to_check = ["sku", "id", "productId", "product_id"]
    if candidate_keys:
        keys_to_check = list(candidate_keys)

    parsed = urlparse(page_url)
    query_map = parse_qs(parsed.query)

    for key in keys_to_check:
        values = query_map.get(key)
        if values and values[0].strip():
            return values[0].strip()

    return None


def extract_sku_from_text_patterns(html_content: str) -> Optional[str]:
    """
    Responsabilidade:
        Encontrar SKU em padrões textuais comuns presentes no HTML bruto.

    Parâmetros:
        html_content: Documento HTML completo em formato string.

    Retorno:
        SKU identificado por regex ou None quando nenhum padrão casar.

    Contexto de uso:
        Segundo fallback, útil quando o SKU aparece em scripts inline, atributos
        de dados ou trechos textuais não estruturados.
    """

    patterns = [
        re.compile(r'"sku"\s*[:=]\s*"?(\w[\w\-\.]+)"?', re.IGNORECASE),
        re.compile(r"sku\s*[:=]\s*'?(\w[\w\-\.]+)'?", re.IGNORECASE),
        re.compile(r"data-sku\s*=\s*\"([^\"]+)\"", re.IGNORECASE),
        re.compile(r"SKU\s*[:#]\s*([A-Za-z0-9\-\.]+)", re.IGNORECASE),
    ]

    for pattern in patterns:
        matched = pattern.search(html_content)
        if matched:
            candidate_sku = matched.group(1).strip()
            if candidate_sku:
                return candidate_sku

    return None


def extract_sku_from_structured_data(html_content: str) -> Optional[str]:
    """
    Responsabilidade:
        Extrair SKU a partir de blocos estruturados (JSON-LD em script).

    Parâmetros:
        html_content: HTML completo da página de produto.

    Retorno:
        SKU encontrado no JSON estruturado ou None quando indisponível.

    Contexto de uso:
        Terceiro fallback, priorizando fontes semânticas mais estáveis que CSS.
    """

    script_pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )

    for matched_script in script_pattern.finditer(html_content):
        raw_json = matched_script.group(1).strip()
        if not raw_json:
            continue

        try:
            parsed_data = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        possible_sku = _find_sku_in_json(parsed_data)
        if possible_sku:
            return possible_sku

    return None


def _find_sku_in_json(data: object) -> Optional[str]:
    """
    Responsabilidade:
        Percorrer estrutura JSON arbitrária para localizar chave 'sku'.

    Parâmetros:
        data: Estrutura JSON já convertida para tipos Python.

    Retorno:
        SKU encontrado em qualquer nível da estrutura ou None.

    Contexto de uso:
        Função auxiliar para suportar variações de JSON-LD entre varejistas.
    """

    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == "sku" and isinstance(value, str) and value.strip():
                return value.strip()

            nested_sku = _find_sku_in_json(value)
            if nested_sku:
                return nested_sku

    if isinstance(data, list):
        for item in data:
            nested_sku = _find_sku_in_json(item)
            if nested_sku:
                return nested_sku

    return None


def extract_sku_basic(
    page_url: str,
    html_content: str,
    configured_fallback_sku: Optional[str] = None,
) -> Optional[str]:
    """
    Responsabilidade:
        Executar extração básica de SKU usando fallback em ordem definida.

    Parâmetros:
        page_url: URL atual da página para extração por query param.
        html_content: HTML da página para padrões textuais e estruturados.
        configured_fallback_sku: SKU de fallback configurável por ambiente.

    Retorno:
        SKU encontrado pela primeira estratégia válida ou None se tudo falhar.

    Contexto de uso:
        Entrada principal para camada resolver e para parse_page_data.
    """

    sku_from_query = extract_sku_from_url_query(page_url)
    if sku_from_query:
        return sku_from_query

    sku_from_text = extract_sku_from_text_patterns(html_content)
    if sku_from_text:
        return sku_from_text

    sku_from_structured_data = extract_sku_from_structured_data(html_content)
    if sku_from_structured_data:
        return sku_from_structured_data

    if configured_fallback_sku and configured_fallback_sku.strip():
        return configured_fallback_sku.strip()

    return None


def _extract_title(html_content: str) -> Optional[str]:
    """
    Responsabilidade:
        Extrair título da página pelo elemento HTML <title>.

    Parâmetros:
        html_content: HTML bruto da página.

    Retorno:
        Título normalizado ou None quando não encontrado.

    Contexto de uso:
        Fornece sinal simples para matcher e observabilidade do resolver.
    """

    head_content = _extract_html_head(html_content)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", head_content, re.IGNORECASE | re.DOTALL)
    if not title_match:
        return None

    return _normalize_spaces(title_match.group(1)) or None


def _extract_meta_content(html_content: str, meta_name: str) -> Optional[str]:
    """
    Responsabilidade:
        Extrair conteúdo de metatags por name/property com regex tolerante.

    Parâmetros:
        html_content: HTML bruto da página.
        meta_name: Nome/property procurado (ex.: og:title, product:brand).

    Retorno:
        Conteúdo da metatag normalizado ou None.

    Contexto de uso:
        Permite inferir brand/name/variant sem depender de parser HTML pesado.
    """

    head_content = _extract_html_head(html_content)

    # Decisão técnica:
    # O padrão cobre as ordens mais comuns de atributos em meta tags.
    patterns = [
        re.compile(
            rf'<meta[^>]+(?:name|property)=["\']{re.escape(meta_name)}["\'][^>]+content=["\'](.*?)["\']',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            rf'<meta[^>]+content=["\'](.*?)["\'][^>]+(?:name|property)=["\']{re.escape(meta_name)}["\']',
            re.IGNORECASE | re.DOTALL,
        ),
    ]

    for pattern in patterns:
        matched = pattern.search(head_content)
        if matched:
            return _normalize_spaces(matched.group(1)) or None

    return None


def _normalize_asset_url(page_url: str, raw_asset_url: Optional[str]) -> Optional[str]:
    """
    Responsabilidade:
        Transformar URL de asset em caminho absoluto utilizável no frontend.

    Parâmetros:
        page_url: URL base da página do produto para resolver caminhos relativos.
        raw_asset_url: URL bruta extraída de metatags ou atributos HTML.

    Retorno:
        URL absoluta do asset quando válida; caso contrário, None.

    Contexto de uso:
        Utilizada para imagens de produto vindas em formato relativo ou com
        protocolo omitido, comum em páginas de e-commerce.
    """

    normalized_asset_url = str(raw_asset_url or "").strip()
    if not normalized_asset_url:
        return None

    return urljoin(page_url, normalized_asset_url)


def extract_product_image_url(page_url: str, html_content: str) -> Optional[str]:
    """
    Responsabilidade:
        Extrair a imagem principal do produto a partir de metadados da página.

    Parâmetros:
        page_url: URL da página usada como base para normalização.
        html_content: HTML bruto completo da página.

    Retorno:
        URL absoluta da imagem principal ou None quando ausente.

    Contexto de uso:
        Alimenta o dashboard web com uma prévia visual do produto sem depender
        de parsing pesado do corpo inteiro da página.
    """

    candidate_image_url = (
        _extract_meta_content(html_content, "og:image")
        or _extract_meta_content(html_content, "twitter:image")
        or _extract_meta_content(html_content, "twitter:image:src")
    )
    return _normalize_asset_url(page_url=page_url, raw_asset_url=candidate_image_url)


def extract_product_description(html_content: str) -> Optional[str]:
    """
    Responsabilidade:
        Extrair uma descricao curta da pagina a partir de metadados comuns.

    Parametros:
        html_content: HTML bruto completo da pagina.

    Retorno:
        Texto de descricao normalizado ou None quando ausente.

    Contexto de uso:
        Ajuda o auto-preenchimento a preferir nomes mais descritivos e menos
        promocionais do que titulos de vitrine.
    """

    return (
        _extract_meta_content(html_content, "product:description")
        or _extract_meta_content(html_content, "description")
        or _extract_meta_content(html_content, "og:description")
        or _extract_meta_content(html_content, "twitter:description")
    )


def _extract_variant_from_text(text: str) -> Optional[str]:
    """
    Responsabilidade:
        Inferir variante textual simples (ml, g, kg, l) em um bloco de texto.

    Parâmetros:
        text: Texto candidato para inferência de variante.

    Retorno:
        Variante encontrada (ex.: "200ml") ou None.

    Contexto de uso:
        Auxilia parse_page_data quando não existe campo estruturado de variante.
    """

    variant_pattern = re.compile(r"\b(\d+[\.,]?\d*)\s*(ml|g|kg|l)\b", re.IGNORECASE)
    match = variant_pattern.search(text)
    if not match:
        return None

    numeric_part = match.group(1).replace(",", ".")
    unit_part = match.group(2).lower()
    return f"{numeric_part}{unit_part}"


def parse_page_data(
    page_url: str,
    html_content: str,
    configured_fallback_sku: Optional[str] = None,
) -> PageData:
    """
    Responsabilidade:
        Consolidar parsing básico de página em uma estrutura PageData.

    Parâmetros:
        page_url: URL final da página utilizada na extração de sinais.
        html_content: HTML completo para extração de metadados e SKU.
        configured_fallback_sku: SKU opcional para último fallback.

    Retorno:
        PageData com campos extraídos e prontos para matching/resolução.

    Contexto de uso:
        Função de entrada principal para o resolver antes da validação de match.
    """

    extracted_title = _extract_title(html_content)

    # Parsing de HTML com prioridade de fontes:
    # 1) Metatags específicas de produto.
    # 2) Open Graph title como fallback de nome.
    # 3) Título da página como último recurso textual.
    extracted_brand = (
        _extract_meta_content(html_content, "product:brand")
        or _extract_meta_content(html_content, "brand")
        or _extract_meta_content(html_content, "og:brand")
    )

    extracted_name = (
        _extract_meta_content(html_content, "product:name")
        or _extract_meta_content(html_content, "og:title")
        or extracted_title
    )

    extracted_description = extract_product_description(html_content)
    # Decisao tecnica:
    # Em paginas da Renner o `og:title` pode continuar apontando para a
    # variante padrao, enquanto o `<title>` reflete o SKU realmente selecionado
    # na URL. Por isso priorizamos o titulo da pagina antes do nome agregado.
    extracted_variant = (
        _extract_meta_content(html_content, "product:variant")
        or _extract_variant_from_text(extracted_title or "")
        or _extract_variant_from_text(extracted_name or "")
        or _extract_variant_from_text(extracted_description or "")
    )

    extracted_sku = extract_sku_basic(
        page_url=page_url,
        html_content=html_content,
        configured_fallback_sku=configured_fallback_sku,
    )
    extracted_image_url = extract_product_image_url(
        page_url=page_url,
        html_content=html_content,
    )

    return PageData(
        url=page_url.strip(),
        title=extracted_title,
        brand=extracted_brand,
        name=extracted_name,
        description=extracted_description,
        variant=extracted_variant,
        sku=extracted_sku,
        image_url=extracted_image_url,
    )
