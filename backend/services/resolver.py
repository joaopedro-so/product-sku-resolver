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
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from backend.models.product import ProductRecord
from backend.models.search_result import SearchResult
from backend.search.base_provider import SearchProvider
from backend.services.matcher import MatchResult, match_product_with_page, normalize_variant
from backend.services.product_store_service import ProductStoreService
from backend.utils.fetcher import Fetcher
from backend.utils.parser import PageData, PageVariantOption, parse_page_data

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


@dataclass(slots=True)
class _ResolvedPageCandidate:
    """
    Responsabilidade:
        Transportar uma candidata de página já adaptada para a variante correta.

    Parâmetros:
        page_data: Dados da página no formato que será validado pelo matcher.
        variant_option: Variante concreta escolhida dentro do HTML, quando houver.
        match_result: Resultado do matcher para essa leitura específica.

    Retorno:
        Estrutura interna usada apenas pelo resolver.

    Contexto de uso:
        Permite que o resolver trate a página pai e a variante individual como
        candidatas equivalentes, sem duplicar lógica de matching e persistência.
    """

    page_data: PageData
    variant_option: Optional[PageVariantOption]
    match_result: MatchResult


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
        resolved_candidate = self._resolve_best_page_candidate(
            expected_product=expected_product,
            page_data=page_data,
            match_threshold=threshold,
        )
        if resolved_candidate is None:
            if self._page_matches_expected_family(expected_product=expected_product, page_data=page_data):
                return ResolveResult(
                    success=False,
                    message="A página corresponde ao produto pai, mas a variante esperada não foi encontrada",
                    product=None,
                    page_data=page_data,
                    match_result=None,
                    error_code="VARIANT_NOT_FOUND_ON_PAGE",
                )
            return ResolveResult(
                success=False,
                message="URL candidata não corresponde ao produto esperado",
                product=None,
                page_data=page_data,
                match_result=None,
                error_code="PRODUCT_MISMATCH",
            )

        resolved_page_data = resolved_candidate.page_data
        if not resolved_page_data.sku:
            return ResolveResult(
                success=False,
                message="SKU ausente na URL candidata validada",
                product=None,
                page_data=resolved_page_data,
                match_result=None,
                error_code="SKU_NOT_FOUND",
            )

        updated_product = self.product_store.update_product_sku_and_url(
            product_alias=expected_product.alias,
            new_sku=resolved_page_data.sku,
            new_url=resolved_page_data.url,
            site_variant_id=resolved_candidate.variant_option.site_variant_id if resolved_candidate.variant_option else "",
        )

        self.logger.info(
            "Produto alias=%s atualizado por %s com score=%.2f",
            expected_product.alias,
            source_label,
            resolved_candidate.match_result.score,
        )

        return ResolveResult(
            success=True,
            message="SKU atualizado com sucesso após validação de identidade",
            product=updated_product,
            page_data=resolved_page_data,
            match_result=resolved_candidate.match_result,
            error_code=None,
        )

    def _resolve_best_page_candidate(
        self,
        expected_product: ProductRecord,
        page_data: PageData,
        match_threshold: Optional[float],
    ) -> Optional[_ResolvedPageCandidate]:
        """
        Responsabilidade:
            Escolher a melhor leitura da página para a variante esperada.

        Parâmetros:
            expected_product: Variante persistida que está sendo sincronizada.
            page_data: Resultado bruto do parser para a página acessada.
            match_threshold: Limiar opcional usado em fallback de busca.

        Retorno:
            Candidata resolvida quando alguma leitura da página casar com a
            variante esperada; caso contrário, None.

        Contexto de uso:
            Algumas páginas da Renner carregam um produto pai com vários volumes
            e apenas uma variante ativa no HTML principal. Esse método testa a
            variante ativa e, quando necessário, sintetiza leituras para as
            demais variantes publicadas na mesma página.
        """

        best_candidate: Optional[_ResolvedPageCandidate] = None
        best_score = -1.0

        for candidate in self._build_candidate_page_data_variants(expected_product, page_data):
            match_result = self._match_page_with_threshold(
                expected_product=expected_product,
                observed_page_data=candidate.page_data,
                match_threshold=match_threshold,
            )
            if not match_result.matched:
                continue

            if match_result.score > best_score:
                best_score = match_result.score
                best_candidate = _ResolvedPageCandidate(
                    page_data=candidate.page_data,
                    variant_option=candidate.variant_option,
                    match_result=match_result,
                )

        return best_candidate

    def _build_candidate_page_data_variants(
        self,
        expected_product: ProductRecord,
        page_data: PageData,
    ) -> list[_ResolvedPageCandidate]:
        """
        Responsabilidade:
            Montar leituras candidatas da página para a variante esperada.

        Parâmetros:
            expected_product: Variante do catálogo que está sendo sincronizada.
            page_data: Leitura bruta da página retornada pelo parser.

        Retorno:
            Lista de candidatas que inclui a variante ativa e, quando existir,
            a variante específica encontrada dentro do HTML.

        Contexto de uso:
            Permite reaproveitar a mesma página pai para resolver 30ml, 50ml e
            80ml independentemente, sem depender da variante padrão da URL.
        """

        normalized_expected_variant = normalize_variant(expected_product.variant)
        normalized_current_variant = normalize_variant(page_data.variant)
        matching_option = self._find_matching_variant_option(expected_product, page_data)

        candidates: list[_ResolvedPageCandidate] = []
        if (
            not normalized_expected_variant
            or not page_data.available_variants
            or normalized_current_variant == normalized_expected_variant
        ):
            candidates.append(
                _ResolvedPageCandidate(
                    page_data=page_data,
                    variant_option=None,
                    match_result=MatchResult(
                        matched=False,
                        score=0.0,
                        reasons=[],
                        conflicts=[],
                        brand_matched=False,
                        name_matched=False,
                        variant_matched=False,
                    ),
                )
            )

        if matching_option is None:
            return candidates

        if (
            page_data.sku == matching_option.sku
            and normalized_current_variant
            and normalized_current_variant == normalized_expected_variant
        ):
            return candidates

        candidates.append(
            _ResolvedPageCandidate(
                page_data=PageData(
                    url=_build_variant_specific_url(page_data.url, matching_option.sku),
                    title=page_data.title,
                    brand=page_data.brand,
                    name=page_data.name,
                    variant=matching_option.label,
                    sku=matching_option.sku,
                    image_url=page_data.image_url,
                    description=page_data.description,
                    available_variants=page_data.available_variants,
                ),
                variant_option=matching_option,
                match_result=MatchResult(
                    matched=False,
                    score=0.0,
                    reasons=[],
                    conflicts=[],
                    brand_matched=False,
                    name_matched=False,
                    variant_matched=False,
                ),
            )
        )
        return candidates

    def _find_matching_variant_option(
        self,
        expected_product: ProductRecord,
        page_data: PageData,
    ) -> Optional[PageVariantOption]:
        """
        Responsabilidade:
            Localizar dentro da página a opção de variante que corresponde ao alias.

        Parâmetros:
            expected_product: Variante persistida que define o volume esperado.
            page_data: Leitura completa da página com as opções disponíveis.

        Retorno:
            PageVariantOption correspondente quando encontrada; senão None.

        Contexto de uso:
            É o ponto central do sync por variante em produtos agrupados como
            Fame In Love, onde cada ml possui SKU próprio na mesma página.
        """

        normalized_expected_variant = normalize_variant(expected_product.variant)
        if not normalized_expected_variant:
            return None

        for variant_option in page_data.available_variants:
            if normalize_variant(variant_option.label) == normalized_expected_variant:
                return variant_option

        return None

    def _page_matches_expected_family(
        self,
        expected_product: ProductRecord,
        page_data: PageData,
    ) -> bool:
        """
        Responsabilidade:
            Verificar se a página corresponde ao produto pai, ignorando o volume.

        Parâmetros:
            expected_product: Variante persistida que está sendo sincronizada.
            page_data: Leitura bruta da página atualmente acessada.

        Retorno:
            True quando marca e identidade do perfume pai casarem; False caso contrário.

        Contexto de uso:
            Diferencia uma página totalmente errada de uma página correta do
            perfume pai que apenas não expõe a variante esperada.
        """

        expected_parent_product = ProductRecord(
            alias=expected_product.alias,
            brand=expected_product.brand,
            name=expected_product.display_name,
            variant="",
            last_known_url=expected_product.last_known_url,
            last_known_sku=expected_product.last_known_sku,
            match_name=expected_product.match_name,
            line_name=expected_product.line_name,
            normalized_match_name=expected_product.normalized_match_name,
            page_family_sku=expected_product.page_family_sku,
            parent_reference=expected_product.parent_reference,
            source_type=expected_product.source_type,
            concentration=expected_product.concentration,
            shelf_reference_label=expected_product.shelf_reference_label,
            notes=expected_product.notes,
            image_url=expected_product.image_url,
            stock_qty=expected_product.stock_qty,
            variant_notes=expected_product.variant_notes,
            is_active=expected_product.is_active,
            shelf_number=expected_product.shelf_number,
            display_order=expected_product.display_order,
            site_link_status=expected_product.site_link_status,
            site_product_id=expected_product.site_product_id,
            site_candidate_id=expected_product.site_candidate_id,
            site_candidate_url=expected_product.site_candidate_url,
            site_candidate_code=expected_product.site_candidate_code,
            site_candidate_variant_id=expected_product.site_candidate_variant_id,
            match_confidence=expected_product.match_confidence,
            match_signals=expected_product.match_signals,
            last_matched_at=expected_product.last_matched_at,
            site_variant_id=expected_product.site_variant_id,
            current_site_code=expected_product.current_site_code,
            current_barcode_value=expected_product.current_barcode_value,
        )
        parent_match_result = match_product_with_page(
            expected_product=expected_parent_product,
            observed_page_data=page_data,
        )
        return parent_match_result.brand_matched and parent_match_result.name_matched

    def _match_page_with_threshold(
        self,
        expected_product: ProductRecord,
        observed_page_data: PageData,
        match_threshold: Optional[float],
    ) -> MatchResult:
        """
        Responsabilidade:
            Executar o matcher respeitando o limiar adequado ao contexto.

        Parâmetros:
            expected_product: Variante persistida que será comparada.
            observed_page_data: Leitura concreta da página ou da variante sintética.
            match_threshold: Limiar opcional usado em fallback de busca.

        Retorno:
            MatchResult completo com score e conflitos.

        Contexto de uso:
            Centraliza a escolha do threshold para que a validação da variante
            ativa e da variante sintética usem exatamente a mesma regra.
        """

        if match_threshold is None:
            return match_product_with_page(
                expected_product=expected_product,
                observed_page_data=observed_page_data,
            )

        return match_product_with_page(
            expected_product=expected_product,
            observed_page_data=observed_page_data,
            match_threshold=match_threshold,
        )


def _build_variant_specific_url(page_url: str, variant_sku: str) -> str:
    """
    Responsabilidade:
        Garantir que a URL final aponte explicitamente para a variante resolvida.

    Parâmetros:
        page_url: URL da página pai ou da variante atualmente acessada.
        variant_sku: SKU da variante escolhida dentro do HTML.

    Retorno:
        URL com query `sku` estável para reabrir a mesma variante no futuro.

    Contexto de uso:
        Evita que futuros syncs caiam novamente na variante padrão da página
        quando o produto pai expõe vários volumes no mesmo HTML.
    """

    normalized_variant_sku = str(variant_sku).strip()
    if not normalized_variant_sku:
        return page_url

    parsed_url = urlparse(page_url)
    current_query_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    current_query_params["sku"] = normalized_variant_sku
    rebuilt_query = urlencode(current_query_params)
    return urlunparse(parsed_url._replace(query=rebuilt_query))
