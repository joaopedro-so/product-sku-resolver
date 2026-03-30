"""
Camada de resolução de SKU com fallback de descoberta automática de URL.

Fluxo atual:
- tenta URL conhecida (last_known_url)
- valida identidade via matcher
- em falha, busca novas URLs via SearchProvider
- testa candidatos com limite e escolhe maior score validado
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from backend.models.product import ProductRecord
from backend.models.search_result import SearchResult
from backend.search.base_provider import SearchProvider
from backend.services.matcher import MatchResult, match_product_with_page
from backend.services.product_store_service import ProductStoreService
from backend.utils.fetcher import Fetcher
from backend.utils.parser import PageData, parse_page_data

SEARCH_MATCH_THRESHOLD = 0.75
MAX_SEARCH_CANDIDATES = 5


@dataclass(slots=True)
class ResolveResult:
    """
    Responsabilidade:
        Representar resultado explicável da tentativa de resolução de SKU.

    Parâmetros:
        success: Indica se a resolução concluiu atualização válida.
        message: Mensagem descritiva para logs e respostas de API.
        product: Produto atualizado em caso de sucesso.
        page_data: Dados parseados da página, úteis para depuração.
        match_result: Resultado detalhado do matching de identidade.
        error_code: Código semântico de erro para tratamento externo.

    Retorno:
        Estrutura padronizada para integração com camadas superiores.

    Contexto de uso:
        Retornado pelo resolver para comunicação clara de sucesso/falha.
    """

    success: bool
    message: str
    product: Optional[ProductRecord]
    page_data: Optional[PageData]
    match_result: Optional[MatchResult]
    error_code: Optional[str]


class ProductResolver:
    """
    Responsabilidade:
        Orquestrar resolução de SKU com fallback de busca desacoplado.

    Parâmetros:
        product_store: Serviço de armazenamento de produtos.
        fetcher: Cliente HTTP reutilizável para download das páginas.
        search_provider: Provider opcional para redescoberta de URLs.
        search_match_threshold: Limiar mínimo para aceitar candidato de busca.
        max_search_candidates: Quantidade máxima de URLs testadas no fallback.

    Retorno:
        Instância de resolver pronta para execução por alias.

    Contexto de uso:
        Camada de serviço chamada pela API para atualização individual de SKU.
    """

    def __init__(
        self,
        product_store: ProductStoreService,
        fetcher: Fetcher,
        search_provider: Optional[SearchProvider] = None,
        search_match_threshold: float = SEARCH_MATCH_THRESHOLD,
        max_search_candidates: int = MAX_SEARCH_CANDIDATES,
    ) -> None:
        """
        Responsabilidade:
            Inicializar dependências e parâmetros de segurança da resolução.

        Parâmetros:
            product_store: Abstração de leitura/escrita de produtos.
            fetcher: Abstração de requisição HTTP para páginas remotas.
            search_provider: Estratégia opcional para redescoberta de URL.
            search_match_threshold: Limiar para aceitar candidato de busca.
            max_search_candidates: Limite de tentativas para evitar loops.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construído no bootstrap da aplicação com injeção de dependências.
        """

        self.product_store = product_store
        self.fetcher = fetcher
        self.search_provider = search_provider
        self.search_match_threshold = search_match_threshold
        self.max_search_candidates = max(1, max_search_candidates)
        self.logger = logging.getLogger(__name__)

    def resolve_sku_for_alias(self, product_alias: str) -> ResolveResult:
        """
        Responsabilidade:
            Executar fluxo completo de resolução para um alias específico.

        Parâmetros:
            product_alias: Alias do produto que deve ter SKU validado/atualizado.

        Retorno:
            ResolveResult contendo sucesso/falha e detalhes de rastreabilidade.

        Contexto de uso:
            Método principal do resolver com fallback de descoberta de URL.
        """

        normalized_alias = product_alias.strip()
        if not normalized_alias:
            return ResolveResult(
                success=False,
                message="Alias informado está vazio",
                product=None,
                page_data=None,
                match_result=None,
                error_code="INVALID_ALIAS",
            )

        expected_product = self.product_store.get_by_alias(normalized_alias)
        if expected_product is None:
            return ResolveResult(
                success=False,
                message=f"Produto com alias '{normalized_alias}' não encontrado",
                product=None,
                page_data=None,
                match_result=None,
                error_code="PRODUCT_NOT_FOUND",
            )

        # Decisão técnica:
        # Primeiro testamos a URL conhecida por ser o caminho de menor custo.
        known_url_result = self._try_resolve_with_url(
            expected_product=expected_product,
            candidate_url=expected_product.last_known_url,
            source_label="last_known_url",
            use_custom_threshold=False,
        )
        if known_url_result.success:
            return known_url_result

        # Regra de negócio:
        # Mantemos compatibilidade com o fluxo anterior quando não há provider
        # de busca configurado, retornando o erro original da URL conhecida.
        if self.search_provider is None:
            return known_url_result

        self.logger.info(
            "Fallback de busca iniciado para alias=%s após falha em last_known_url: %s",
            expected_product.alias,
            known_url_result.error_code,
        )

        search_results = self._search_candidates(expected_product)
        if not search_results:
            return ResolveResult(
                success=False,
                message="Nenhum candidato encontrado na busca automática",
                product=None,
                page_data=known_url_result.page_data,
                match_result=known_url_result.match_result,
                error_code="NO_SEARCH_RESULTS",
            )

        best_candidate_result = self._resolve_using_search_results(expected_product, search_results)
        if best_candidate_result is None:
            return ResolveResult(
                success=False,
                message="Nenhum candidato de busca atingiu score mínimo confiável",
                product=None,
                page_data=known_url_result.page_data,
                match_result=known_url_result.match_result,
                error_code="NO_VALID_SEARCH_CANDIDATE",
            )

        return best_candidate_result

    def _search_candidates(self, product: ProductRecord) -> list[SearchResult]:
        """
        Responsabilidade:
            Consultar provider de busca com tratamento de erro controlado.

        Parâmetros:
            product: Produto alvo usado para construir query de descoberta.

        Retorno:
            Lista de SearchResult limitada por max_search_candidates.

        Contexto de uso:
            Etapa intermediária do fallback de busca no resolver.
        """

        try:
            all_results = self.search_provider.search(product) if self.search_provider else []
        except Exception as error:
            # Tratamento de erro:
            # Falhas de provider não devem quebrar o processo inteiro; apenas
            # registramos e retornamos lista vazia para erro controlado final.
            self.logger.warning("Falha ao buscar candidatos para alias=%s: %s", product.alias, error)
            return []

        limited_results = all_results[: self.max_search_candidates]
        self.logger.info(
            "Busca retornou %s candidatos (limitado para %s) para alias=%s",
            len(all_results),
            len(limited_results),
            product.alias,
        )
        return limited_results

    def _resolve_using_search_results(
        self,
        expected_product: ProductRecord,
        search_results: list[SearchResult],
    ) -> Optional[ResolveResult]:
        """
        Responsabilidade:
            Testar candidatos da busca e escolher melhor resultado validado.

        Parâmetros:
            expected_product: Produto de referência para matching.
            search_results: Candidatos retornados pelo SearchProvider.

        Retorno:
            ResolveResult vencedor quando houver candidato confiável, senão None.

        Contexto de uso:
            Núcleo do fallback para atualização de URL e SKU por redescoberta.
        """

        best_result: Optional[ResolveResult] = None
        best_score = -1.0

        for search_result in search_results:
            candidate_result = self._try_resolve_with_url(
                expected_product=expected_product,
                candidate_url=search_result.url,
                source_label=search_result.source,
                use_custom_threshold=True,
            )

            if not candidate_result.success:
                self.logger.info(
                    "Candidato rejeitado alias=%s url=%s motivo=%s",
                    expected_product.alias,
                    search_result.url,
                    candidate_result.error_code,
                )
                continue

            current_score = candidate_result.match_result.score if candidate_result.match_result else 0.0
            if current_score > best_score:
                best_score = current_score
                best_result = candidate_result

        return best_result

    def _try_resolve_with_url(
        self,
        expected_product: ProductRecord,
        candidate_url: str,
        source_label: str,
        use_custom_threshold: bool,
    ) -> ResolveResult:
        """
        Responsabilidade:
            Avaliar URL candidata com fetch, parsing, matching e atualização.

        Parâmetros:
            expected_product: Produto esperado usado no matcher.
            candidate_url: URL candidata que será validada.
            source_label: Rótulo de origem para logs de auditoria.
            use_custom_threshold: Define se usa limiar de fallback de busca.

        Retorno:
            ResolveResult de sucesso/falha para a URL testada.

        Contexto de uso:
            Reutilizada tanto no fluxo da last_known_url quanto da busca.
        """

        try:
            fetch_result = self.fetcher.fetch_page(candidate_url)
        except Exception as error:
            return ResolveResult(
                success=False,
                message=f"Falha ao baixar URL candidata ({source_label}): {error}",
                product=None,
                page_data=None,
                match_result=None,
                error_code="FETCH_FAILED",
            )

        page_data = parse_page_data(
            page_url=fetch_result.final_url,
            html_content=fetch_result.html_content,
            configured_fallback_sku=None,
        )

        threshold = self.search_match_threshold if use_custom_threshold else None
        if threshold is None:
            match_result = match_product_with_page(
                expected_product=expected_product,
                observed_page_data=page_data,
            )
        else:
            # Regra de negócio:
            # No fallback de busca exigimos score mais alto para evitar aceitar
            # URLs erradas retornadas por mecanismo de busca aberto.
            match_result = match_product_with_page(
                expected_product=expected_product,
                observed_page_data=page_data,
                match_threshold=threshold,
            )

        if not match_result.matched:
            return ResolveResult(
                success=False,
                message="URL candidata não corresponde ao produto esperado",
                product=None,
                page_data=page_data,
                match_result=match_result,
                error_code="PRODUCT_MISMATCH",
            )

        if not page_data.sku:
            return ResolveResult(
                success=False,
                message="SKU ausente na URL candidata validada",
                product=None,
                page_data=page_data,
                match_result=match_result,
                error_code="SKU_NOT_FOUND",
            )

        updated_product = self.product_store.update_product_sku_and_url(
            product_alias=expected_product.alias,
            new_sku=page_data.sku,
            new_url=page_data.url,
        )

        self.logger.info(
            "Produto alias=%s atualizado por %s com score=%.2f",
            expected_product.alias,
            source_label,
            match_result.score,
        )

        return ResolveResult(
            success=True,
            message="SKU atualizado com sucesso após validação de identidade",
            product=updated_product,
            page_data=page_data,
            match_result=match_result,
            error_code=None,
        )
