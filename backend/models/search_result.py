"""
Modelos de resultado de busca usados pela camada de descoberta de URL.

A intenção deste módulo é isolar o contrato de saída dos providers de busca,
permitindo trocar implementações sem quebrar o resolver.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SearchResult:
    """
    Responsabilidade:
        Representar uma URL candidata retornada por um provider de busca.

    Parâmetros:
        url: URL candidata da página de produto encontrada na busca.
        title: Título do resultado para observabilidade e depuração.
        source: Origem do resultado (ex.: nome do provider ou mecanismo).

    Retorno:
        Instância tipada consumida pelo resolver durante tentativas de fallback.

    Contexto de uso:
        Utilizada por SearchProvider.search para desacoplar o contrato entre
        descoberta de links e validação de identidade via matcher.
    """

    url: str
    title: str
    source: str
