"""
Primeira versão da camada de resolução de SKU baseada em last_known_url.

Nesta etapa, o fluxo é deliberadamente simples:
- busca produto por alias
- baixa página da última URL conhecida
- parseia PageData
- valida identidade via matcher
- atualiza SKU/URL somente quando o match for confiável
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.models.product import ProductRecord
from backend.services.matcher import MatchResult, match_product_with_page
from backend.services.product_store_service import ProductStoreService
from backend.utils.fetcher import Fetcher
from backend.utils.parser import PageData, parse_page_data


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
        Orquestrar resolução de SKU usando apenas a last_known_url nesta fase.

    Parâmetros:
        product_store: Serviço de armazenamento de produtos.
        fetcher: Cliente HTTP reutilizável para download das páginas.

    Retorno:
        Instância de resolver pronta para execução por alias.

    Contexto de uso:
        Camada de serviço chamada pela API para atualização individual de SKU.
    """

    def __init__(self, product_store: ProductStoreService, fetcher: Fetcher) -> None:
        """
        Responsabilidade:
            Inicializar dependências do fluxo de resolução.

        Parâmetros:
            product_store: Abstração de leitura/escrita de produtos.
            fetcher: Abstração de requisição HTTP para páginas remotas.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construído no bootstrap da aplicação com injeção de dependências.
        """

        self.product_store = product_store
        self.fetcher = fetcher

    def resolve_sku_for_alias(self, product_alias: str) -> ResolveResult:
        """
        Responsabilidade:
            Executar fluxo completo de resolução para um alias específico.

        Parâmetros:
            product_alias: Alias do produto que deve ter SKU validado/atualizado.

        Retorno:
            ResolveResult contendo sucesso/falha e detalhes de rastreabilidade.

        Contexto de uso:
            Método principal da primeira versão do resolver (sem busca de nova URL).
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

        try:
            fetch_result = self.fetcher.fetch_page(expected_product.last_known_url)
        except Exception as error:
            # Tratamento de erro:
            # Encapsulamos qualquer falha de fetch em erro controlado para não
            # vazar detalhes de infraestrutura para a camada de API.
            return ResolveResult(
                success=False,
                message=f"Falha ao baixar página do produto: {error}",
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

        match_result = match_product_with_page(
            expected_product=expected_product,
            observed_page_data=page_data,
        )

        if not match_result.matched:
            return ResolveResult(
                success=False,
                message="Página não corresponde ao produto esperado",
                product=None,
                page_data=page_data,
                match_result=match_result,
                error_code="PRODUCT_MISMATCH",
            )

        if not page_data.sku:
            return ResolveResult(
                success=False,
                message="Não foi possível extrair SKU da página validada",
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

        return ResolveResult(
            success=True,
            message="SKU atualizado com sucesso após validação de identidade",
            product=updated_product,
            page_data=page_data,
            match_result=match_result,
            error_code=None,
        )
