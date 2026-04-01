"""
Rotas do dashboard web mobile-first para operacao manual do resolvedor de SKU.

Este modulo reorganiza a experiencia em torno de Home, Search, Updates,
Saved e detalhe operacional, preservando a logica existente de produtos,
barcode, update de SKU e preview visual.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.models.product import ProductRecord
from backend.models.sku_event import SkuEvent
from backend.services.curated_renner_import_service import (
    CuratedRennerImportService,
    resolve_builtin_curated_seed_file,
)
from backend.services.matcher import normalize_text
from backend.services.shelf_banner_service import ShelfBannerService
from backend.services.product_draft_service import ProductDraftService
from backend.services.product_group_service import GroupedParentProduct, ProductGroupService
from backend.services.product_preview_service import ProductPreview, ProductPreviewService
from backend.services.shelf_service import ShelfPlacement, ShelfService
from backend.services.storage_path_service import resolve_default_data_file
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver, ResolveResult
from backend.services.saved_product_service import SavedProductService
from backend.utils.barcode import build_code128_svg_data_uri
from backend.utils.fetcher import FetchResult, Fetcher
from backend.utils.parser import PageData, parse_page_data
from history.history_store import HistoryStore
from monitoring.monitor_service import MonitorRunSummary, MonitorService

router = APIRouter(prefix="/dashboard", tags=["dashboard-web"])
templates = Jinja2Templates(directory="backend/web/templates")
templates.env.globals["build_code128_svg_data_uri"] = build_code128_svg_data_uri

# Decisao tecnica:
# Mantemos feedbacks recentes em memoria para exibir status imediato apos
# interacoes manuais, sem exigir nova persistencia no contrato de dominio.
last_update_by_alias: Dict[str, Dict[str, Any]] = {}


def _get_store_service(request: Request) -> ProductStoreService:
    """
    Responsabilidade:
        Obter a instancia compartilhada de armazenamento de produtos.

    Parametros:
        request: Requisicao HTTP atual com acesso ao `app.state`.

    Retorno:
        ProductStoreService inicializado no bootstrap da aplicacao.

    Contexto de uso:
        Base para listagem, cadastro, edicao e detalhes do dashboard.
    """

    return request.app.state.product_store_service


def _get_resolver_service(request: Request) -> ProductResolver:
    """
    Responsabilidade:
        Obter o resolvedor compartilhado usado pelas acoes operacionais.

    Parametros:
        request: Requisicao HTTP atual com acesso ao `app.state`.

    Retorno:
        ProductResolver pronto para execucao individual ou em lote.

    Contexto de uso:
        Utilizada por update individual, update em lote e preview visual.
    """

    return request.app.state.product_resolver


def _get_fetcher_service(request: Request) -> Optional[Fetcher]:
    """
    Responsabilidade:
        Recuperar o fetcher compartilhado usado para leitura de paginas remotas.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        Fetcher quando disponivel; caso contrario, None.

    Contexto de uso:
        Necessario para preview de imagem e auto-preenchimento por URL.
    """

    resolver_service = _get_resolver_service(request)
    fetcher = getattr(resolver_service, "fetcher", None)
    return fetcher if isinstance(fetcher, Fetcher) else fetcher


def _resolve_history_storage_path() -> Path:
    """
    Responsabilidade:
        Definir o caminho do arquivo de historico usado pelo dashboard.

    Parametros:
        Nenhum.

    Retorno:
        Path do arquivo de historico.

    Contexto de uso:
        Fallback para runtimes que nao inicializam `app.state.services`.
    """

    configured_path = os.getenv("PRODUCT_HISTORY_FILE", "").strip()
    if configured_path:
        return Path(configured_path)
    return resolve_default_data_file("history.json")


def _resolve_saved_storage_path() -> Path:
    """
    Responsabilidade:
        Definir o caminho persistente dos produtos salvos.

    Parametros:
        Nenhum.

    Retorno:
        Path do arquivo de favoritos operacionais.

    Contexto de uso:
        Permite deploy com override por variavel de ambiente.
    """

    configured_path = os.getenv("SAVED_PRODUCTS_FILE", "").strip()
    if configured_path:
        return Path(configured_path)
    return resolve_default_data_file("saved_products.json")


def _resolve_preview_cache_path() -> Path:
    """
    Responsabilidade:
        Definir o caminho do cache de previews visuais do dashboard.

    Parametros:
        Nenhum.

    Retorno:
        Path do arquivo de cache de imagem/titulo.

    Contexto de uso:
        Reduz latencia em listas mobile-first com muitos cards.
    """

    configured_path = os.getenv("PRODUCT_PREVIEW_CACHE_FILE", "").strip()
    if configured_path:
        return Path(configured_path)
    return resolve_default_data_file("product_previews.json")


def _get_history_store(request: Request) -> HistoryStore:
    """
    Responsabilidade:
        Recuperar ou inicializar o store de historico do dashboard.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        HistoryStore compartilhado pela aplicacao web.

    Contexto de uso:
        Necessario para a tela Updates e para status de sincronizacao.
    """

    runtime_services = getattr(request.app.state, "services", None)
    history_store = getattr(runtime_services, "history_store", None)
    if isinstance(history_store, HistoryStore):
        return history_store

    cached_history_store = getattr(request.app.state, "history_store_service", None)
    if isinstance(cached_history_store, HistoryStore):
        return cached_history_store

    initialized_history_store = HistoryStore(_resolve_history_storage_path())
    request.app.state.history_store_service = initialized_history_store
    return initialized_history_store


def _get_monitor_service(request: Request) -> MonitorService:
    """
    Responsabilidade:
        Recuperar ou inicializar o monitor service usado pela tela Updates.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        MonitorService pronto para update em lote com historico.

    Contexto de uso:
        Alimenta o resumo de sincronizacao e a acao "Update all".
    """

    runtime_services = getattr(request.app.state, "services", None)
    monitor_service = getattr(runtime_services, "monitor_service", None)
    if isinstance(monitor_service, MonitorService):
        return monitor_service

    cached_monitor_service = getattr(request.app.state, "monitor_service", None)
    if isinstance(cached_monitor_service, MonitorService):
        return cached_monitor_service

    initialized_monitor_service = MonitorService(
        product_store=_get_store_service(request),
        resolver=_get_resolver_service(request),
        history_store=_get_history_store(request),
    )
    request.app.state.monitor_service = initialized_monitor_service
    return initialized_monitor_service


def _get_saved_service(request: Request) -> SavedProductService:
    """
    Responsabilidade:
        Recuperar ou inicializar o storage de produtos salvos.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        SavedProductService compartilhado pela interface web.

    Contexto de uso:
        Base da aba Saved e do botao de salvar produto.
    """

    cached_saved_service = getattr(request.app.state, "saved_product_service", None)
    if isinstance(cached_saved_service, SavedProductService):
        return cached_saved_service

    initialized_saved_service = SavedProductService(_resolve_saved_storage_path())
    request.app.state.saved_product_service = initialized_saved_service
    return initialized_saved_service


def _get_preview_service(request: Request) -> Optional[ProductPreviewService]:
    """
    Responsabilidade:
        Recuperar ou inicializar o cache de previews visuais.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        ProductPreviewService quando houver fetcher disponivel; senao None.

    Contexto de uso:
        Reutilizado por Home, Search, Saved e detalhe do produto.
    """

    cached_preview_service = getattr(request.app.state, "product_preview_service", None)
    if isinstance(cached_preview_service, ProductPreviewService):
        return cached_preview_service

    fetcher = _get_fetcher_service(request)
    if fetcher is None:
        return None

    initialized_preview_service = ProductPreviewService(
        storage_file_path=_resolve_preview_cache_path(),
        fetcher=fetcher,
    )
    request.app.state.product_preview_service = initialized_preview_service
    return initialized_preview_service


def _get_shelf_service(request: Request) -> ShelfService:
    """
    Responsabilidade:
        Recuperar ou inicializar o servico derivado de organizacao por prateleira.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        ShelfService compartilhado pelo dashboard.

    Contexto de uso:
        Permite abrir o app pela visao fisica sem alterar o storage principal.
    """

    cached_shelf_service = getattr(request.app.state, "shelf_service", None)
    if isinstance(cached_shelf_service, ShelfService):
        return cached_shelf_service

    initialized_shelf_service = ShelfService()
    request.app.state.shelf_service = initialized_shelf_service
    return initialized_shelf_service


def _get_shelf_banner_service(request: Request) -> ShelfBannerService:
    """
    Responsabilidade:
        Recuperar ou inicializar o catálogo visual dos banners de prateleira.

    Parâmetros:
        request: Requisição HTTP atual com acesso ao `app.state`.

    Retorno:
        ShelfBannerService compartilhado pela interface web.

    Contexto de uso:
        Mantém cards e headers de prateleira sincronizados com a mesma fonte
        de verdade para textos, assets e fallbacks visuais.
    """

    cached_service = getattr(request.app.state, "shelf_banner_service", None)
    if isinstance(cached_service, ShelfBannerService):
        return cached_service

    initialized_service = ShelfBannerService(static_directory=Path("backend/web/static"))
    request.app.state.shelf_banner_service = initialized_service
    return initialized_service


def _get_product_group_service(request: Request) -> ProductGroupService:
    """
    Responsabilidade:
        Recuperar ou inicializar o servico de agrupamento por produto pai.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        ProductGroupService compartilhado pelo dashboard.

    Contexto de uso:
        Reorganiza variantes de volume em uma estrutura semantica unica para
        listas e detalhe, sem alterar o formato persistido no storage.
    """

    cached_group_service = getattr(request.app.state, "product_group_service", None)
    if isinstance(cached_group_service, ProductGroupService):
        return cached_group_service

    initialized_group_service = ProductGroupService()
    request.app.state.product_group_service = initialized_group_service
    return initialized_group_service


def _parse_iso_timestamp(raw_timestamp: Optional[str]) -> Optional[datetime]:
    """
    Responsabilidade:
        Converter timestamp ISO8601 em datetime tolerante a formatos comuns.

    Parametros:
        raw_timestamp: Texto vindo de historico ou snapshots em memoria.

    Retorno:
        Datetime timezone-aware quando o parse for bem-sucedido; senao None.

    Contexto de uso:
        Usado para ordenacao, badges de recencia e resumos da tela Updates.
    """

    normalized_timestamp = str(raw_timestamp or "").strip()
    if not normalized_timestamp:
        return None

    try:
        return datetime.fromisoformat(normalized_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_timestamp_label(raw_timestamp: Optional[str]) -> str:
    """
    Responsabilidade:
        Traduzir timestamp bruto em texto curto e amigavel ao uso operacional.

    Parametros:
        raw_timestamp: Texto ISO8601 vindo do historico ou estado em memoria.

    Retorno:
        Rotulo curto para interface, como "Hoje 14:20" ou "Sem sync recente".

    Contexto de uso:
        Reforca leitura rapida de status em listas e detalhe.
    """

    parsed_timestamp = _parse_iso_timestamp(raw_timestamp)
    if parsed_timestamp is None:
        return "Sem sincronização recente"

    localized_timestamp = parsed_timestamp.astimezone()
    now = datetime.now(localized_timestamp.tzinfo)
    if localized_timestamp.date() == now.date():
        return f"Hoje {localized_timestamp:%H:%M}"

    if (now.date() - localized_timestamp.date()).days == 1:
        return f"Ontem {localized_timestamp:%H:%M}"

    return localized_timestamp.strftime("%d/%m %H:%M")


def _humanize_alias(product_alias: str) -> str:
    """
    Responsabilidade:
        Converter alias tecnico em texto mais amigavel para fallback visual.

    Parametros:
        product_alias: Alias interno persistido no storage.

    Retorno:
        Texto simples com separacao humana entre palavras.

    Contexto de uso:
        Evita expor slugs crus quando algum contexto visual nao tem nome melhor.
    """

    normalized_alias = str(product_alias).strip().replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in normalized_alias.split())


def _humanize_event_type(event_type: str) -> str:
    """
    Responsabilidade:
        Traduzir tipos tecnicos de evento para rotulos compreensiveis na UI.

    Parametros:
        event_type: Tipo persistido no historico de SKU.

    Retorno:
        Texto curto e humano para exibicao em telas operacionais.

    Contexto de uso:
        Remove jargao tecnico de secoes visuais como historico curto.
    """

    mapping = {
        "sku_changed": "SKU alterado",
        "url_changed": "URL alterada",
        "error": "Falha",
    }
    return mapping.get(str(event_type).strip(), _humanize_alias(event_type))


def _is_today(raw_timestamp: Optional[str]) -> bool:
    """
    Responsabilidade:
        Indicar se um timestamp ocorreu no dia corrente local.

    Parametros:
        raw_timestamp: Texto ISO8601 a ser avaliado.

    Retorno:
        True quando o evento ocorreu hoje; False nos demais casos.

    Contexto de uso:
        Utilizado em filtros rapidos e contadores da Home/Updates.
    """

    parsed_timestamp = _parse_iso_timestamp(raw_timestamp)
    if parsed_timestamp is None:
        return False

    localized_timestamp = parsed_timestamp.astimezone()
    return localized_timestamp.date() == datetime.now(localized_timestamp.tzinfo).date()


def _build_update_snapshot(resolve_result: ResolveResult) -> Dict[str, Any]:
    """
    Responsabilidade:
        Converter resultado de resolucao em estrutura serializavel para a UI.

    Parametros:
        resolve_result: Resultado retornado por `resolve_sku_for_alias`.

    Retorno:
        Dicionario com status, mensagem, timestamp e dados auxiliares.

    Contexto de uso:
        Mantem feedback manual imediato entre navegacoes do dashboard.
    """

    return {
        "success": resolve_result.success,
        "message": resolve_result.message,
        "error_code": resolve_result.error_code,
        "page_data": asdict(resolve_result.page_data) if resolve_result.page_data else None,
        "match_result": asdict(resolve_result.match_result) if resolve_result.match_result else None,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_product_visual_snapshot(request: Request, product: ProductRecord) -> Optional[PageData]:
    """
    Responsabilidade:
        Buscar sinais visuais completos da pagina do produto para a tela de detalhe.

    Parametros:
        request: Requisicao atual para obter fetcher compartilhado.
        product: Produto persistido que tera a URL atual consultada.

    Retorno:
        PageData com imagem, titulo, sku e sinais extras; ou None em falha.

    Contexto de uso:
        Alimenta a confirmacao visual do detalhe e do fullscreen barcode.
    """

    fetcher = _get_fetcher_service(request)
    if fetcher is None or not product.last_known_url.strip():
        return None

    try:
        fetch_result: FetchResult = fetcher.fetch_page(product.last_known_url)
    except Exception:
        return None

    return parse_page_data(
        page_url=fetch_result.final_url,
        html_content=fetch_result.html_content,
        configured_fallback_sku=product.last_known_sku,
    )


def _with_app_shell(
    request: Request,
    context: Dict[str, Any],
    active_tab: str = "home",
    hide_app_chrome: bool = False,
    body_class: str = "",
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Enriquecer contexto dos templates com dados globais da shell mobile-first.

    Parametros:
        request: Requisicao atual para acessar servicos globais.
        context: Contexto especifico da tela.
        active_tab: Identificador da navegacao principal ativa.
        hide_app_chrome: Define se header/bottom nav devem ser ocultados.
        body_class: Classe opcional para ajustes pontuais de layout.

    Retorno:
        Dicionario pronto para renderizacao do template base.

    Contexto de uso:
        Garante navegacao consistente entre Home, Search, Updates e Saved.
    """

    saved_count = len(_get_saved_service(request).list_saved_aliases())
    return {
        **context,
        "active_tab": active_tab,
        "hide_app_chrome": hide_app_chrome,
        "body_class": body_class,
        "saved_count": saved_count,
    }


def _build_new_product_form_context(
    submitted_data: Optional[Dict[str, str]] = None,
    error_message: Optional[str] = None,
    autofill_message: Optional[str] = None,
    autofill_error_message: Optional[str] = None,
    autofill_preview: Optional[Dict[str, Any]] = None,
    form_mode: str = "create",
    form_action_url: str = "/dashboard/products",
    submit_button_label: str = "Salvar produto",
    cancel_url: str = "/dashboard",
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Padronizar contexto da tela de formulario de produto.

    Parametros:
        submitted_data: Valores atuais do formulario para re-renderizacao.
        error_message: Mensagem de erro de validacao final.
        autofill_message: Feedback de sucesso do auto-preenchimento.
        autofill_error_message: Feedback de falha do auto-preenchimento.
        autofill_preview: Dados auxiliares extraidos da pagina.
        form_mode: Modo do formulario (`create` ou `edit`).
        form_action_url: Endpoint que recebera o submit principal.
        submit_button_label: Texto do botao principal.
        cancel_url: Destino do CTA secundario de cancelamento.

    Retorno:
        Dicionario compativel com `add_product.html`.

    Contexto de uso:
        Reutilizado pelos fluxos de criacao, auto-preenchimento e edicao.
    """

    return {
        "error_message": error_message,
        "submitted_data": submitted_data or {},
        "autofill_message": autofill_message,
        "autofill_error_message": autofill_error_message,
        "autofill_preview": autofill_preview,
        "form_mode": form_mode,
        "form_action_url": form_action_url,
        "submit_button_label": submit_button_label,
        "cancel_url": cancel_url,
    }


def _build_shelf_options(request: Request) -> List[Dict[str, Any]]:
    """
    Responsabilidade:
        Montar a lista de opcoes de prateleira para formularios de produto.

    Parametros:
        request: Requisicao atual para acessar o ShelfService.

    Retorno:
        Lista de opcoes com numero e titulo de cada prateleira.

    Contexto de uso:
        Reutilizada no cadastro e na edicao para atribuicao manual.
    """

    return [
        {
            "value": shelf.shelf_number,
            "label": f"Prateleira {shelf.shelf_number:02d} — {shelf.shelf_title}",
        }
        for shelf in _get_shelf_service(request).list_shelves()
    ]


def _normalize_optional_numeric_text(raw_value: Any) -> str:
    """
    Responsabilidade:
        Padronizar texto numerico opcional vindo de formulario HTML.

    Parametros:
        raw_value: Valor bruto do formulario.

    Retorno:
        String limpa ou vazia quando nao houver conteudo.

    Contexto de uso:
        Mantem o estado do formulario consistente antes da conversao final.
    """

    normalized_value = str(raw_value or "").strip()
    return normalized_value


def _build_submitted_data_from_product(product: ProductRecord) -> Dict[str, str]:
    """
    Responsabilidade:
        Converter ProductRecord em payload pronto para preencher o formulario.

    Parametros:
        product: Produto persistido que sera exibido para edicao.

    Retorno:
        Dicionario com os campos esperados pelo template de formulario.

    Contexto de uso:
        Evita duplicacao na abertura da tela de editar produto.
    """

    return {
        "alias": product.alias,
        "brand": product.brand,
        "name": product.name,
        "variant": product.variant,
        "last_known_url": product.last_known_url,
        "last_known_sku": product.last_known_sku,
        "shelf_number": str(product.shelf_number or ""),
        "display_order": str(product.display_order or ""),
    }


def _extract_product_form_submission(form_data: Any) -> Dict[str, str]:
    """
    Responsabilidade:
        Extrair e normalizar os campos relevantes do formulario de produto.

    Parametros:
        form_data: Estrutura retornada por `await request.form()`.

    Retorno:
        Dicionario com strings limpas e defaults operacionais previsiveis.

    Contexto de uso:
        Centraliza o parsing do formulario para que criacao e edicao usem o
        mesmo contrato antes de validar ou persistir qualquer dado.
    """

    submitted_data = {
        field: str(form_data.get(field, "")).strip()
        for field in [
            "alias",
            "brand",
            "name",
            "variant",
            "last_known_url",
            "last_known_sku",
        ]
    }
    submitted_data["shelf_number"] = _normalize_optional_numeric_text(form_data.get("shelf_number"))
    submitted_data["display_order"] = _normalize_optional_numeric_text(form_data.get("display_order"))
    submitted_data["last_known_sku"] = submitted_data["last_known_sku"] or "unknown"
    return submitted_data


def _validate_product_submission(submitted_data: Dict[str, str]) -> Optional[str]:
    """
    Responsabilidade:
        Validar os campos minimos para persistencia confiavel do produto.

    Parametros:
        submitted_data: Payload ja normalizado vindo do formulario HTML.

    Retorno:
        Mensagem de erro quando houver dado invalido; caso contrario, None.

    Contexto de uso:
        Evita gravacoes inconsistentes ou invisiveis na UI, como alias vazio ou
        URL ausente, que poderiam dar a impressao de cadastro bem-sucedido.
    """

    required_fields = {
        "alias": "Informe um alias para identificar o produto.",
        "brand": "Informe a marca do produto.",
        "name": "Informe o nome do produto.",
        "last_known_url": "Informe a URL conhecida do produto.",
    }
    for field_name, error_message in required_fields.items():
        if not str(submitted_data.get(field_name, "")).strip():
            return error_message

    raw_display_order = str(submitted_data.get("display_order", "")).strip()
    if raw_display_order:
        try:
            if int(raw_display_order) < 1:
                return "A ordem na prateleira deve ser maior que zero."
        except ValueError:
            return "A ordem na prateleira precisa ser um numero inteiro."

    raw_shelf_number = str(submitted_data.get("shelf_number", "")).strip()
    if raw_shelf_number:
        try:
            if int(raw_shelf_number) < 1:
                return "A prateleira informada precisa ser valida."
        except ValueError:
            return "A prateleira informada precisa ser numerica."

    return None


def _build_product_record_from_submission(submitted_data: Dict[str, str]) -> ProductRecord:
    """
    Responsabilidade:
        Converter o payload do formulario em ProductRecord pronto para persistir.

    Parametros:
        submitted_data: Dicionario validado com os campos do formulario.

    Retorno:
        ProductRecord com tipos adequados para a camada de storage.

    Contexto de uso:
        Mantem a montagem do modelo em um ponto unico para reduzir divergencia
        entre criacao e edicao, especialmente nos campos opcionais numericos.
    """

    return ProductRecord(
        alias=submitted_data["alias"],
        brand=submitted_data["brand"],
        name=submitted_data["name"],
        variant=submitted_data["variant"],
        last_known_url=submitted_data["last_known_url"],
        last_known_sku=submitted_data["last_known_sku"],
        shelf_number=int(submitted_data["shelf_number"]) if submitted_data["shelf_number"] else None,
        display_order=int(submitted_data["display_order"]) if submitted_data["display_order"] else None,
    )


def _validate_alias_availability(
    product_store: ProductStoreService,
    desired_alias: str,
    current_alias: Optional[str] = None,
) -> Optional[str]:
    """
    Responsabilidade:
        Validar se o alias desejado esta livre para criacao ou edicao.

    Parametros:
        product_store: Storage usado para consultar aliases existentes.
        desired_alias: Alias informado no formulario.
        current_alias: Alias atual do produto em edicao, quando houver.

    Retorno:
        Mensagem de erro em caso de colisao; caso contrario, None.

    Contexto de uso:
        Impede sobrescrita silenciosa de outro produto ao editar alias.
    """

    normalized_desired_alias = desired_alias.strip()
    existing_product = product_store.get_by_alias(normalized_desired_alias)
    if existing_product is None:
        return None

    normalized_current_alias = str(current_alias or "").strip()
    if normalized_current_alias and existing_product.alias == normalized_current_alias:
        return None

    return f"Ja existe um produto cadastrado com o alias '{normalized_desired_alias}'."


def _build_latest_event_map(events: Iterable[SkuEvent]) -> Dict[str, SkuEvent]:
    """
    Responsabilidade:
        Consolidar o ultimo evento conhecido por alias.

    Parametros:
        events: Colecao de eventos historicos carregados do store.

    Retorno:
        Mapa de alias para o evento mais recente encontrado.

    Contexto de uso:
        Base para status de sync, listas recentes e tela Updates.
    """

    latest_event_by_alias: Dict[str, SkuEvent] = {}
    for event in sorted(
        events,
        key=lambda item: _parse_iso_timestamp(item.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
    ):
        latest_event_by_alias[event.alias] = event
    return latest_event_by_alias


def _build_preview_map(
    request: Request,
    products: List[ProductRecord],
    fetch_limit: int = 0,
) -> Dict[str, Optional[ProductPreview]]:
    """
    Responsabilidade:
        Carregar previews cached e buscar alguns faltantes de forma controlada.

    Parametros:
        request: Requisicao atual para acessar o servico de preview.
        products: Produtos que precisam de sinais visuais.
        fetch_limit: Quantidade maxima de previews faltantes a buscar agora.

    Retorno:
        Mapa de alias para ProductPreview ou None.

    Contexto de uso:
        Balanceia qualidade visual com custo de rede em listas mobile-first.
    """

    preview_service = _get_preview_service(request)
    if preview_service is None:
        return {product.alias: None for product in products}

    preview_map: Dict[str, Optional[ProductPreview]] = {}
    fetched_count = 0
    for product in products:
        preview = preview_service.get_cached_preview(product)
        if preview is None and fetched_count < fetch_limit:
            preview = preview_service.ensure_preview(product)
            if preview is not None:
                fetched_count += 1
        preview_map[product.alias] = preview

    return preview_map


def _build_product_activity(
    product: ProductRecord,
    latest_event: Optional[SkuEvent],
    manual_snapshot: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Traduzir historico e feedback manual em um status unico para a UI.

    Parametros:
        product: Produto em analise.
        latest_event: Ultimo evento persistido do historico para o alias.
        manual_snapshot: Feedback recente em memoria apos update manual.

    Retorno:
        Dicionario com chave de status, tom visual e mensagens amigaveis.

    Contexto de uso:
        Reutilizado por Home, Search, Saved e detalhe do produto.
    """

    if manual_snapshot:
        recorded_at = manual_snapshot.get("recorded_at")
        if manual_snapshot.get("success"):
            return {
                "status_key": "manual_ok",
                "status_tone": "success",
                "status_label": "Atualizado agora",
                "status_message": manual_snapshot.get("message") or "Atualização manual concluída.",
                "timestamp": recorded_at,
                "timestamp_label": _format_timestamp_label(recorded_at),
                "is_today": _is_today(recorded_at),
            }

        return {
            "status_key": "manual_error",
            "status_tone": "error",
            "status_label": "Falha na tentativa",
            "status_message": manual_snapshot.get("message") or "A atualização manual falhou.",
            "timestamp": recorded_at,
            "timestamp_label": _format_timestamp_label(recorded_at),
            "is_today": _is_today(recorded_at),
        }

    if latest_event is None:
        return {
            "status_key": "idle",
            "status_tone": "neutral",
            "status_label": "Sem sincronização",
            "status_message": "Ainda não há histórico recente para este produto.",
            "timestamp": None,
            "timestamp_label": "Sem sync recente",
            "is_today": False,
        }

    if latest_event.event_type == "error":
        return {
            "status_key": "failed",
            "status_tone": "error",
            "status_label": "Falha na sincronização",
            "status_message": "A última verificação terminou com erro e pede revisão.",
            "timestamp": latest_event.timestamp,
            "timestamp_label": _format_timestamp_label(latest_event.timestamp),
            "is_today": _is_today(latest_event.timestamp),
        }

    if latest_event.event_type in {"sku_changed", "url_changed"}:
        change_description = (
            f"{latest_event.old_sku or 'sem SKU'} -> {latest_event.new_sku or 'sem SKU'}"
            if latest_event.event_type == "sku_changed"
            else "URL atualizada"
        )
        return {
            "status_key": "changed",
            "status_tone": "warning",
            "status_label": "Código atualizado",
            "status_message": change_description,
            "timestamp": latest_event.timestamp,
            "timestamp_label": _format_timestamp_label(latest_event.timestamp),
            "is_today": _is_today(latest_event.timestamp),
        }

    return {
        "status_key": "synced",
        "status_tone": "success",
        "status_label": "Sincronizado",
        "status_message": "O último ciclo passou sem mudanças relevantes.",
        "timestamp": latest_event.timestamp,
        "timestamp_label": _format_timestamp_label(latest_event.timestamp),
        "is_today": _is_today(latest_event.timestamp),
    }


def _build_product_card(
    product: ProductRecord,
    preview: Optional[ProductPreview],
    activity: Dict[str, Any],
    is_saved: bool,
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar a estrutura enxuta consumida pelos cards de produto.

    Parametros:
        product: Produto persistido.
        preview: Preview visual cached ou recem-buscado.
        activity: Status operacional consolidado do produto.
        is_saved: Indica se o produto esta salvo como atalho.

    Retorno:
        Dicionario com campos prontos para os templates de lista.

    Contexto de uso:
        Padroniza exibicao entre Home, Search e Saved.
    """

    variant_summary_parts = [part for part in [product.brand, product.variant] if str(part).strip()]
    return {
        "alias": product.alias,
        "name": product.name,
        "brand": product.brand,
        "variant": product.variant,
        "variant_summary": " • ".join(variant_summary_parts) if variant_summary_parts else "Sem variante",
        "sku": product.last_known_sku,
        "url": product.last_known_url,
        "image_url": preview.image_url if preview else None,
        "preview_title": preview.title if preview else None,
        "activity": activity,
        "is_saved": is_saved,
    }


def _sort_product_cards(cards: List[Dict[str, Any]], sort_key: str) -> List[Dict[str, Any]]:
    """
    Responsabilidade:
        Ordenar cards conforme criterio de navegacao escolhido pelo operador.

    Parametros:
        cards: Lista de cards ja montados.
        sort_key: Chave de ordenacao recebida da querystring.

    Retorno:
        Lista ordenada sem mutar a colecao original recebida.

    Contexto de uso:
        Utilizado pela tela Search e por listas derivadas da Home.
    """

    sortable_cards = list(cards)

    if sort_key == "name":
        return sorted(sortable_cards, key=lambda card: (card["name"].lower(), card["alias"]))

    if sort_key == "sku":
        return sorted(sortable_cards, key=lambda card: (str(card["sku"]).lower(), card["name"].lower()))

    return sorted(
        sortable_cards,
        key=lambda card: _parse_iso_timestamp(card["activity"].get("timestamp"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def _apply_search_filters(
    cards: List[Dict[str, Any]],
    search_query: str,
    brand_filter: str,
    sync_status_filter: str,
    updated_scope: str,
    saved_only: bool,
    image_only: bool,
) -> List[Dict[str, Any]]:
    """
    Responsabilidade:
        Aplicar filtros operacionais na lista de produtos do Search.

    Parametros:
        cards: Cards ja montados para busca.
        search_query: Texto livre de nome, SKU ou alias.
        brand_filter: Marca selecionada pelo usuario.
        sync_status_filter: Status de sync desejado.
        updated_scope: Escopo temporal rapido como `today`.
        saved_only: Restringe a lista aos produtos salvos.
        image_only: Mantem apenas itens com imagem conhecida.

    Retorno:
        Lista filtrada conforme os criterios recebidos.

    Contexto de uso:
        Permite uma busca operacional simples sem introduzir stack JS pesado.
    """

    normalized_query = search_query.strip().lower()
    normalized_brand = brand_filter.strip().lower()
    normalized_sync_status = sync_status_filter.strip().lower()
    normalized_updated_scope = updated_scope.strip().lower()

    filtered_cards: List[Dict[str, Any]] = []
    for card in cards:
        haystack = " ".join(
            [
                card["alias"],
                card["name"],
                card["brand"],
                card["variant"],
                card["sku"],
            ]
        ).lower()
        if normalized_query and normalized_query not in haystack:
            continue

        if normalized_brand and card["brand"].lower() != normalized_brand:
            continue

        if normalized_sync_status and card["activity"]["status_key"] != normalized_sync_status:
            continue

        if normalized_updated_scope == "today" and not card["activity"].get("is_today"):
            continue

        if normalized_updated_scope == "recent" and not card["activity"].get("timestamp"):
            continue

        if saved_only and not card["is_saved"]:
            continue

        if image_only and not card["image_url"]:
            continue

        filtered_cards.append(card)

    return filtered_cards


def _build_brand_chips(products: Iterable[ProductRecord]) -> List[Dict[str, Any]]:
    """
    Responsabilidade:
        Transformar marcas existentes em chips de navegacao rapida.

    Parametros:
        products: Colecao de produtos persistidos no catalogo.

    Retorno:
        Lista de chips com marca, quantidade e URL de atalho.

    Contexto de uso:
        Substitui a ideia de categorias quando o modelo atual nao as oferece.
    """

    brand_counter: Dict[str, int] = {}
    for product in products:
        normalized_brand = product.brand.strip()
        if not normalized_brand:
            continue
        brand_counter[normalized_brand] = brand_counter.get(normalized_brand, 0) + 1

    chips = [
        {
            "label": brand_name,
            "count": count,
            "href": f"/dashboard/search?{urlencode({'brand': brand_name})}",
        }
        for brand_name, count in sorted(brand_counter.items(), key=lambda item: (-item[1], item[0].lower()))
    ]
    return chips[:8]


def _build_short_product_name(product_name: str, product_brand: str) -> str:
    """
    Responsabilidade:
        Encurtar nome exibido no card sem perder a identidade principal.

    Parametros:
        product_name: Nome principal persistido do produto.
        product_brand: Marca usada para remover repeticao desnecessaria.

    Retorno:
        Titulo curto e mais facil de escanear na prateleira.

    Contexto de uso:
        Aplicado na tela de detalhe da prateleira para ganhar densidade.
    """

    normalized_name = str(product_name).strip()
    normalized_brand = str(product_brand).strip()
    if not normalized_name:
        return ""

    if normalized_brand and normalized_name.lower().startswith(normalized_brand.lower()):
        shortened_name = normalized_name[len(normalized_brand):].strip(" -")
        if shortened_name:
            return shortened_name

    return normalized_name


def _build_group_variant_payload(
    grouped_product: GroupedParentProduct,
    variant_alias: str,
    preview: Optional[ProductPreview],
    activity: Dict[str, str],
    barcode_module_width_px: int,
    barcode_height_px: int,
    include_barcode_data_uri: bool = True,
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Converter uma variante agrupada em dados prontos para a interface web.

    Parametros:
        grouped_product: Produto pai ao qual a variante pertence.
        variant_alias: Alias real da variante selecionada.
        preview: Preview visual opcional carregado do cache/fetcher.
        activity: Resumo operacional de sincronizacao da variante.
        barcode_module_width_px: Largura do modulo usada ao montar o SVG.
        barcode_height_px: Altura das barras usada no SVG.
        include_barcode_data_uri: Define se o payload precisa incluir o SVG.

    Retorno:
        Dicionario serializavel com links, SKU, status e barcode da variante.

    Contexto de uso:
        Reutilizado tanto nas listas por prateleira quanto na tela de detalhe
        para manter o frontend sincronizado com o alias real da variante.
    """

    variant_product = next(
        (
            grouped_variant.product
            for grouped_variant in grouped_product.variants
            if grouped_variant.alias == variant_alias
        ),
        None,
    )
    if variant_product is None:
        raise KeyError(f"Variante '{variant_alias}' nao encontrada no grupo '{grouped_product.group_id}'")

    variant_label = next(
        (
            grouped_variant.label
            for grouped_variant in grouped_product.variants
            if grouped_variant.alias == variant_alias
        ),
        variant_product.variant or "Padrao",
    )

    barcode_data_uri = None
    if include_barcode_data_uri:
        barcode_data_uri = build_code128_svg_data_uri(
            variant_product.variant_code,
            module_width_px=barcode_module_width_px,
            bar_height_px=barcode_height_px,
        )

    return {
        "alias": variant_product.alias,
        "label": variant_label,
        "variant_code": variant_product.variant_code,
        "parent_page_sku": grouped_product.parent_page_sku,
        "image_url": preview.image_url if preview else None,
        "detail_href": f"/dashboard/products/{variant_product.alias}",
        "barcode_href": f"/dashboard/products/{variant_product.alias}/barcode",
        "update_href": f"/dashboard/products/{variant_product.alias}/update",
        "edit_href": f"/dashboard/products/{variant_product.alias}/edit",
        "delete_href": f"/dashboard/products/{variant_product.alias}/delete",
        "save_href": f"/dashboard/products/{variant_product.alias}/toggle-saved",
        "last_known_url": variant_product.last_known_url,
        "status_label": activity["status_label"],
        "status_tone": activity["status_tone"],
        "timestamp_label": activity["timestamp_label"],
        "barcode_data_uri": barcode_data_uri,
    }


def _build_group_search_text(grouped_product: GroupedParentProduct) -> str:
    """
    Responsabilidade:
        Consolidar o texto pesquisavel de um produto pai e suas variantes.

    Parametros:
        grouped_product: Produto pai com todas as variantes agrupadas.

    Retorno:
        String unica em minusculas contendo sinais uteis para filtro.

    Contexto de uso:
        Permite que a busca da prateleira continue funcionando por nome, SKU ou
        variante mesmo quando a UI deixa de exibir as variantes como cards separados.
    """

    searchable_parts = [grouped_product.parent_name, grouped_product.brand]
    for variant in grouped_product.variants:
        searchable_parts.extend(
            [
                variant.label,
                variant.product.variant_code,
                variant.product.alias,
                variant.product.name,
            ]
        )

    return " ".join(part for part in searchable_parts if part).lower()


def _build_shelf_brand_filters(
    shelf_number: int,
    grouped_products: List[GroupedParentProduct],
    query_text: str,
    selected_brand: str,
) -> List[Dict[str, str]]:
    """
    Responsabilidade:
        Montar os filtros de marca disponiveis para uma prateleira fisica.

    Parametros:
        shelf_number: Numero da prateleira atualmente aberta.
        grouped_products: Produtos pai ja agrupados dentro da prateleira.
        query_text: Texto atual de busca para preservacao na URL.
        selected_brand: Marca atualmente selecionada no filtro.

    Retorno:
        Lista de chips com label, href e estado de selecao.

    Contexto de uso:
        Separa a referencia fisica da prateleira da filtragem por marca, para
        deixar claro que varias marcas podem coexistir no mesmo expositor.
    """

    normalized_selected_brand = str(selected_brand).strip()
    available_brands = sorted(
        {grouped_product.brand for grouped_product in grouped_products if grouped_product.brand},
        key=normalize_text,
    )

    filter_chips = [
        {
            "label": "Todas",
            "href": f"/dashboard/prateleiras/{shelf_number}?{urlencode({'q': query_text})}" if query_text else f"/dashboard/prateleiras/{shelf_number}",
            "is_selected": not normalized_selected_brand,
        }
    ]

    for brand in available_brands:
        query_params = {"brand": brand}
        if query_text:
            query_params["q"] = query_text

        filter_chips.append(
            {
                "label": brand,
                "href": f"/dashboard/prateleiras/{shelf_number}?{urlencode(query_params)}",
                "is_selected": brand == normalized_selected_brand,
            }
        )

    return filter_chips


def _build_shelf_card_visual_metadata(request: Request, shelf_number: int, shelf_title: str) -> Dict[str, str]:
    """
    Responsabilidade:
        Definir textos e variantes visuais das prateleiras da perfumaria.

    Parametros:
        request: Requisição atual para acesso ao catálogo visual centralizado.
        shelf_number: Numero fixo da prateleira fisica.
        shelf_title: Titulo operacional persistido para a prateleira.

    Retorno:
        Dicionario com wordmark do banner, rotulos auxiliares e estilo visual.

    Contexto de uso:
        Mantem a camada de template enxuta e centraliza o mapeamento entre a
        prateleira operacional e a apresentacao inspirada nos expositores reais.
    """

    visual = _get_shelf_banner_service(request).get_visual(shelf_number=shelf_number, shelf_title=shelf_title)
    return {
        "banner_wordmark": visual.banner_wordmark,
        "banner_sublabel": visual.banner_sublabel,
        "body_label": visual.body_label,
        "banner_variant": visual.banner_key,
        "banner_image_file": visual.banner_image_file,
        "legacy_title": visual.legacy_title,
    }


def _resolve_shelf_banner_image_url(request: Request, banner_image_file: str, shelf_number: int, shelf_title: str) -> str:
    """
    Responsabilidade:
        Resolver a URL publica do banner ilustrado da prateleira quando o
        arquivo existir no diretório estático do app.

    Parâmetros:
        request: Requisição atual para acesso ao catálogo visual.
        banner_image_file: Nome do arquivo PNG configurado para a prateleira.
        shelf_number: Número da prateleira consultada.
        shelf_title: Título visível da prateleira.

    Retorno:
        URL pública do banner quando houver arquivo válido; caso contrário,
        string vazia para manter o fallback tipográfico atual.

    Contexto de uso:
        Mantém a decisão de caminho estático fora do template e permite
        evoluir a origem dos banners sem espalhar regras de arquivo pela UI.
    """

    del banner_image_file
    visual = _get_shelf_banner_service(request).get_visual(shelf_number=shelf_number, shelf_title=shelf_title)
    return _get_shelf_banner_service(request).build_public_image_url(visual)


def _build_shelves_context(request: Request) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar a tela inicial baseada nas prateleiras fisicas da perfumaria.

    Parametros:
        request: Requisicao atual para acesso ao catalogo e ao servico de prateleiras.

    Retorno:
        Dicionario pronto para renderizacao da tela inicial por prateleiras.

    Contexto de uso:
        Substitui a Home generica por uma navegacao fisica orientada a loja.
    """

    products = _get_store_service(request).list_products()
    shelf_service = _get_shelf_service(request)

    shelf_cards = []
    for shelf in shelf_service.list_shelves():
        shelf_products = shelf_service.list_products_for_shelf(products, shelf.shelf_number)
        visual_metadata = _build_shelf_card_visual_metadata(request, shelf.shelf_number, shelf.shelf_title)
        shelf_cards.append(
            {
                "shelf_number": shelf.shelf_number,
                "shelf_title": shelf.shelf_title,
                "full_title": f"Prateleira {shelf.shelf_number:02d} — {shelf.shelf_title}",
                "brand_group": shelf.brand_group,
                "product_count": len(shelf_products),
                "href": f"/dashboard/prateleiras/{shelf.shelf_number}",
                "banner_image_url": _resolve_shelf_banner_image_url(
                    request=request,
                    banner_image_file=visual_metadata.get("banner_image_file", ""),
                    shelf_number=shelf.shelf_number,
                    shelf_title=shelf.shelf_title,
                ),
                **visual_metadata,
            }
        )

    import_feedback = _resolve_dashboard_import_feedback_message(request)

    return _with_app_shell(
        request=request,
        active_tab="home",
        context={
            "request": request,
            "page_title": "Prateleiras",
            "shelves": shelf_cards,
            "import_feedback": import_feedback,
            "prestige_shelf_import_action_url": "/dashboard/imports/prestige-shelf-03",
        },
    )


def _resolve_dashboard_import_feedback_message(request: Request) -> Optional[Dict[str, str]]:
    """
    Responsabilidade:
        Traduzir query params de importacao em mensagem curta para a Home.

    Parametros:
        request: Requisicao atual com possivel feedback apos importacao.

    Retorno:
        Dicionario com tipo e mensagem ou None quando nao houver feedback.

    Contexto de uso:
        Permite confirmar no proprio dashboard se a carga da Railway funcionou
        sem depender de acesso a logs ou shell do ambiente.
    """

    import_status = request.query_params.get("import_status", "").strip()
    imported_count = request.query_params.get("import_count", "").strip()
    seed_name = request.query_params.get("seed", "").strip()
    if import_status == "success":
        count_label = imported_count or "0"
        return {
            "type": "success",
            "message": f"Importação concluída no ambiente atual: {count_label} produto(s) processado(s) pelo seed {seed_name or 'interno'}.",
        }

    if import_status == "error":
        return {
            "type": "error",
            "message": request.query_params.get(
                "import_message",
                "Não foi possível importar os produtos neste ambiente.",
            ).strip()
            or "Não foi possível importar os produtos neste ambiente.",
        }

    return None


def _run_builtin_curated_seed_import(request: Request, seed_name: str) -> tuple[bool, str, int]:
    """
    Responsabilidade:
        Executar uma importacao curada embarcada no proprio codigo do app.

    Parametros:
        request: Requisicao atual para obter fetcher e storage compartilhados.
        seed_name: Nome logico do seed interno que deve ser aplicado.

    Retorno:
        Tupla com sucesso, mensagem amigavel e quantidade processada.

    Contexto de uso:
        Permite disparar cargas administrativas direto na Railway pelo painel
        web, sem exigir shell ou manipulacao manual do volume persistente.
    """

    fetcher = _get_fetcher_service(request)
    if fetcher is None:
        return False, "O ambiente atual não possui fetcher configurado para importar o seed interno.", 0

    seed_file_path = resolve_builtin_curated_seed_file(seed_name)
    import_service = CuratedRennerImportService(
        fetcher=fetcher,
        product_store=_get_store_service(request),
    )
    entries = import_service.load_entries_from_file(seed_file_path)
    results = import_service.import_entries(entries)
    failed_results = [result for result in results if not result.success]
    if failed_results:
        return False, failed_results[0].message, len(results)

    return True, "Importação concluída com sucesso.", len(results)


def _build_shelf_detail_context(request: Request, shelf_number: int) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar o detalhe de uma prateleira com os produtos alocados nela.

    Parametros:
        request: Requisicao atual para acesso a produtos, historico e previews.
        shelf_number: Numero fisico da prateleira aberta.

    Retorno:
        Dicionario pronto para a tela de detalhe da prateleira.

    Contexto de uso:
        Fluxo principal do app quando o operador busca localizacao fisica primeiro.
    """

    shelf_service = _get_shelf_service(request)
    shelf_definition = shelf_service.get_shelf(shelf_number)
    if shelf_definition is None:
        return _with_app_shell(
            request=request,
            active_tab="home",
            context={
                "request": request,
                "page_title": "Prateleira não encontrada",
                "error_message": "A prateleira informada não foi encontrada.",
            },
        )

    products = _get_store_service(request).list_products()
    shelf_products = shelf_service.list_products_for_shelf(products, shelf_number)
    shelf_visual = _build_shelf_card_visual_metadata(request, shelf_definition.shelf_number, shelf_definition.shelf_title)
    grouped_products = _get_product_group_service(request).group_products(shelf_products)
    latest_events = _build_latest_event_map(_get_history_store(request).list_events())
    preview_map = _build_preview_map(request, shelf_products, fetch_limit=max(12, len(shelf_products)))
    raw_query_text = request.query_params.get("q", "").strip()
    query_text = raw_query_text.lower()
    selected_brand = request.query_params.get("brand", "").strip()
    brand_filters = _build_shelf_brand_filters(
        shelf_number=shelf_number,
        grouped_products=grouped_products,
        query_text=raw_query_text,
        selected_brand=selected_brand,
    )

    shelf_product_cards = []
    for grouped_product in grouped_products:
        if selected_brand and grouped_product.brand != selected_brand:
            continue
        if query_text and query_text not in _build_group_search_text(grouped_product):
            continue

        selected_variant = _get_product_group_service(request).choose_default_variant(grouped_product)
        selected_preview = preview_map.get(selected_variant.alias)
        selected_activity = _build_product_activity(
            selected_variant.product,
            latest_events.get(selected_variant.alias),
            last_update_by_alias.get(selected_variant.alias),
        )

        variant_options = []
        for grouped_variant in grouped_product.variants:
            variant_options.append(
                _build_group_variant_payload(
                    grouped_product=grouped_product,
                    variant_alias=grouped_variant.alias,
                    preview=preview_map.get(grouped_variant.alias),
                    activity=_build_product_activity(
                        grouped_variant.product,
                        latest_events.get(grouped_variant.alias),
                        last_update_by_alias.get(grouped_variant.alias),
                    ),
                    barcode_module_width_px=2,
                    barcode_height_px=72,
                    include_barcode_data_uri=False,
                )
            )

        shelf_product_cards.append(
            {
                "group_id": grouped_product.group_id,
                "name": _build_short_product_name(grouped_product.parent_name, grouped_product.brand),
                "brand": grouped_product.brand,
                "variant_code": selected_variant.product.variant_code,
                "parent_page_sku": grouped_product.parent_page_sku,
                "image_url": selected_preview.image_url if selected_preview else None,
                "barcode_href": f"/dashboard/products/{selected_variant.alias}/barcode",
                "detail_href": f"/dashboard/products/{selected_variant.alias}",
                "status_label": selected_activity["status_label"],
                "placement": shelf_service.get_product_placement(
                    product=selected_variant.product,
                    all_products=products,
                ),
                "selected_alias": selected_variant.alias,
                "selected_variant_label": selected_variant.label,
                "variants": variant_options,
            }
        )

    return _with_app_shell(
        request=request,
        active_tab="home",
        context={
            "request": request,
            "page_title": f"Prateleira {shelf_definition.shelf_number:02d}",
            "shelf": shelf_definition,
            "reference_label": shelf_definition.shelf_title,
            "shelf_visual": shelf_visual,
            "banner_image_url": _resolve_shelf_banner_image_url(
                request=request,
                banner_image_file=shelf_visual.get("banner_image_file", ""),
                shelf_number=shelf_definition.shelf_number,
                shelf_title=shelf_definition.shelf_title,
            ),
            "products": shelf_product_cards,
            "query_text": raw_query_text,
            "brand_filters": brand_filters,
            "selected_brand": selected_brand,
        },
    )


def _build_home_context(request: Request) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar contexto da Home com foco em descoberta rapida e status de sync.

    Parametros:
        request: Requisicao atual para acesso a servicos e query params.

    Retorno:
        Dicionario pronto para renderizacao da tela inicial.

    Contexto de uso:
        Alimenta a Home mobile-first com busca, atalhos e produtos recentes.
    """

    product_store = _get_store_service(request)
    saved_service = _get_saved_service(request)
    products = product_store.list_products()
    history_events = _get_history_store(request).list_events()
    latest_events = _build_latest_event_map(history_events)
    saved_aliases = saved_service.get_saved_aliases_set()
    preview_map = _build_preview_map(request, products, fetch_limit=6)

    cards = [
        _build_product_card(
            product=product,
            preview=preview_map.get(product.alias),
            activity=_build_product_activity(product, latest_events.get(product.alias), last_update_by_alias.get(product.alias)),
            is_saved=product.alias in saved_aliases,
        )
        for product in products
    ]
    recent_cards = _sort_product_cards(cards, "recent")[:8]

    last_monitor_snapshot = getattr(request.app.state, "last_monitor_snapshot", None) or {}
    changed_today_count = len(
        [
            event
            for event in history_events
            if event.event_type in {"sku_changed", "url_changed"} and _is_today(event.timestamp)
        ]
    )

    sync_summary = {
        "last_sync_label": _format_timestamp_label(last_monitor_snapshot.get("recorded_at")),
        "processed_count": last_monitor_snapshot.get("processed_count", 0),
        "changed_count": last_monitor_snapshot.get("changed_count", changed_today_count),
        "error_count": last_monitor_snapshot.get("error_count", 0),
    }

    quick_actions = [
        {"label": "Recentes", "href": "/dashboard/search?updated_scope=recent", "count": len(recent_cards)},
        {"label": "Salvos", "href": "/dashboard/saved", "count": len(saved_aliases)},
        {"label": "Atualizados hoje", "href": "/dashboard/search?updated_scope=today", "count": changed_today_count},
    ]

    return _with_app_shell(
        request=request,
        active_tab="home",
        context={
            "request": request,
            "page_title": "Início",
            "products_count": len(products),
            "quick_actions": quick_actions,
            "brand_chips": _build_brand_chips(products),
            "recent_products": recent_cards,
            "sync_summary": sync_summary,
        },
    )


def _resolve_product_detail_success_message(request: Request) -> Optional[str]:
    """
    Responsabilidade:
        Traduzir marcadores de sucesso da URL em feedback claro na tela.

    Parametros:
        request: Requisicao atual com query params opcionais de feedback.

    Retorno:
        Mensagem curta de sucesso ou None quando nao houver marcador.

    Contexto de uso:
        Mantem o fluxo server-side simples: apos persistir e redirecionar, o
        detalhe do produto confirma ao operador que o item realmente foi salvo.
    """

    if request.query_params.get("created", "") == "1":
        return "Produto salvo com sucesso e relido do armazenamento."

    return None


def _build_search_context(request: Request) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar contexto da tela Search com filtros e ordenacao mobile-first.

    Parametros:
        request: Requisicao atual com query params de busca e filtro.

    Retorno:
        Dicionario pronto para renderizacao da lista pesquisavel.

    Contexto de uso:
        Centraliza logica da aba Search sem espalhar filtros pelo template.
    """

    product_store = _get_store_service(request)
    saved_service = _get_saved_service(request)
    products = product_store.list_products()
    history_events = _get_history_store(request).list_events()
    latest_events = _build_latest_event_map(history_events)
    saved_aliases = saved_service.get_saved_aliases_set()
    preview_map = _build_preview_map(request, products, fetch_limit=12)

    all_cards = [
        _build_product_card(
            product=product,
            preview=preview_map.get(product.alias),
            activity=_build_product_activity(product, latest_events.get(product.alias), last_update_by_alias.get(product.alias)),
            is_saved=product.alias in saved_aliases,
        )
        for product in products
    ]

    active_filters = {
        "q": request.query_params.get("q", ""),
        "brand": request.query_params.get("brand", ""),
        "sync_status": request.query_params.get("sync_status", ""),
        "updated_scope": request.query_params.get("updated_scope", ""),
        "sort": request.query_params.get("sort", "recent"),
        "saved_only": request.query_params.get("saved_only", "") == "1",
        "image_only": request.query_params.get("image_only", "") == "1",
    }
    filtered_cards = _apply_search_filters(
        cards=all_cards,
        search_query=active_filters["q"],
        brand_filter=active_filters["brand"],
        sync_status_filter=active_filters["sync_status"],
        updated_scope=active_filters["updated_scope"],
        saved_only=active_filters["saved_only"],
        image_only=active_filters["image_only"],
    )
    sorted_cards = _sort_product_cards(filtered_cards, active_filters["sort"])

    return _with_app_shell(
        request=request,
        active_tab="search",
        context={
            "request": request,
            "page_title": "Buscar",
            "products": sorted_cards,
            "filters": active_filters,
            "brand_chips": _build_brand_chips(products),
            "results_count": len(sorted_cards),
            "available_statuses": [
                {"value": "manual_ok", "label": "Atualizado agora"},
                {"value": "manual_error", "label": "Falha manual"},
                {"value": "changed", "label": "Código atualizado"},
                {"value": "failed", "label": "Falha na sincronização"},
                {"value": "idle", "label": "Sem sincronização"},
            ],
        },
    )


def _build_saved_context(request: Request) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar contexto da aba Saved com atalhos persistidos do operador.

    Parametros:
        request: Requisicao atual para acesso a storage e historico.

    Retorno:
        Dicionario pronto para a tela de produtos salvos.

    Contexto de uso:
        Oferece acesso rapido aos itens usados com mais frequencia.
    """

    product_store = _get_store_service(request)
    saved_service = _get_saved_service(request)
    saved_aliases_in_order = saved_service.list_saved_aliases()
    all_products_by_alias = {product.alias: product for product in product_store.list_products()}
    saved_products = [all_products_by_alias[alias] for alias in saved_aliases_in_order if alias in all_products_by_alias]
    history_events = _get_history_store(request).list_events()
    latest_events = _build_latest_event_map(history_events)
    preview_map = _build_preview_map(request, saved_products, fetch_limit=8)

    cards = [
        _build_product_card(
            product=product,
            preview=preview_map.get(product.alias),
            activity=_build_product_activity(product, latest_events.get(product.alias), last_update_by_alias.get(product.alias)),
            is_saved=True,
        )
        for product in saved_products
    ]

    return _with_app_shell(
        request=request,
        active_tab="saved",
        context={
            "request": request,
            "page_title": "Salvos",
            "products": _sort_product_cards(cards, "recent"),
        },
    )


def _build_updates_context(request: Request) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar contexto da aba Updates com resumo claro de sincronizacao.

    Parametros:
        request: Requisicao atual para acesso ao historico e snapshot em memoria.

    Retorno:
        Dicionario pronto para renderizacao da tela operacional de updates.

    Contexto de uso:
        Consolida confianca do sync sem expor log tecnico excessivo.
    """

    product_store = _get_store_service(request)
    products_by_alias = {product.alias: product for product in product_store.list_products()}
    history_events = sorted(
        _get_history_store(request).list_events(),
        key=lambda item: _parse_iso_timestamp(item.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    last_monitor_snapshot = getattr(request.app.state, "last_monitor_snapshot", None) or {}

    changed_items = []
    latest_error_by_alias: Dict[str, SkuEvent] = {}
    for event in history_events:
        if event.event_type in {"sku_changed", "url_changed"}:
            related_product = products_by_alias.get(event.alias)
            changed_items.append(
                {
                    "alias": event.alias,
                    "product_name": related_product.name if related_product else _humanize_alias(event.alias),
                    "old_code": event.old_sku,
                    "new_code": event.new_sku,
                    "timestamp": event.timestamp,
                    "timestamp_label": _format_timestamp_label(event.timestamp),
                    "event_type": event.event_type,
                }
            )

        if event.event_type == "error" and event.alias not in latest_error_by_alias:
            latest_error_by_alias[event.alias] = event

    failed_items = []
    for alias, event in latest_error_by_alias.items():
        related_product = products_by_alias.get(alias)
        failed_items.append(
            {
                "alias": alias,
                "product_name": related_product.name if related_product else _humanize_alias(alias),
                "reason": "Não foi possível validar um código atualizado para este produto.",
                "timestamp": event.timestamp,
                "timestamp_label": _format_timestamp_label(event.timestamp),
            }
        )

    summary_metrics = {
        "checked_items": last_monitor_snapshot.get("processed_count", len(products_by_alias)),
        "changed_codes": last_monitor_snapshot.get("changed_count", len(changed_items)),
        "failed_items": last_monitor_snapshot.get("error_count", len(failed_items)),
        "last_sync_label": _format_timestamp_label(last_monitor_snapshot.get("recorded_at")),
    }

    return _with_app_shell(
        request=request,
        active_tab="updates",
        context={
            "request": request,
            "page_title": "Atualizações",
            "summary_metrics": summary_metrics,
            "changed_items": changed_items[:30],
            "failed_items": failed_items[:20],
        },
    )


def _run_monitor_cycle(request: Request) -> Dict[str, Any]:
    """
    Responsabilidade:
        Executar monitoramento em lote e salvar um snapshot resumido da rodada.

    Parametros:
        request: Requisicao atual para acesso ao monitor service.

    Retorno:
        Snapshot serializavel com metricas operacionais da execucao.

    Contexto de uso:
        Compartilhado pelas acoes "Update all" da Home e da aba Updates.
    """

    monitor_summary: MonitorRunSummary = _get_monitor_service(request).run()
    changed_count = len(
        [
            event
            for event in monitor_summary.emitted_events
            if event.event_type in {"sku_changed", "url_changed"}
        ]
    )
    snapshot = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "processed_count": monitor_summary.processed_count,
        "success_count": monitor_summary.success_count,
        "error_count": monitor_summary.error_count,
        "changed_count": changed_count,
    }
    request.app.state.last_monitor_snapshot = snapshot
    return snapshot


def _build_product_detail_context(request: Request, alias: str) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar contexto completo da tela de detalhe operacional do produto.

    Parametros:
        request: Requisicao atual para acesso a storage, historico e preview.
        alias: Alias do produto solicitado.

    Retorno:
        Dicionario pronto para o template de detalhe ou contexto de erro.

    Contexto de uso:
        Centraliza a tela que confirma imagem, SKU e barcode acima da dobra.
    """

    store_service = _get_store_service(request)
    all_products = store_service.list_products()
    product = store_service.get_by_alias(alias)
    if product is None:
        return _with_app_shell(
            request=request,
            active_tab="search",
            context={
                "request": request,
                "page_title": "Produto nao encontrado",
                "error_message": "O produto informado nao foi encontrado no catalogo.",
            },
        )

    grouped_product = _get_product_group_service(request).get_group_for_alias(all_products, alias)
    if grouped_product is None:
        return _with_app_shell(
            request=request,
            active_tab="search",
            context={
                "request": request,
                "page_title": "Produto nao encontrado",
                "error_message": "O produto informado nao foi encontrado no catalogo.",
            },
        )

    selected_variant = _get_product_group_service(request).choose_default_variant(
        grouped_product,
        preferred_alias=alias,
    )
    history_events = _get_history_store(request).list_events_by_alias(selected_variant.alias)
    history_events = sorted(
        history_events,
        key=lambda item: _parse_iso_timestamp(item.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    latest_event = history_events[0] if history_events else None
    variant_products = [grouped_variant.product for grouped_variant in grouped_product.variants]
    preview_map = _build_preview_map(request, variant_products, fetch_limit=max(4, len(variant_products)))
    product_preview = preview_map.get(selected_variant.alias)
    visual_snapshot = _build_product_visual_snapshot(request, selected_variant.product)
    activity = _build_product_activity(
        selected_variant.product,
        latest_event,
        last_update_by_alias.get(selected_variant.alias),
    )
    shelf_placement = _get_shelf_service(request).get_product_placement(
        product=selected_variant.product,
        all_products=all_products,
    )

    latest_history_event_by_alias: Dict[str, Optional[SkuEvent]] = {}
    for grouped_variant in grouped_product.variants:
        variant_history_events = sorted(
            _get_history_store(request).list_events_by_alias(grouped_variant.alias),
            key=lambda item: _parse_iso_timestamp(item.timestamp) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        latest_history_event_by_alias[grouped_variant.alias] = variant_history_events[0] if variant_history_events else None

    variant_options = []
    for grouped_variant in grouped_product.variants:
        variant_options.append(
            _build_group_variant_payload(
                grouped_product=grouped_product,
                variant_alias=grouped_variant.alias,
                preview=preview_map.get(grouped_variant.alias),
                activity=_build_product_activity(
                    grouped_variant.product,
                    latest_history_event_by_alias.get(grouped_variant.alias),
                    last_update_by_alias.get(grouped_variant.alias),
                ),
                barcode_module_width_px=3,
                barcode_height_px=124,
                include_barcode_data_uri=True,
            )
        )

    related_products = []
    for related_group in _get_product_group_service(request).group_products(all_products):
        if related_group.group_id == grouped_product.group_id:
            continue
        if related_group.brand != grouped_product.brand:
            continue
        related_products.append(
            {
                "alias": related_group.variants[0].alias,
                "name": related_group.parent_name,
                "variant": related_group.variants[0].label,
                "sku": related_group.variants[0].product.last_known_sku,
            }
        )

    selected_variant_payload = next(
        (
            variant_payload
            for variant_payload in variant_options
            if variant_payload["alias"] == selected_variant.alias
        ),
        variant_options[0] if variant_options else None,
    )

    history_cards = [
        {
            "event_type": _humanize_event_type(event.event_type),
            "old_sku": event.old_sku,
            "new_sku": event.new_sku,
            "timestamp": event.timestamp,
            "timestamp_label": _format_timestamp_label(event.timestamp),
        }
        for event in history_events[:6]
    ]

    return _with_app_shell(
        request=request,
        active_tab="home",
        context={
            "request": request,
            "page_title": grouped_product.parent_name,
            "success_message": _resolve_product_detail_success_message(request),
            "product": selected_variant.product,
            "parent_product": grouped_product,
            "selected_variant": selected_variant_payload,
            "variant_options": variant_options,
            "product_preview": product_preview,
            "visual_snapshot": visual_snapshot,
            "activity": activity,
            "shelf_placement": shelf_placement,
            "barcode_data_uri": build_code128_svg_data_uri(
                selected_variant.product.variant_code,
                module_width_px=3,
                bar_height_px=124,
            ),
            "is_saved": _get_saved_service(request).is_saved(selected_variant.alias),
            "history_cards": history_cards,
            "related_products": related_products[:4],
            "last_update": last_update_by_alias.get(selected_variant.alias),
        },
    )


@router.get("")
def dashboard_home(request: Request) -> Any:
    """
    Responsabilidade:
        Renderizar a tela inicial baseada nas prateleiras da perfumaria.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        TemplateResponse da tela inicial por prateleiras.

    Contexto de uso:
        Ponto de entrada principal do app para localizar a prateleira primeiro.
    """

    return templates.TemplateResponse(request, "dashboard.html", _build_shelves_context(request))


@router.post("/imports/prestige-shelf-03")
def dashboard_import_prestige_shelf_03(request: Request) -> RedirectResponse:
    """
    Responsabilidade:
        Importar no ambiente atual o seed curado da prateleira 03.

    Parametros:
        request: Requisicao HTTP atual com acesso aos servicos compartilhados.

    Retorno:
        RedirectResponse para a Home com feedback de sucesso ou falha.

    Contexto de uso:
        Facilita a carga inicial na Railway sem depender de shell, tornando a
        operacao acessivel a partir do proprio dashboard web.
    """

    import_succeeded, import_message, processed_count = _run_builtin_curated_seed_import(
        request=request,
        seed_name="prestige_shelf_03_curated",
    )
    query_params = {
        "seed": "prestige-shelf-03",
        "import_count": str(processed_count),
    }
    if import_succeeded:
        query_params["import_status"] = "success"
    else:
        query_params["import_status"] = "error"
        query_params["import_message"] = import_message

    return RedirectResponse(
        url=f"/dashboard?{urlencode(query_params)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/prateleiras/{shelf_number}")
def dashboard_shelf_detail(request: Request, shelf_number: int) -> Any:
    """
    Responsabilidade:
        Renderizar uma prateleira fisica com os produtos nela alocados.

    Parametros:
        request: Requisicao HTTP atual.
        shelf_number: Numero da prateleira aberta pelo operador.

    Retorno:
        TemplateResponse do detalhe da prateleira.

    Contexto de uso:
        Fluxo principal de navegacao da perfumaria prestigio.
    """

    context = _build_shelf_detail_context(request, shelf_number)
    status_code = 404 if context.get("error_message") else 200
    return templates.TemplateResponse(request, "shelf_detail.html", context, status_code=status_code)


@router.get("/search")
def dashboard_search(request: Request) -> Any:
    """
    Responsabilidade:
        Renderizar a tela Search com lista filtravel de produtos.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        TemplateResponse da aba Search.

    Contexto de uso:
        Tela principal para localizar produtos rapidamente por nome, SKU ou alias.
    """

    return templates.TemplateResponse(request, "search.html", _build_search_context(request))


@router.get("/updates")
def dashboard_updates(request: Request) -> Any:
    """
    Responsabilidade:
        Renderizar a tela Updates com resumo e historico de mudancas.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        TemplateResponse da aba Updates.

    Contexto de uso:
        Exibe confianca do sync e mudancas recentes do catalogo.
    """

    return templates.TemplateResponse(request, "updates.html", _build_updates_context(request))


@router.post("/updates/run")
def dashboard_run_updates(request: Request) -> RedirectResponse:
    """
    Responsabilidade:
        Disparar um ciclo manual de monitoramento e voltar para a tela Updates.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        RedirectResponse para a aba Updates apos executar o monitor.

    Contexto de uso:
        Acao principal do CTA "Update all" da nova IA.
    """

    _run_monitor_cycle(request)
    return RedirectResponse(url="/dashboard/updates", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/update-all")
def dashboard_update_all_products(request: Request) -> RedirectResponse:
    """
    Responsabilidade:
        Manter compatibilidade com a rota antiga de update em lote.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        RedirectResponse para a tela Updates.

    Contexto de uso:
        Preserva links antigos e testes existentes enquanto a IA evolui.
    """

    _run_monitor_cycle(request)
    return RedirectResponse(url="/dashboard/updates", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/saved")
def dashboard_saved(request: Request) -> Any:
    """
    Responsabilidade:
        Renderizar a aba Saved com atalhos do operador.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        TemplateResponse da aba Saved.

    Contexto de uso:
        Facilita acesso rapido aos produtos mais usados no dia a dia.
    """

    return templates.TemplateResponse(request, "saved.html", _build_saved_context(request))


@router.post("/products/{alias}/toggle-saved")
async def dashboard_toggle_saved_product(request: Request, alias: str) -> RedirectResponse:
    """
    Responsabilidade:
        Alternar estado salvo de um produto e redirecionar para a origem.

    Parametros:
        request: Requisicao HTTP atual com possivel campo `next`.
        alias: Produto alvo do toggle de favoritos.

    Retorno:
        RedirectResponse para a tela de origem.

    Contexto de uso:
        Acao operacional usada nos cards de lista e na tela de detalhe.
    """

    form_data = await request.form()
    redirect_target = str(form_data.get("next") or request.headers.get("referer") or "/dashboard/saved")
    _get_saved_service(request).toggle_alias(alias)
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/products/new")
def dashboard_new_product_form(request: Request) -> Any:
    """
    Responsabilidade:
        Exibir formulario de cadastro de novo produto.

    Parametros:
        request: Requisicao HTTP atual.

    Retorno:
        TemplateResponse com o formulario em branco.

    Contexto de uso:
        Entrada de criacao manual do catalogo.
    """

    return templates.TemplateResponse(
        request,
        "add_product.html",
        _with_app_shell(
            request=request,
            active_tab="search",
            context={
                "request": request,
                "page_title": "Novo produto",
                **_build_new_product_form_context(),
                "shelf_options": _build_shelf_options(request),
            },
        ),
    )


@router.post("/products/auto-fill")
async def dashboard_autofill_product_form(request: Request) -> Any:
    """
    Responsabilidade:
        Gerar rascunho de cadastro a partir de uma URL enviada pelo operador.

    Parametros:
        request: Requisicao HTTP atual contendo `last_known_url`.

    Retorno:
        TemplateResponse com o formulario pre-preenchido ou erro explicativo.

    Contexto de uso:
        Reduz friccao do cadastro sem salvar automaticamente dados incertos.
    """

    form_data = await request.form()
    submitted_url = str(form_data.get("last_known_url", "")).strip()
    fetcher = _get_fetcher_service(request)

    if fetcher is None:
        context = _build_new_product_form_context(
            submitted_data={"last_known_url": submitted_url},
            autofill_error_message="O ambiente atual nao possui fetcher configurado para auto-preenchimento.",
        )
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Novo produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
        )

    draft_service = ProductDraftService(fetcher=fetcher, product_store=_get_store_service(request))
    draft_result = draft_service.build_from_url(submitted_url)
    if not draft_result.success or draft_result.draft is None:
        context = _build_new_product_form_context(
            submitted_data={"last_known_url": submitted_url},
            autofill_error_message=draft_result.message,
            autofill_preview={
                "title": draft_result.page_data.title if draft_result.page_data else None,
                "image_url": draft_result.page_data.image_url if draft_result.page_data else None,
                "sku": draft_result.page_data.sku if draft_result.page_data else None,
                "url": draft_result.page_data.url if draft_result.page_data else submitted_url,
            }
            if draft_result.page_data
            else None,
        )
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Novo produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
        )

    submitted_data = {
        "alias": draft_result.draft.alias,
        "brand": draft_result.draft.brand,
        "name": draft_result.draft.name,
        "variant": draft_result.draft.variant,
        "last_known_url": draft_result.draft.last_known_url,
        "last_known_sku": draft_result.draft.last_known_sku,
    }
    context = _build_new_product_form_context(
        submitted_data=submitted_data,
        autofill_message=draft_result.message,
        autofill_preview={
            "title": draft_result.draft.source_title,
            "image_url": draft_result.draft.image_url,
            "sku": draft_result.draft.last_known_sku,
            "url": draft_result.draft.last_known_url,
        },
    )
    return templates.TemplateResponse(
        request,
        "add_product.html",
        _with_app_shell(
            request,
            {"request": request, "page_title": "Novo produto", **context, "shelf_options": _build_shelf_options(request)},
            active_tab="search",
        ),
    )


@router.get("/products/{alias}/edit")
def dashboard_edit_product_form(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Exibir formulario de edicao para um produto ja existente.

    Parametros:
        request: Requisicao HTTP atual.
        alias: Alias do produto que sera editado.

    Retorno:
        TemplateResponse com dados atuais do produto ou erro de ausencia.

    Contexto de uso:
        Permite manutencao segura de alias, URL, SKU e identidade do item.
    """

    product = _get_store_service(request).get_by_alias(alias)
    if product is None:
        return templates.TemplateResponse(
            request,
            "product_detail.html",
            _with_app_shell(
                request=request,
                active_tab="search",
                context={
                    "request": request,
                    "page_title": "Produto nao encontrado",
                    "error_message": "O produto informado nao foi encontrado no catalogo.",
                },
            ),
            status_code=404,
        )

    context = _build_new_product_form_context(
        submitted_data=_build_submitted_data_from_product(product),
        form_mode="edit",
        form_action_url=f"/dashboard/products/{alias}/edit",
        submit_button_label="Salvar alteracoes",
        cancel_url=f"/dashboard/products/{alias}",
    )
    return templates.TemplateResponse(
        request,
        "add_product.html",
        _with_app_shell(
            request=request,
            active_tab="search",
            context={"request": request, "page_title": "Editar produto", **context, "shelf_options": _build_shelf_options(request)},
        ),
    )


@router.get("/products/{alias}")
def dashboard_product_detail(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Renderizar detalhe operacional de um produto com barcode em destaque.

    Parametros:
        request: Requisicao HTTP atual.
        alias: Alias do produto solicitado.

    Retorno:
        TemplateResponse da tela de detalhe.

    Contexto de uso:
        Tela central para confirmacao visual e exibicao do barcode operavel.
    """

    context = _build_product_detail_context(request, alias)
    status_code = 404 if context.get("error_message") else 200
    return templates.TemplateResponse(request, "product_detail.html", context, status_code=status_code)


@router.get("/products/{alias}/barcode")
def dashboard_product_barcode_fullscreen(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Renderizar modo fullscreen de barcode com o minimo de distrações.

    Parametros:
        request: Requisicao HTTP atual.
        alias: Alias do produto solicitado.

    Retorno:
        TemplateResponse da tela scan-ready.

    Contexto de uso:
        Usada em operacao mobile para leitura rapida por scanner.
    """

    context = _build_product_detail_context(request, alias)
    status_code = 404 if context.get("error_message") else 200
    fullscreen_context = _with_app_shell(
        request=request,
        active_tab="search",
        hide_app_chrome=True,
        body_class="barcode-screen-page",
        context=context,
    )
    return templates.TemplateResponse(request, "barcode_fullscreen.html", fullscreen_context, status_code=status_code)


@router.post("/products")
async def dashboard_create_product(request: Request) -> Any:
    """
    Responsabilidade:
        Persistir um novo produto submetido pelo formulario.

    Parametros:
        request: Requisicao HTTP atual contendo dados do formulario.

    Retorno:
        RedirectResponse para a Home em caso de sucesso ou TemplateResponse em erro.

    Contexto de uso:
        Fluxo principal de cadastro manual do catalogo.
    """

    form_data = await request.form()
    submitted_data = _extract_product_form_submission(form_data)

    validation_error = _validate_product_submission(submitted_data)
    if validation_error:
        context = _build_new_product_form_context(submitted_data=submitted_data, error_message=validation_error)
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Novo produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
            status_code=400,
        )

    alias_error = _validate_alias_availability(_get_store_service(request), submitted_data["alias"])
    if alias_error:
        context = _build_new_product_form_context(submitted_data=submitted_data, error_message=alias_error)
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Novo produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
            status_code=400,
        )

    try:
        saved_product = _get_store_service(request).upsert_product(
            _build_product_record_from_submission(submitted_data)
        )
    except (RuntimeError, ValueError) as error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            error_message=f"Nao foi possivel salvar o produto: {error}",
        )
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Novo produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
            status_code=500,
        )

    return RedirectResponse(
        url=f"/dashboard/products/{saved_product.alias}?created=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/products/{alias}/edit")
async def dashboard_edit_product(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Persistir alteracoes de um produto existente, inclusive novo alias.

    Parametros:
        request: Requisicao HTTP atual contendo dados do formulario.
        alias: Alias atual do produto em edicao.

    Retorno:
        RedirectResponse para o detalhe atualizado ou TemplateResponse em erro.

    Contexto de uso:
        Fluxo de manutencao do cadastro operacional.
    """

    existing_product = _get_store_service(request).get_by_alias(alias)
    if existing_product is None:
        return templates.TemplateResponse(
            request,
            "product_detail.html",
            _with_app_shell(
                request=request,
                active_tab="search",
                context={
                    "request": request,
                    "page_title": "Produto nao encontrado",
                    "error_message": "O produto informado nao foi encontrado no catalogo.",
                },
            ),
            status_code=404,
        )

    form_data = await request.form()
    submitted_data = _extract_product_form_submission(form_data)

    validation_error = _validate_product_submission(submitted_data)
    if validation_error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            error_message=validation_error,
            form_mode="edit",
            form_action_url=f"/dashboard/products/{alias}/edit",
            submit_button_label="Salvar alteracoes",
            cancel_url=f"/dashboard/products/{alias}",
        )
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Editar produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
            status_code=400,
        )

    alias_error = _validate_alias_availability(
        _get_store_service(request),
        desired_alias=submitted_data["alias"],
        current_alias=alias,
    )
    if alias_error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            error_message=alias_error,
            form_mode="edit",
            form_action_url=f"/dashboard/products/{alias}/edit",
            submit_button_label="Salvar alteracoes",
            cancel_url=f"/dashboard/products/{alias}",
        )
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Editar produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
            status_code=400,
        )

    try:
        updated_product = _get_store_service(request).replace_product(
            current_alias=alias,
            updated_product=_build_product_record_from_submission(submitted_data),
        )
    except (RuntimeError, ValueError) as error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            error_message=f"Nao foi possivel salvar as alteracoes: {error}",
            form_mode="edit",
            form_action_url=f"/dashboard/products/{alias}/edit",
            submit_button_label="Salvar alteracoes",
            cancel_url=f"/dashboard/products/{alias}",
        )
        return templates.TemplateResponse(
            request,
            "add_product.html",
            _with_app_shell(
                request,
                {"request": request, "page_title": "Editar produto", **context, "shelf_options": _build_shelf_options(request)},
                active_tab="search",
            ),
            status_code=500,
        )

    return RedirectResponse(
        url=f"/dashboard/products/{updated_product.alias}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/products/{alias}/delete")
def dashboard_delete_product(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Excluir um produto do catalogo e limpar estados auxiliares relacionados.

    Parametros:
        request: Requisicao HTTP atual.
        alias: Alias do produto que deve ser removido pelo operador.

    Retorno:
        RedirectResponse para a tela inicial em caso de sucesso ou
        TemplateResponse 404 quando o produto nao existir.

    Contexto de uso:
        Acao administrativa do dashboard para manutencao do catalogo fisico
        sem precisar editar manualmente o arquivo de armazenamento.
    """

    store_service = _get_store_service(request)
    existing_product = store_service.get_by_alias(alias)
    if existing_product is None:
        return templates.TemplateResponse(
            request,
            "product_detail.html",
            _with_app_shell(
                request=request,
                active_tab="search",
                context={
                    "request": request,
                    "page_title": "Produto nao encontrado",
                    "error_message": "O produto informado nao foi encontrado no catalogo.",
                },
            ),
            status_code=404,
        )

    removed_product = store_service.delete_product(alias)
    _get_saved_service(request).unsave_alias(removed_product.alias)
    last_update_by_alias.pop(removed_product.alias, None)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/products/{alias}/update")
def dashboard_update_product(request: Request, alias: str) -> RedirectResponse:
    """
    Responsabilidade:
        Executar update manual de um produto e guardar feedback para a UI.

    Parametros:
        request: Requisicao HTTP atual.
        alias: Alias do produto que deve ser reprocessado.

    Retorno:
        RedirectResponse para o detalhe do produto apos a tentativa.

    Contexto de uso:
        Acao operacional primaria da tela de detalhe e dos cards.
    """

    resolve_result = _get_resolver_service(request).resolve_sku_for_alias(alias)
    last_update_by_alias[alias] = _build_update_snapshot(resolve_result)
    return RedirectResponse(url=f"/dashboard/products/{alias}", status_code=status.HTTP_303_SEE_OTHER)
