"""
Contrato base da camada de busca para redescoberta de URLs de produto.

Este módulo define interface abstrata para que cada varejista tenha sua
estratégia de busca isolada e intercambiável.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from backend.models.product import ProductRecord
from backend.models.search_result import SearchResult


class SearchProvider(ABC):
    """
    Responsabilidade:
        Definir contrato mínimo para providers de busca desacoplados.

    Parâmetros:
        Nenhum no contrato base.

    Retorno:
        Classe abstrata usada por implementações concretas.

    Contexto de uso:
        Injetada no resolver para fallback de URL quando last_known_url falha.
    """

    @abstractmethod
    def search(self, product_record: ProductRecord) -> List[SearchResult]:
        """
        Responsabilidade:
            Retornar lista ordenada de URLs candidatas para um produto.

        Parâmetros:
            product_record: Produto alvo usado para montar a estratégia de busca.

        Retorno:
            Lista de SearchResult priorizada por relevância do provider.

        Contexto de uso:
            Chamado pelo resolver após falha na validação da URL conhecida.
        """

        raise NotImplementedError
