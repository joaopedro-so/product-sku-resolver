"""
Servico de organizacao fisica de produtos por prateleira.

Este modulo adiciona uma camada derivada de localizacao para a interface web,
sem alterar o contrato persistido do produto nem o fluxo de SKU/barcode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from backend.models.product import ProductRecord
from backend.services.matcher import normalize_text


@dataclass(frozen=True, slots=True)
class ShelfDefinition:
    """
    Responsabilidade:
        Representar uma prateleira fisica da perfumaria prestigio.

    Parametros:
        shelf_number: Numero fisico da prateleira na loja.
        shelf_title: Titulo visivel da prateleira.
        brand_group: Grupo principal de marca associado a prateleira.
        display_order: Ordem fixa de exibicao na interface.

    Retorno:
        Estrutura imutavel usada pela camada web para montar a navegacao.

    Contexto de uso:
        Serve de base para a tela inicial e para o detalhe de cada prateleira.
    """

    shelf_number: int
    shelf_title: str
    brand_group: str
    display_order: int


@dataclass(frozen=True, slots=True)
class ShelfPlacement:
    """
    Responsabilidade:
        Representar a localizacao derivada de um produto dentro da loja.

    Parametros:
        shelf_number: Numero da prateleira resolvida.
        shelf_title: Nome da prateleira resolvida.
        brand_group: Grupo principal usado no agrupamento.
        display_order: Ordem do produto dentro da prateleira.

    Retorno:
        Estrutura leve para consumo pela interface web.

    Contexto de uso:
        Alimenta cards de prateleira, detalhe do produto e listagens fisicas.
    """

    shelf_number: int
    shelf_title: str
    brand_group: str
    display_order: int


class ShelfService:
    """
    Responsabilidade:
        Resolver a organizacao fisica das prateleiras a partir do catalogo atual.

    Parametros:
        Nenhum.

    Retorno:
        Servico pronto para derivar localizacao e agrupamento sem persistencia.

    Contexto de uso:
        Reutilizado pela interface web para abrir o app direto na visao fisica.
    """

    def list_shelves(self) -> List[ShelfDefinition]:
        """
        Responsabilidade:
            Retornar a lista fixa de prateleiras na ordem fisica correta.

        Parametros:
            Nenhum.

        Retorno:
            Lista de ShelfDefinition com exatamente 9 prateleiras.

        Contexto de uso:
            Base da tela inicial da perfumaria prestigio.
        """

        return [
            ShelfDefinition(1, "Perfumes Árabes", "Perfumes Árabes", 1),
            ShelfDefinition(2, "Azzaro", "Azzaro", 2),
            ShelfDefinition(3, "Calvin Klein", "Calvin Klein", 3),
            ShelfDefinition(4, "Paco Rabanne", "Paco Rabanne", 4),
            ShelfDefinition(5, "Carolina Herrera A", "Carolina Herrera", 5),
            ShelfDefinition(6, "Carolina Herrera B", "Carolina Herrera", 6),
            ShelfDefinition(7, "Lancôme", "Lancôme", 7),
            ShelfDefinition(8, "Giorgio Armani", "Giorgio Armani", 8),
            ShelfDefinition(9, "Ralph Lauren", "Ralph Lauren", 9),
        ]

    def get_shelf(self, shelf_number: int) -> Optional[ShelfDefinition]:
        """
        Responsabilidade:
            Buscar uma prateleira especifica pelo numero fisico.

        Parametros:
            shelf_number: Numero procurado na configuracao fixa.

        Retorno:
            ShelfDefinition quando existir; caso contrario, None.

        Contexto de uso:
            Utilizado para abrir o detalhe de prateleira com validacao segura.
        """

        for shelf in self.list_shelves():
            if shelf.shelf_number == shelf_number:
                return shelf
        return None

    def list_products_for_shelf(self, products: List[ProductRecord], shelf_number: int) -> List[ProductRecord]:
        """
        Responsabilidade:
            Filtrar e ordenar os produtos que pertencem a uma prateleira.

        Parametros:
            products: Catalogo atual carregado do storage.
            shelf_number: Numero da prateleira de interesse.

        Retorno:
            Lista de produtos ordenada conforme a exibicao fisica derivada.

        Contexto de uso:
            Alimenta a tela de detalhe da prateleira sem alterar persistencia.
        """

        placed_products = []
        for product in products:
            placement = self.get_product_placement(product=product, all_products=products)
            if placement and placement.shelf_number == shelf_number:
                placed_products.append((placement.display_order, product.name.lower(), product))

        return [product for _, _, product in sorted(placed_products, key=lambda item: (item[0], item[1]))]

    def get_product_placement(
        self,
        product: ProductRecord,
        all_products: List[ProductRecord],
    ) -> Optional[ShelfPlacement]:
        """
        Responsabilidade:
            Derivar a localizacao fisica de um produto no conjunto atual.

        Parametros:
            product: Produto alvo que precisa de localizacao.
            all_products: Catalogo completo para resolver grupos divididos.

        Retorno:
            ShelfPlacement quando houver correspondencia; senao None.

        Contexto de uso:
            Usado pela tela inicial, detalhe de prateleira e detalhe do produto.
        """

        if product.shelf_number is not None:
            explicit_shelf = self.get_shelf(product.shelf_number)
            if explicit_shelf is not None:
                explicit_display_order = product.display_order or self._build_display_order(product)
                return ShelfPlacement(
                    explicit_shelf.shelf_number,
                    explicit_shelf.shelf_title,
                    explicit_shelf.brand_group,
                    explicit_display_order,
                )

        normalized_brand = normalize_text(product.brand)
        if self._is_arabic_brand(normalized_brand):
            return ShelfPlacement(1, "Perfumes Árabes", "Perfumes Árabes", self._build_display_order(product))

        if "azzaro" in normalized_brand:
            return ShelfPlacement(2, "Azzaro", "Azzaro", self._build_display_order(product))

        if "calvin klein" in normalized_brand:
            return ShelfPlacement(3, "Calvin Klein", "Calvin Klein", self._build_display_order(product))

        if "paco rabanne" in normalized_brand:
            return ShelfPlacement(4, "Paco Rabanne", "Paco Rabanne", self._build_display_order(product))

        if "carolina herrera" in normalized_brand:
            return self._resolve_carolina_herrera_shelf(product=product, all_products=all_products)

        if "lancome" in normalized_brand:
            return ShelfPlacement(7, "Lancôme", "Lancôme", self._build_display_order(product))

        if "giorgio armani" in normalized_brand:
            return ShelfPlacement(8, "Giorgio Armani", "Giorgio Armani", self._build_display_order(product))

        if "ralph lauren" in normalized_brand:
            return ShelfPlacement(9, "Ralph Lauren", "Ralph Lauren", self._build_display_order(product))

        return None

    def _resolve_carolina_herrera_shelf(
        self,
        product: ProductRecord,
        all_products: List[ProductRecord],
    ) -> ShelfPlacement:
        """
        Responsabilidade:
            Dividir produtos da Carolina Herrera entre as prateleiras A e B.

        Parametros:
            product: Produto atual da marca Carolina Herrera.
            all_products: Catalogo completo usado para particionar a marca.

        Retorno:
            ShelfPlacement com prateleira A ou B e ordem derivada.

        Contexto de uso:
            Mantem a divisao fisica sem depender de um campo persistido extra.
        """

        carolina_products = [
            current_product
            for current_product in all_products
            if "carolina herrera" in normalize_text(current_product.brand)
        ]
        ordered_products = sorted(
            carolina_products,
            key=lambda current_product: (
                normalize_text(current_product.name),
                normalize_text(current_product.variant),
                normalize_text(current_product.alias),
            ),
        )
        midpoint_index = max(1, (len(ordered_products) + 1) // 2)
        product_position = next(
            (
                index
                for index, current_product in enumerate(ordered_products, start=1)
                if current_product.alias == product.alias
            ),
            1,
        )

        if product_position <= midpoint_index:
            return ShelfPlacement(5, "Carolina Herrera A", "Carolina Herrera", product_position)

        return ShelfPlacement(6, "Carolina Herrera B", "Carolina Herrera", product_position - midpoint_index)

    def _is_arabic_brand(self, normalized_brand: str) -> bool:
        """
        Responsabilidade:
            Identificar marcas que pertencem ao agrupamento de perfumes arabes.

        Parametros:
            normalized_brand: Marca ja normalizada para comparacao textual.

        Retorno:
            True quando a marca pertencer ao grupo arabe; False caso contrario.

        Contexto de uso:
            Resolve a prateleira 01 sem depender de enumeracao no cadastro.
        """

        arabic_brand_keywords = (
            "lattafa",
            "armaf",
            "afnan",
            "maison alhambra",
            "al haramain",
            "rasasi",
            "khadlaj",
            "al wataniah",
            "swiss arabian",
        )
        return any(keyword in normalized_brand for keyword in arabic_brand_keywords)

    def _build_display_order(self, product: ProductRecord) -> int:
        """
        Responsabilidade:
            Gerar uma ordem estavel simples a partir do identificador do produto.

        Parametros:
            product: Produto que precisa de ordem dentro da prateleira.

        Retorno:
            Inteiro derivado para uso em ordenacao.

        Contexto de uso:
            Mantem a lista previsivel mesmo sem campo persistido de ordem fisica.
        """

        return sum(ord(character) for character in product.alias)
