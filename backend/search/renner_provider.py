"""
Provider de busca para descoberta de páginas da Renner.

A implementação usa endpoint HTML de busca para reduzir dependências externas
neste estágio inicial, mantendo extração de links em utilitário simples.
"""

from __future__ import annotations

import re
from socket import timeout as SocketTimeout
from typing import List
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from backend.models.product import ProductRecord
from backend.models.search_result import SearchResult
from backend.search.base_provider import SearchProvider


class RennerSearchProvider(SearchProvider):
    """
    Responsabilidade:
        Buscar candidatos de URL da Renner a partir de dados do produto.

    Parâmetros:
        max_results: Quantidade máxima de resultados retornados ao resolver.
        timeout_seconds: Timeout de requisição para evitar bloqueios longos.
        user_agent: Identificação HTTP para reduzir bloqueios triviais.

    Retorno:
        Provider pronto para pesquisa textual e extração de candidatos.

    Contexto de uso:
        Usado como fallback quando a URL conhecida não resolve corretamente.
    """

    def __init__(
        self,
        max_results: int = 5,
        timeout_seconds: float = 6.0,
        user_agent: str = "ProductSkuResolver/1.0",
    ) -> None:
        """
        Responsabilidade:
            Configurar limites de busca e parâmetros de rede do provider.

        Parâmetros:
            max_results: Limite de candidatos retornados para controlar custo.
            timeout_seconds: Tempo máximo de espera por resposta de busca.
            user_agent: Header HTTP enviado no request de busca.

        Retorno:
            Nenhum.

        Contexto de uso:
            Instanciado no bootstrap e injetado no resolver.
        """

        self.max_results = max(1, max_results)
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def build_query(self, product_record: ProductRecord) -> str:
        """
        Responsabilidade:
            Montar query textual focada no domínio da Renner.

        Parâmetros:
            product_record: Produto com brand, name e variant para compor busca.

        Retorno:
            Query pronta para mecanismo de busca no formato site:dominio termos.

        Contexto de uso:
            Etapa inicial para aumentar precisão da descoberta de URLs.
        """

        # Regra de negócio:
        # Priorizamos identidade estável (marca, nome e variante) para reduzir
        # links genéricos de categoria e aumentar chance de página correta.
        technical_query = str(product_record.match_name).strip()
        if technical_query:
            return f"site:lojasrenner.com.br {technical_query}".strip()

        return (
            f"site:lojasrenner.com.br "
            f"{product_record.brand} {product_record.display_name} {product_record.variant}"
        ).strip()

    def search(self, product_record: ProductRecord) -> List[SearchResult]:
        """
        Responsabilidade:
            Executar busca web e retornar URLs candidatas da Renner.

        Parâmetros:
            product_record: Produto alvo para geração de query de busca.

        Retorno:
            Lista de SearchResult validada e limitada por max_results.

        Contexto de uso:
            Chamado pelo resolver no fluxo de fallback de redescoberta de URL.
        """

        search_query = self.build_query(product_record)
        raw_html = self._fetch_search_html(search_query)
        extracted_results = self._extract_results_from_html(raw_html)
        return extracted_results[: self.max_results]

    def _fetch_search_html(self, search_query: str) -> str:
        """
        Responsabilidade:
            Buscar página HTML de resultados para uma query textual.

        Parâmetros:
            search_query: Query previamente montada com sinais do produto.

        Retorno:
            HTML bruto da página de resultados.

        Contexto de uso:
            Função interna para separar I/O de rede da etapa de parsing.
        """

        encoded_query = quote_plus(search_query)
        search_url = f"https://duckduckgo.com/html/?q={encoded_query}"
        request = Request(search_url, headers={"User-Agent": self.user_agent}, method="GET")

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except TimeoutError as error:
            raise RuntimeError(
                f"Timeout na busca externa da Renner após {self.timeout_seconds:.0f}s"
            ) from error
        except SocketTimeout as error:
            raise RuntimeError(
                f"Timeout na busca externa da Renner após {self.timeout_seconds:.0f}s"
            ) from error
        except Exception as error:
            # Tratamento de erro:
            # Encapsulamos falhas de rede para manter a interface previsível
            # e permitir que o resolver retorne erro controlado de busca.
            raise RuntimeError(f"Falha na busca externa da Renner: {error}") from error

    def _extract_results_from_html(self, html_content: str) -> List[SearchResult]:
        """
        Responsabilidade:
            Extrair links candidatos do HTML de busca com filtros de domínio.

        Parâmetros:
            html_content: HTML bruto retornado pelo mecanismo de busca.

        Retorno:
            Lista de SearchResult sem duplicidade e com URLs válidas.

        Contexto de uso:
            Parsing de HTML da busca para alimentar tentativas do resolver.
        """

        # Parsing de HTML:
        # A marcação esperada no endpoint HTML inclui links com classe
        # result__a. A regex tolera atributos extras para robustez mínima.
        anchor_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        unique_urls: set[str] = set()
        search_results: List[SearchResult] = []

        for matched_anchor in anchor_pattern.finditer(html_content):
            candidate_url = matched_anchor.group(1).strip()
            candidate_title = re.sub(r"<[^>]+>", " ", matched_anchor.group(2))
            normalized_title = re.sub(r"\s+", " ", candidate_title).strip()

            if not self._is_candidate_url_allowed(candidate_url):
                continue

            if candidate_url in unique_urls:
                continue

            unique_urls.add(candidate_url)
            search_results.append(
                SearchResult(
                    url=candidate_url,
                    title=normalized_title or "Resultado sem título",
                    source="renner_provider_ddg",
                )
            )

        return search_results

    def _is_candidate_url_allowed(self, candidate_url: str) -> bool:
        """
        Responsabilidade:
            Validar se a URL candidata pertence ao domínio alvo esperado.

        Parâmetros:
            candidate_url: URL bruta extraída da página de resultados.

        Retorno:
            True para URLs da Renner com esquema http/https; senão False.

        Contexto de uso:
            Regra de segurança para evitar navegar em domínios irrelevantes.
        """

        parsed = urlparse(candidate_url)
        if parsed.scheme not in {"http", "https"}:
            return False

        host = (parsed.netloc or "").lower()
        return "lojasrenner.com.br" in host
