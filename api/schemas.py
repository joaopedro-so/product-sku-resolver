"""
Schemas Pydantic da camada de API REST.

Este módulo define contratos de entrada e saída para manter validação
consistente e documentação automática dos endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    """
    Responsabilidade:
        Representar payload de criação/atualização de produto na API.

    Parâmetros:
        alias: Identificador único do produto no sistema.
        brand: Marca estável usada no matching.
        name: Nome estável usado no matching.
        variant: Variante estável (ex.: 200ml).
        last_known_url: URL inicial conhecida para tentativa de resolução.
        last_known_sku: SKU inicial conhecido no cadastro.

    Retorno:
        Modelo validado com dados necessários para persistência.

    Contexto de uso:
        Recebido no endpoint POST /products.
    """

    alias: str = Field(..., min_length=1)
    brand: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    variant: str = Field(..., min_length=1)
    last_known_url: str = Field(..., min_length=1)
    last_known_sku: str = Field(..., min_length=1)


class ProductResponse(BaseModel):
    """
    Responsabilidade:
        Representar resposta padronizada de produto na API.

    Parâmetros:
        alias: Identificador único do produto.
        brand: Marca persistida.
        name: Nome persistido.
        variant: Variante persistida.
        last_known_url: URL conhecida mais recente.
        last_known_sku: SKU conhecido mais recente.

    Retorno:
        Estrutura serializável para listagem e consulta de produto.

    Contexto de uso:
        Usada nos endpoints GET /products, GET /products/{alias} e POST /products.
    """

    alias: str
    brand: str
    name: str
    variant: str
    last_known_url: str
    last_known_sku: str


class UpdateResult(BaseModel):
    """
    Responsabilidade:
        Representar status de atualização individual de SKU.

    Parâmetros:
        alias: Produto alvo da tentativa de atualização.
        success: Indica se atualização foi concluída com validade.
        message: Mensagem descritiva da tentativa.
        error_code: Código semântico para falhas controladas.
        updated_sku: SKU resultante quando sucesso.
        updated_url: URL resultante quando sucesso.

    Retorno:
        Modelo de retorno para endpoints de update individual e em lote.

    Contexto de uso:
        Padroniza resposta operacional da camada resolver na API.
    """

    alias: str
    success: bool
    message: str
    error_code: str | None = None
    updated_sku: str | None = None
    updated_url: str | None = None


class SkuEventResponse(BaseModel):
    """
    Responsabilidade:
        Representar evento histórico retornado pela API.

    Parâmetros:
        timestamp: Data/hora UTC do evento.
        alias: Produto relacionado ao evento.
        event_type: Tipo semântico de evento monitorado.
        old_sku: SKU anterior quando disponível.
        new_sku: SKU novo quando disponível.
        old_url: URL anterior quando disponível.
        new_url: URL nova quando disponível.
        match_score: Score do matcher quando aplicável.

    Retorno:
        Modelo serializável para endpoints de histórico.

    Contexto de uso:
        Usado nos endpoints GET /history e GET /history/{alias}.
    """

    timestamp: str
    alias: str
    event_type: str
    old_sku: str | None
    new_sku: str | None
    old_url: str | None
    new_url: str | None
    match_score: float | None


class MonitorRunResponse(BaseModel):
    """
    Responsabilidade:
        Representar resumo da execução manual do monitoramento.

    Parâmetros:
        processed_count: Quantidade de produtos processados.
        success_count: Quantidade de itens atualizados sem erro.
        error_count: Quantidade de itens com falha.
        emitted_events: Quantidade de eventos gravados no ciclo.

    Retorno:
        Modelo de resposta do endpoint POST /monitor/run.

    Contexto de uso:
        Permite observabilidade imediata da execução sob demanda.
    """

    processed_count: int
    success_count: int
    error_count: int
    emitted_events: int
