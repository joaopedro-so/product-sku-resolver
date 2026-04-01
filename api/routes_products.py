"""
Rotas de produtos, histórico e monitoramento da API REST.

Este módulo conecta operações HTTP aos serviços de domínio sem duplicar regras
já implementadas nas camadas backend/services e monitoring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from api.schemas import (
    MonitorRunResponse,
    ProductCreate,
    ProductResponse,
    SkuEventResponse,
    UpdateResult,
)
from backend.models.product import ProductRecord
from backend.models.sku_event import SkuEvent
from backend.services.runtime_context import RuntimeServices

router = APIRouter(tags=["products"])


def _get_services(request: Request) -> RuntimeServices:
    """
    Responsabilidade:
        Recuperar container de serviços compartilhados da aplicação FastAPI.

    Parâmetros:
        request: Objeto de requisição com referência ao estado da aplicação.

    Retorno:
        RuntimeServices com dependências necessárias às rotas.

    Contexto de uso:
        Função interna para evitar repetição de acesso ao app.state.
    """

    services: RuntimeServices | None = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Serviços da aplicação não foram inicializados",
        )
    return services


def _to_product_response(product_record: ProductRecord) -> ProductResponse:
    """
    Responsabilidade:
        Converter ProductRecord de domínio para schema de resposta da API.

    Parâmetros:
        product_record: Entidade de domínio retornada pelo ProductStoreService.

    Retorno:
        ProductResponse pronto para serialização JSON.

    Contexto de uso:
        Utilizado em endpoints de listagem e consulta de produtos.
    """

    return ProductResponse(**product_record.to_dict())


def _to_event_response(event: SkuEvent) -> SkuEventResponse:
    """
    Responsabilidade:
        Converter evento de domínio para schema HTTP de histórico.

    Parâmetros:
        event: Evento de auditoria lido do HistoryStore.

    Retorno:
        SkuEventResponse serializável para retorno em endpoints.

    Contexto de uso:
        Reaproveitado por GET /history e GET /history/{alias}.
    """

    return SkuEventResponse(**event.to_dict())


def _to_update_result(alias: str, resolver_result: Any) -> UpdateResult:
    """
    Responsabilidade:
        Traduzir resultado do resolver para contrato HTTP padronizado.

    Parâmetros:
        alias: Alias do produto processado.
        resolver_result: Objeto retornado por ProductResolver.

    Retorno:
        UpdateResult com informações úteis para operação e diagnóstico.

    Contexto de uso:
        Compartilhado por update individual e update-all.
    """

    updated_sku = resolver_result.product.last_known_sku if resolver_result.product else None
    updated_url = resolver_result.product.last_known_url if resolver_result.product else None

    return UpdateResult(
        alias=alias,
        success=resolver_result.success,
        message=resolver_result.message,
        error_code=resolver_result.error_code,
        updated_sku=updated_sku,
        updated_url=updated_url,
    )


@router.get("/health")
def healthcheck() -> dict[str, str]:
    """
    Responsabilidade:
        Expor endpoint simples de saúde para monitoramento externo.

    Parâmetros:
        Nenhum.

    Retorno:
        Dicionário com status textual da aplicação.

    Contexto de uso:
        Usado por probes de infraestrutura e validação rápida de disponibilidade.
    """

    return {"status": "ok"}


@router.get("/products", response_model=list[ProductResponse])
def list_products(request: Request) -> list[ProductResponse]:
    """
    Responsabilidade:
        Listar todos os produtos cadastrados no storage.

    Parâmetros:
        request: Requisição atual para acesso ao container de serviços.

    Retorno:
        Lista de ProductResponse representando o catálogo persistido.

    Contexto de uso:
        Endpoint operacional para inspeção e conferência de dados.
    """

    services = _get_services(request)
    products = services.product_store.list_products()
    return [_to_product_response(product) for product in products]


@router.get("/products/{alias}", response_model=ProductResponse)
def get_product(alias: str, request: Request) -> ProductResponse:
    """
    Responsabilidade:
        Buscar produto específico pelo alias informado na rota.

    Parâmetros:
        alias: Identificador canônico do produto.
        request: Requisição atual para acesso ao container de serviços.

    Retorno:
        ProductResponse do item encontrado.

    Contexto de uso:
        Endpoint de consulta individual para operação diária.
    """

    services = _get_services(request)
    product = services.product_store.get_by_alias(alias)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto não encontrado")

    return _to_product_response(product)


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, request: Request) -> ProductResponse:
    """
    Responsabilidade:
        Criar ou atualizar produto com base no alias informado.

    Parâmetros:
        payload: Dados validados de criação vindos do cliente.
        request: Requisição atual para acesso ao container de serviços.

    Retorno:
        ProductResponse persistido após upsert no storage.

    Contexto de uso:
        Endpoint de cadastro inicial e manutenção de catálogo.
    """

    services = _get_services(request)
    normalized_product = ProductRecord(
        alias=payload.alias.strip(),
        brand=payload.brand.strip(),
        name=payload.name.strip(),
        variant=payload.variant.strip(),
        last_known_url=payload.last_known_url.strip(),
        last_known_sku=payload.last_known_sku.strip(),
    )

    saved_product = services.product_store.upsert_product(normalized_product)
    return _to_product_response(saved_product)


@router.post("/products/{alias}/update", response_model=UpdateResult)
def update_product(alias: str, request: Request) -> UpdateResult:
    """
    Responsabilidade:
        Executar atualização de SKU para um produto específico.

    Parâmetros:
        alias: Produto alvo da atualização.
        request: Requisição atual para acesso ao container de serviços.

    Retorno:
        UpdateResult descrevendo sucesso/falha da execução.

    Contexto de uso:
        Endpoint principal para operação manual de atualização individual.
    """

    services = _get_services(request)
    resolver_result = services.resolver.resolve_sku_for_alias(alias)
    return _to_update_result(alias, resolver_result)


@router.post("/products/update-all", response_model=list[UpdateResult])
def update_all_products(request: Request) -> list[UpdateResult]:
    """
    Responsabilidade:
        Executar atualização de SKU para todos os produtos cadastrados.

    Parâmetros:
        request: Requisição atual para acesso ao container de serviços.

    Retorno:
        Lista de UpdateResult com resultado por alias processado.

    Contexto de uso:
        Endpoint de operação em lote para manutenção periódica do catálogo.
    """

    services = _get_services(request)
    all_products = services.product_store.list_products()

    update_results: list[UpdateResult] = []
    for product in all_products:
        if not product.is_syncable:
            # Decisao tecnica:
            # A API em lote precisa seguir a mesma regra operacional do monitor:
            # itens manuais/legacy nao devem aparecer como falha de sync quando
            # nao dependem mais do site para manter o codigo atual.
            continue

        resolver_result = services.resolver.resolve_sku_for_alias(product.alias)
        update_results.append(_to_update_result(product.alias, resolver_result))

    return update_results


@router.get("/history", response_model=list[SkuEventResponse])
def list_history(request: Request) -> list[SkuEventResponse]:
    """
    Responsabilidade:
        Listar todos os eventos de histórico registrados no monitoramento.

    Parâmetros:
        request: Requisição atual para acesso aos serviços do runtime.

    Retorno:
        Lista de eventos convertidos para schema HTTP.

    Contexto de uso:
        Endpoint para auditoria geral de alterações e falhas.
    """

    services = _get_services(request)
    events = services.history_store.list_events()
    return [_to_event_response(event) for event in events]


@router.get("/history/{alias}", response_model=list[SkuEventResponse])
def list_history_by_alias(alias: str, request: Request) -> list[SkuEventResponse]:
    """
    Responsabilidade:
        Listar eventos de histórico filtrados por alias do produto.

    Parâmetros:
        alias: Alias do produto que será usado como filtro.
        request: Requisição atual para acesso aos serviços do runtime.

    Retorno:
        Lista de eventos do alias informado.

    Contexto de uso:
        Endpoint para investigação pontual de produto específico.
    """

    services = _get_services(request)
    events = services.history_store.list_events_by_alias(alias)
    return [_to_event_response(event) for event in events]


@router.post("/monitor/run", response_model=MonitorRunResponse)
def run_monitor(request: Request) -> MonitorRunResponse:
    """
    Responsabilidade:
        Executar monitoramento manual sob demanda e retornar resumo.

    Parâmetros:
        request: Requisição atual para acesso aos serviços do runtime.

    Retorno:
        MonitorRunResponse com métricas de execução e eventos emitidos.

    Contexto de uso:
        Endpoint operacional para disparo manual de ciclo de monitoramento.
    """

    services = _get_services(request)
    summary = services.monitor_service.run()
    return MonitorRunResponse(
        processed_count=summary.processed_count,
        success_count=summary.success_count,
        error_count=summary.error_count,
        emitted_events=len(summary.emitted_events),
    )
