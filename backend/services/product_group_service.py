"""
Servico de agrupamento de perfumes por produto pai e variantes de volume.

Este modulo cria uma camada semantica acima do storage atual, que continua
persistindo cada SKU como uma linha individual. A interface web consome esse
agrupamento para representar um perfume apenas uma vez e trocar dinamicamente
entre variantes como 30ml, 50ml e 80ml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse

from backend.models.product import ProductRecord
from backend.services.matcher import normalize_text, normalize_variant


@dataclass(slots=True)
class ProductVariantGroupItem:
    """
    Responsabilidade:
        Representar uma variante concreta dentro de um produto pai agrupado.

    Parametros:
        alias: Alias real persistido para a variante.
        label: Rotulo visivel da variante, como 30ml ou 80ml.
        sort_value: Valor numerico usado para ordenar variantes com estabilidade.
        product: Registro plano original da variante no storage.

    Retorno:
        Estrutura leve usada pela camada web ao montar seletores de variantes.

    Contexto de uso:
        Permite trocar SKU, barcode e update target sem perder o alias real
        que continua sendo a identidade operacional de cada variante.
    """

    alias: str
    label: str
    sort_value: float
    product: ProductRecord


@dataclass(slots=True)
class GroupedParentProduct:
    """
    Responsabilidade:
        Representar um perfume pai com suas variantes de volume agrupadas.

    Parametros:
        group_id: Identificador estavel do grupo para UI e memoria local.
        canonical_key: Chave interna usada para agrupamento deterministico.
        parent_name: Nome base do perfume sem separar por volume.
        brand: Marca principal usada na exibicao.
        variants: Lista ordenada de variantes pertencentes ao mesmo perfume.

    Retorno:
        Estrutura de consumo para cards de lista e detalhe do produto.

    Contexto de uso:
        Evita que o frontend trate cada SKU de volume como se fosse um produto
        totalmente diferente quando, na pratica, sao variantes do mesmo perfume.
    """

    group_id: str
    canonical_key: str
    parent_name: str
    brand: str
    variants: List[ProductVariantGroupItem]


class ProductGroupService:
    """
    Responsabilidade:
        Agrupar linhas planas de SKU em produtos pai com variantes.

    Parametros:
        Nenhum.

    Retorno:
        Servico pronto para transformar listas planas de ProductRecord.

    Contexto de uso:
        Reutilizado pelas telas de prateleira e detalhe para representar a
        estrutura correta de um perfume com multiplos volumes.
    """

    def group_products(self, products: List[ProductRecord]) -> List[GroupedParentProduct]:
        """
        Responsabilidade:
            Transformar uma lista plana de produtos em grupos por perfume pai.

        Parametros:
            products: Lista plana vinda do storage atual da aplicacao.

        Retorno:
            Lista de GroupedParentProduct ordenada por nome e marca.

        Contexto de uso:
            Base da nova IA das prateleiras, onde uma familia de perfume deve
            aparecer apenas uma vez, mesmo com varios SKUs de volume.
        """

        grouped_items_map: Dict[str, List[ProductVariantGroupItem]] = {}
        group_identity_map: Dict[str, tuple[str, str]] = {}

        for product in products:
            canonical_key = self._build_group_key(product)
            grouped_items_map.setdefault(canonical_key, []).append(self._build_group_item(product))
            group_identity_map.setdefault(
                canonical_key,
                (
                    self._derive_parent_name(product),
                    self._resolve_display_brand(product),
                ),
            )

        grouped_products: List[GroupedParentProduct] = []
        for canonical_key, variants in grouped_items_map.items():
            parent_name, brand = group_identity_map[canonical_key]
            ordered_variants = sorted(
                variants,
                key=lambda variant_item: (
                    variant_item.sort_value,
                    normalize_variant(variant_item.label),
                    normalize_text(variant_item.product.alias),
                ),
            )
            grouped_products.append(
                GroupedParentProduct(
                    group_id=self._build_group_id(brand=brand, parent_name=parent_name),
                    canonical_key=canonical_key,
                    parent_name=parent_name,
                    brand=brand,
                    variants=ordered_variants,
                )
            )

        return sorted(
            grouped_products,
            key=lambda grouped_product: (
                normalize_text(grouped_product.brand),
                normalize_text(grouped_product.parent_name),
            ),
        )

    def get_group_for_alias(
        self,
        products: List[ProductRecord],
        product_alias: str,
    ) -> Optional[GroupedParentProduct]:
        """
        Responsabilidade:
            Encontrar o grupo de variantes correspondente a um alias especifico.

        Parametros:
            products: Catalogo plano completo carregado do storage.
            product_alias: Alias real da variante atualmente solicitada.

        Retorno:
            GroupedParentProduct quando o alias existir; senao None.

        Contexto de uso:
            Necessario para abrir o detalhe do produto em modo agrupado sem
            perder compatibilidade com as rotas antigas baseadas em alias.
        """

        normalized_alias = str(product_alias).strip()
        if not normalized_alias:
            return None

        for grouped_product in self.group_products(products):
            for variant in grouped_product.variants:
                if variant.alias == normalized_alias:
                    return grouped_product

        return None

    def choose_default_variant(
        self,
        grouped_product: GroupedParentProduct,
        preferred_alias: Optional[str] = None,
    ) -> ProductVariantGroupItem:
        """
        Responsabilidade:
            Definir uma variante inicial estavel para renderizacao.

        Parametros:
            grouped_product: Produto pai com a lista de variantes disponiveis.
            preferred_alias: Alias preferencial quando a tela ja foi aberta em
                uma variante especifica.

        Retorno:
            ProductVariantGroupItem escolhido como variante inicial.

        Contexto de uso:
            Mantem o comportamento previsivel em cards e detalhe do produto,
            sem depender de escolhas aleatorias entre os volumes disponiveis.
        """

        normalized_preferred_alias = str(preferred_alias or "").strip()
        if normalized_preferred_alias:
            for variant in grouped_product.variants:
                if variant.alias == normalized_preferred_alias:
                    return variant

        return grouped_product.variants[0]

    def _build_group_item(self, product: ProductRecord) -> ProductVariantGroupItem:
        """
        Responsabilidade:
            Converter um ProductRecord em uma variante agrupada.

        Parametros:
            product: Produto plano vindo do storage atual.

        Retorno:
            ProductVariantGroupItem pronto para ordenacao e exibicao.

        Contexto de uso:
            Isola a regra de rotulo e ordenacao da variante em um ponto unico.
        """

        variant_label = self._build_variant_label(product)
        return ProductVariantGroupItem(
            alias=product.alias,
            label=variant_label,
            sort_value=self._build_variant_sort_value(variant_label),
            product=product,
        )

    def _build_group_key(self, product: ProductRecord) -> str:
        """
        Responsabilidade:
            Montar uma chave robusta para agrupar variantes do mesmo perfume.

        Parametros:
            product: Produto plano analisado durante o agrupamento.

        Retorno:
            String canonica usada como identidade interna do grupo.

        Contexto de uso:
            Prioriza a URL canonica sem SKU porque, no varejo atual, ela costuma
            representar o produto pai, enquanto a query muda por variante.
        """

        canonical_url_key = self._build_canonical_url_key(product.last_known_url)
        normalized_parent_name = normalize_text(self._derive_parent_name(product))
        normalized_brand = normalize_text(self._resolve_display_brand(product))

        if canonical_url_key:
            return canonical_url_key

        return f"{normalized_brand}::{normalized_parent_name}"

    def _build_canonical_url_key(self, product_url: str) -> str:
        """
        Responsabilidade:
            Remover query params de SKU para obter a URL do produto pai.

        Parametros:
            product_url: URL conhecida da variante persistida no cadastro.

        Retorno:
            Chave canonica derivada da URL ou string vazia quando indisponivel.

        Contexto de uso:
            Ajuda a unir variantes de volume que compartilham a mesma pagina
            base de produto, mudando apenas o SKU na query string.
        """

        normalized_url = str(product_url).strip()
        if not normalized_url:
            return ""

        parsed_url = urlparse(normalized_url)
        if not parsed_url.netloc and not parsed_url.path:
            return ""

        return f"{parsed_url.netloc.lower()}{parsed_url.path.lower()}"

    def _derive_parent_name(self, product: ProductRecord) -> str:
        """
        Responsabilidade:
            Extrair um nome base do perfume sem separar por volume.

        Parametros:
            product: Produto plano de origem.

        Retorno:
            Nome pai mais curto e operacional para a interface.

        Contexto de uso:
            Mantem nomes como "Good Girl" e "La Vie Est Belle" como entidade
            principal, enquanto o ml fica exclusivamente no seletor de variantes.
        """

        raw_name = str(product.name).strip()
        if not raw_name:
            return str(product.alias).strip()

        name_without_variant = re.sub(
            r"\b\d+[\.,]?\d*\s*(ml|g|kg|l)\b",
            " ",
            raw_name,
            flags=re.IGNORECASE,
        )
        name_without_marketing_tail = re.sub(r"\s*:\s*.*$", "", name_without_variant)
        cleaned_name = re.sub(r"\s+", " ", name_without_marketing_tail).strip(" -|,:;")
        return cleaned_name or raw_name

    def _resolve_display_brand(self, product: ProductRecord) -> str:
        """
        Responsabilidade:
            Definir a marca principal exibida para o grupo de variantes.

        Parametros:
            product: Produto plano que fornece os sinais de marca.

        Retorno:
            Marca legivel para interface, ou string vazia quando ausente.

        Contexto de uso:
            Mantem o comportamento atual do app, que ainda usa o campo brand do
            storage como referencia principal de marca nas telas operacionais.
        """

        return str(product.brand).strip()

    def _build_variant_label(self, product: ProductRecord) -> str:
        """
        Responsabilidade:
            Definir o rotulo curto da variante para chips de selecao.

        Parametros:
            product: Produto plano cujo volume sera exibido na interface.

        Retorno:
            Rotulo curto como 30ml, 50ml ou "Padrao" em casos sem variante.

        Contexto de uso:
            Alimenta seletores de variantes compactos em cards e detalhe.
        """

        normalized_variant = normalize_variant(product.variant)
        if normalized_variant:
            return normalized_variant

        extracted_variant_match = re.search(
            r"\b(\d+[\.,]?\d*)\s*(ml|g|kg|l)\b",
            str(product.name),
            flags=re.IGNORECASE,
        )
        if extracted_variant_match:
            numeric_part = extracted_variant_match.group(1).replace(",", ".")
            unit_part = extracted_variant_match.group(2).lower()
            return f"{numeric_part}{unit_part}"

        return "Padrao"

    def _build_variant_sort_value(self, variant_label: str) -> float:
        """
        Responsabilidade:
            Construir valor de ordenacao para manter volumes em ordem crescente.

        Parametros:
            variant_label: Rotulo curto da variante, como 30ml ou 80ml.

        Retorno:
            Numero usado na ordenacao; variantes sem volume ficam no final.

        Contexto de uso:
            Garante que a primeira variante seja a menor ou a mais estavel,
            atendendo a regra de default sem depender da ordem do arquivo.
        """

        normalized_variant = normalize_variant(variant_label)
        volume_match = re.search(r"(\d+[\.,]?\d*)", normalized_variant)
        if not volume_match:
            return 999999.0

        return float(volume_match.group(1).replace(",", "."))

    def _build_group_id(self, brand: str, parent_name: str) -> str:
        """
        Responsabilidade:
            Gerar um identificador estavel para uso em atributos HTML e storage local.

        Parametros:
            brand: Marca exibida para o produto pai.
            parent_name: Nome base do perfume agrupado.

        Retorno:
            String compacta e previsivel para uso no frontend.

        Contexto de uso:
            Permite memorizar a ultima variante escolhida no navegador sem criar
            dependencias de banco ou colunas novas no modelo persistido.
        """

        normalized_id = normalize_text(f"{brand} {parent_name}")
        return normalized_id.replace(" ", "-") or "produto"
