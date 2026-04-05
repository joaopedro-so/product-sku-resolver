"""
Fetcher com cache em memória para ciclos de sincronização em lote.

Este módulo existe para reaproveitar o HTML já baixado durante um job de sync,
especialmente quando várias variantes compartilham a mesma página pai.
"""

from __future__ import annotations

from threading import RLock
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.utils.fetcher import FetchResult, Fetcher


class CachedFetcher:
    """
    Responsabilidade:
        Reaproveitar respostas HTTP iguais ou semanticamente equivalentes.

    Parâmetros:
        base_fetcher: Fetcher real usado quando a URL ainda não estiver em cache.

    Retorno:
        Wrapper compatível com `fetch_page` usado pelo resolver.

    Contexto de uso:
        Em sincronização em lote, várias variantes podem apontar para a mesma
        página pai mudando apenas o parâmetro `sku`. Este wrapper reduz fetches
        redundantes e acelera o job sem alterar o contrato do resolver.
    """

    def __init__(self, base_fetcher: Fetcher) -> None:
        """
        Responsabilidade:
            Guardar o fetcher real e preparar o cache em memória.

        Parâmetros:
            base_fetcher: Implementação concreta que executa a requisição HTTP.

        Retorno:
            Nenhum.

        Contexto de uso:
            Criado por job de monitoramento para compartilhar o mesmo cache ao
            longo de todo o lote, mantendo isolamento entre execuções.
        """

        self.base_fetcher = base_fetcher
        self._cache_by_url: dict[str, FetchResult] = {}
        self._cache_lock = RLock()

    def fetch_page(self, target_url: str, extra_headers: dict[str, str] | None = None) -> FetchResult:
        """
        Responsabilidade:
            Buscar uma página usando cache por URL canônica quando possível.

        Parâmetros:
            target_url: URL solicitada pelo resolver.
            extra_headers: Cabeçalhos extras opcionais do fetch original.

        Retorno:
            FetchResult vindo do cache ou da rede.

        Contexto de uso:
            O resolver continua enxergando um fetcher normal. A diferença é que
            o job em lote deixa de baixar a mesma página pai repetidas vezes.
        """

        canonical_url = _build_fetch_cache_key(target_url)
        with self._cache_lock:
            cached_result = self._cache_by_url.get(canonical_url)
            if cached_result is not None:
                return cached_result

        fetched_result = self.base_fetcher.fetch_page(target_url, extra_headers=extra_headers)

        with self._cache_lock:
            self._cache_by_url[canonical_url] = fetched_result

        return fetched_result


def _build_fetch_cache_key(target_url: str) -> str:
    """
    Responsabilidade:
        Normalizar a URL usada como chave de cache do fetch.

    Parâmetros:
        target_url: URL original recebida pelo resolver.

    Retorno:
        URL canônica sem o parâmetro `sku`, quando houver.

    Contexto de uso:
        Em muitas páginas do varejo, `?sku=` apenas seleciona a variante ativa,
        mas o HTML já contém as demais opções. Remover esse parâmetro permite
        reaproveitar a mesma resposta para 30ml, 50ml e 80ml no mesmo lote.
    """

    normalized_url = str(target_url or "").strip()
    if not normalized_url:
        return ""

    parsed_url = urlparse(normalized_url)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)
        if key.lower() != "sku"
    ]
    rebuilt_query = urlencode(query_items)
    return urlunparse(parsed_url._replace(query=rebuilt_query))
