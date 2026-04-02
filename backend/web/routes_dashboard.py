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

from fastapi import APIRouter, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.models.product import ProductRecord
from backend.models.sku_event import SkuEvent
from backend.services.curated_renner_import_service import (
    CuratedRennerImportService,
    resolve_builtin_curated_seed_file,
)
from backend.services.internal_catalog_seed_service import (
    InternalCatalogSeedService,
    resolve_builtin_internal_catalog_seed_file,
)
from backend.services.matcher import normalize_text, normalize_variant
from backend.services.shelf_banner_service import ShelfBannerService
from backend.services.product_draft_service import ProductDraftService
from backend.services.product_group_service import GroupedParentProduct, ProductGroupService
from backend.services.product_preview_service import ProductPreview, ProductPreviewService
from backend.services.shelf_service import ShelfPlacement, ShelfService
from backend.services.storage_path_service import resolve_default_data_file
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver, ResolveResult
from backend.services.saved_product_service import SavedProductService
from backend.services.uploaded_image_service import UploadedImageService, resolve_uploaded_images_directory
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


def _get_uploaded_image_service(request: Request) -> UploadedImageService:
    """
    Responsabilidade:
        Recuperar ou inicializar o serviço de uploads persistentes do catálogo.

    Parâmetros:
        request: Requisição HTTP atual com acesso ao `app.state`.

    Retorno:
        UploadedImageService compartilhado pela interface web.

    Contexto de uso:
        Usado pelos fluxos de cadastro manual e edição para salvar imagens
        tiradas do celular ou escolhidas da galeria sem depender do site.
    """

    cached_service = getattr(request.app.state, "uploaded_image_service", None)
    if isinstance(cached_service, UploadedImageService):
        return cached_service

    initialized_service = UploadedImageService(
        storage_directory=resolve_uploaded_images_directory(),
    )
    request.app.state.uploaded_image_service = initialized_service
    return initialized_service


def _migrate_auxiliary_alias_references(
    request: Request,
    previous_alias: str,
    updated_alias: str,
) -> None:
    """
    Responsabilidade:
        Migrar referencias auxiliares quando um produto muda de alias.

    Parametros:
        request: Requisicao HTTP atual com acesso aos services compartilhados.
        previous_alias: Alias antigo antes da edicao.
        updated_alias: Novo alias persistido para o mesmo produto.

    Retorno:
        Nenhum.

    Contexto de uso:
        Mantem salvos e historico conectados ao item correto depois que o
        operador renomeia um produto no dashboard.
    """

    normalized_previous_alias = str(previous_alias).strip()
    normalized_updated_alias = str(updated_alias).strip()
    if not normalized_previous_alias or not normalized_updated_alias:
        return

    if normalized_previous_alias == normalized_updated_alias:
        return

    _get_saved_service(request).replace_alias(
        old_alias=normalized_previous_alias,
        new_alias=normalized_updated_alias,
    )
    _get_history_store(request).replace_alias(
        old_alias=normalized_previous_alias,
        new_alias=normalized_updated_alias,
    )


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
        "internal_import_actions": _build_internal_import_actions(),
    }


def _build_internal_import_actions() -> List[Dict[str, str]]:
    """
    Responsabilidade:
        Concentrar os atalhos administrativos de importacao interna da loja.

    Parametros:
        Nenhum.

    Retorno:
        Lista de acoes POST com rotulo curto e rota correspondente.

    Contexto de uso:
        A Home precisa priorizar busca e prateleiras. Ao concentrar esses
        atalhos no menu global do botao `+`, mantemos a operacao administrativa
        acessivel sem competir com o fluxo principal de leitura de codigo.
    """

    return [
        {
            "label": "Importar prateleira 02",
            "href": "/dashboard/imports/prestige-shelf-02",
        },
        {
            "label": "Importar prateleira 01",
            "href": "/dashboard/imports/prestige-shelf-01",
        },
    ]


def _build_new_product_form_context(
    submitted_data: Optional[Dict[str, str]] = None,
    manual_variant_rows: Optional[List[Dict[str, Any]]] = None,
    error_message: Optional[str] = None,
    autofill_message: Optional[str] = None,
    autofill_error_message: Optional[str] = None,
    autofill_preview: Optional[Dict[str, Any]] = None,
    form_mode: str = "create",
    form_action_url: str = "/dashboard/products",
    submit_button_label: str = "Salvar produto",
    cancel_url: str = "/dashboard",
    allows_site_variants: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Padronizar contexto da tela de formulario de produto.

    Parametros:
        submitted_data: Valores atuais do formulario para re-renderizacao.
        manual_variant_rows: Variantes manuais exibidas no formulario.
        error_message: Mensagem de erro de validacao final.
        autofill_message: Feedback de sucesso do auto-preenchimento.
        autofill_error_message: Feedback de falha do auto-preenchimento.
        autofill_preview: Dados auxiliares extraidos da pagina.
        form_mode: Modo do formulario (`create` ou `edit`).
        form_action_url: Endpoint que recebera o submit principal.
        submit_button_label: Texto do botao principal.
        cancel_url: Destino do CTA secundario de cancelamento.
        allows_site_variants: Define se a UI deve permitir lote de variantes
            mesmo quando a origem atual for `site`.

    Retorno:
        Dicionario compativel com `add_product.html`.

    Contexto de uso:
        Reutilizado pelos fluxos de criacao, auto-preenchimento e edicao.
    """

    return {
        "error_message": error_message,
        "submitted_data": submitted_data or {},
        "manual_variant_rows": manual_variant_rows
        or [
            {
                "alias": "",
                "label": "",
                "code": "",
                "site_url": "",
                "stock_qty": "0",
                "notes": "",
            }
        ],
        "autofill_message": autofill_message,
        "autofill_error_message": autofill_error_message,
        "autofill_preview": autofill_preview,
        "form_mode": form_mode,
        "form_action_url": form_action_url,
        "submit_button_label": submit_button_label,
        "cancel_url": cancel_url,
        "allows_site_variants": (form_mode != "edit") if allows_site_variants is None else allows_site_variants,
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
        "source_type": product.source_type,
        "concentration": product.concentration,
        "shelf_reference_label": product.shelf_reference_label,
        "notes": product.notes,
        "image_url": product.image_url,
        "stock_qty": str(product.stock_qty),
        "variant_notes": product.variant_notes,
        "is_active": "1" if product.is_active else "0",
        "shelf_number": str(product.shelf_number or ""),
        "display_order": str(product.display_order or ""),
    }


def _build_safe_alias_fragment(raw_value: str) -> str:
    """
    Responsabilidade:
        Transformar texto livre em fragmento seguro para composição de alias.

    Parametros:
        raw_value: Texto bruto vindo do formulário manual.

    Retorno:
        Fragmento enxuto, em snake_case, pronto para compor aliases únicos.

    Contexto de uso:
        Reutilizado na criação manual de variantes para evitar aliases gigantes
        ou inconsistentes quando o operador adiciona volumes dinamicamente.
    """

    normalized_value = normalize_text(raw_value).replace(" ", "_").strip("_")
    return normalized_value


def _build_default_parent_reference(submitted_data: Dict[str, str]) -> str:
    """
    Responsabilidade:
        Definir o identificador pai estável usado pelo agrupamento interno.

    Parametros:
        submitted_data: Payload principal já normalizado do formulário.

    Retorno:
        String estável para unir variantes do mesmo perfume manual.

    Contexto de uso:
        Permite que múltiplas variantes manuais compartilhem o mesmo produto
        pai sem depender de URL do site ou SKU de página.
    """

    alias_fragment = _build_safe_alias_fragment(submitted_data.get("alias", ""))
    if alias_fragment:
        return alias_fragment

    composed_reference = " ".join(
        [
            submitted_data.get("brand", ""),
            submitted_data.get("name", ""),
            submitted_data.get("concentration", ""),
        ]
    )
    return _build_safe_alias_fragment(composed_reference) or "produto-manual"


def _normalize_uploaded_file(raw_value: Any) -> UploadFile | None:
    """
    Responsabilidade:
        Validar se um valor do formulário realmente representa um upload útil.

    Parametros:
        raw_value: Valor bruto vindo de `form_data.get` ou `form_data.getlist`.

    Retorno:
        UploadFile quando houver arquivo enviado; caso contrário, None.

    Contexto de uso:
        Evita que campos vazios de input file sejam tratados como imagens reais
        durante a criação manual com câmera ou galeria.
    """

    # Decisao tecnica:
    # O objeto retornado por `await request.form()` costuma ser a classe de
    # upload do Starlette. Em algumas execucoes ela nao passa em `isinstance`
    # contra `fastapi.UploadFile`, mesmo sendo um upload valido. Aceitamos as
    # duas classes para evitar que a imagem seja descartada silenciosamente.
    if not isinstance(raw_value, (UploadFile, StarletteUploadFile)):
        return None

    if not str(raw_value.filename or "").strip():
        return None

    return raw_value


def _extract_manual_variant_submissions(form_data: Any) -> List[Dict[str, Any]]:
    """
    Responsabilidade:
        Consolidar as linhas de variantes manuais enviadas pelo formulário.

    Parametros:
        form_data: Estrutura retornada por `await request.form()`.

    Retorno:
        Lista de dicionários, um por variante preenchida pelo operador.

    Contexto de uso:
        Mantém a lógica de variantes fora das rotas, permitindo criar um lote
        de `ProductRecord` a partir de inputs repetidos no cadastro manual.
    """

    variant_labels = [str(item).strip() for item in form_data.getlist("manual_variant_label")]
    variant_codes = [str(item).strip() for item in form_data.getlist("manual_variant_code")]
    variant_site_urls = [str(item).strip() for item in form_data.getlist("manual_variant_site_url")]
    variant_stocks = [str(item).strip() for item in form_data.getlist("manual_variant_stock_qty")]
    variant_notes = [str(item).strip() for item in form_data.getlist("manual_variant_notes")]
    variant_aliases = [str(item).strip() for item in form_data.getlist("manual_variant_alias")]
    raw_variant_files = list(form_data.getlist("manual_variant_image"))

    max_row_count = max(
        len(variant_labels),
        len(variant_codes),
        len(variant_site_urls),
        len(variant_stocks),
        len(variant_notes),
        len(variant_aliases),
        len(raw_variant_files),
        0,
    )

    variant_rows: List[Dict[str, Any]] = []
    for row_index in range(max_row_count):
        row_label = variant_labels[row_index] if row_index < len(variant_labels) else ""
        row_code = variant_codes[row_index] if row_index < len(variant_codes) else ""
        row_site_url = variant_site_urls[row_index] if row_index < len(variant_site_urls) else ""
        row_stock_qty = variant_stocks[row_index] if row_index < len(variant_stocks) else ""
        row_notes = variant_notes[row_index] if row_index < len(variant_notes) else ""
        row_alias = variant_aliases[row_index] if row_index < len(variant_aliases) else ""
        row_file = raw_variant_files[row_index] if row_index < len(raw_variant_files) else None

        if not any([row_label, row_code, row_site_url, row_stock_qty, row_notes, row_alias, _normalize_uploaded_file(row_file)]):
            continue

        variant_rows.append(
            {
                "label": row_label,
                "code": row_code,
                "site_url": row_site_url,
                "stock_qty": row_stock_qty,
                "notes": row_notes,
                "alias": row_alias,
                "image_file": _normalize_uploaded_file(row_file),
            }
        )

    return variant_rows


def _normalize_single_manual_variant_for_edit(
    submitted_data: Dict[str, str],
    manual_variants: List[Dict[str, Any]],
    fallback_alias: str,
) -> tuple[Dict[str, str], List[Dict[str, Any]]]:
    """
    Responsabilidade:
        Tornar a linha visível de variante manual a fonte da verdade na edição.

    Parametros:
        submitted_data: Payload principal extraído do formulário HTML.
        manual_variants: Linhas repetidas enviadas pela seção de variantes.
        fallback_alias: Alias atual da variante em edição usado como segurança.

    Retorno:
        Tupla com o payload principal ajustado e a lista normalizada de variantes.

    Contexto de uso:
        A tela de edição manual reaproveita o mesmo formulário do cadastro,
        então ainda existem campos "simples" escondidos no HTML. Sem esta
        normalização, esses campos ocultos podem sobrescrever a variante
        realmente editada, fazendo a segunda variante virar cópia da primeira.
    """

    normalized_source_type = str(submitted_data.get("source_type", "site")).strip().lower()
    if normalized_source_type not in {"manual", "legacy"}:
        return submitted_data, manual_variants

    if not manual_variants:
        fallback_row = {
            "alias": submitted_data.get("alias", fallback_alias),
            "label": submitted_data.get("variant", ""),
            "code": submitted_data.get("last_known_sku", ""),
            "site_url": submitted_data.get("last_known_url", ""),
            "stock_qty": submitted_data.get("stock_qty", "0"),
            "notes": submitted_data.get("variant_notes", ""),
            "image_file": None,
        }
        return submitted_data, [fallback_row]

    primary_variant_row = manual_variants[0]
    normalized_variant_row = {
        "alias": str(primary_variant_row.get("alias") or submitted_data.get("alias") or fallback_alias).strip(),
        "label": str(primary_variant_row.get("label", "")).strip(),
        "code": str(primary_variant_row.get("code", "")).strip(),
        "site_url": str(primary_variant_row.get("site_url", "")).strip(),
        "stock_qty": _normalize_optional_numeric_text(primary_variant_row.get("stock_qty")) or "0",
        "notes": str(primary_variant_row.get("notes", "")).strip(),
        "image_file": primary_variant_row.get("image_file"),
    }

    normalized_submission = {
        **submitted_data,
        "alias": normalized_variant_row["alias"] or fallback_alias,
        "variant": normalized_variant_row["label"],
        "last_known_sku": normalized_variant_row["code"] or submitted_data.get("last_known_sku", ""),
        "stock_qty": normalized_variant_row["stock_qty"],
        "variant_notes": normalized_variant_row["notes"],
    }
    return normalized_submission, [normalized_variant_row]


def _build_single_manual_variant_row(
    submitted_data: Dict[str, str],
    fallback_alias: str,
) -> List[Dict[str, str]]:
    """
    Responsabilidade:
        Montar a linha única de variante usada no formulário de edição manual.

    Parametros:
        submitted_data: Dados já normalizados que devem repopular o formulário.
        fallback_alias: Alias atual preservado quando o payload ainda estiver vazio.

    Retorno:
        Lista com uma única linha no formato esperado pelo template.

    Contexto de uso:
        Centraliza a reconstrução do formulário em cenários de erro de edição,
        evitando divergência entre o que o operador vê e o que o backend salva.
    """

    return [
        {
            "alias": submitted_data.get("alias", fallback_alias),
            "label": submitted_data.get("variant", ""),
            "code": submitted_data.get("last_known_sku", ""),
            "site_url": submitted_data.get("last_known_url", ""),
            "stock_qty": submitted_data.get("stock_qty", "0"),
            "notes": submitted_data.get("variant_notes", ""),
        }
    ]


def _build_manual_variant_rows_from_group(
    grouped_product: GroupedParentProduct,
) -> List[Dict[str, str]]:
    """
    Responsabilidade:
        Converter um grupo de variantes em linhas prontas para o formulário.

    Parametros:
        grouped_product: Produto pai agrupado com todas as variantes atuais.

    Retorno:
        Lista de dicionarios compatível com a seção repetível do template.

    Contexto de uso:
        Permite que a edição carregue o perfume inteiro, e não apenas a
        variante aberta, destravando manutenção de volumes adicionais.
    """

    return [
        {
            "alias": grouped_variant.alias,
            "label": grouped_variant.product.variant,
            "code": grouped_variant.product.last_known_sku,
            "site_url": grouped_variant.product.last_known_url,
            "stock_qty": str(grouped_variant.product.stock_qty),
            "notes": grouped_variant.product.variant_notes,
        }
        for grouped_variant in grouped_product.variants
    ]


def _resolve_variant_site_url(
    submitted_data: Dict[str, str],
    variant_row: Dict[str, Any],
    current_variant_product: ProductRecord | None = None,
) -> str:
    """
    Responsabilidade:
        Resolver a URL efetiva de sincronizacao para uma variante do site.

    Parametros:
        submitted_data: Dados principais do formulario, usados como fallback.
        variant_row: Linha atual de variante preenchida pelo operador.
        current_variant_product: Produto ja persistido da mesma variante em
            cenarios de edicao, usado para preservar a URL anterior.

    Retorno:
        URL final que deve ficar vinculada a variante.

    Contexto de uso:
        Alguns perfumes da Renner possuem cada ml em paginas separadas. Ao
        persistir a URL por linha, o botao `Atualizar agora` deixa de puxar a
        pagina errada e de quebrar as outras variantes do grupo.
    """

    row_level_site_url = str(variant_row.get("site_url", "")).strip()
    if row_level_site_url:
        return row_level_site_url

    if current_variant_product is not None and current_variant_product.last_known_url.strip():
        return current_variant_product.last_known_url.strip()

    return str(submitted_data.get("last_known_url", "")).strip()


def _resolve_group_products_for_alias(
    request: Request,
    product_alias: str,
) -> List[ProductRecord]:
    """
    Responsabilidade:
        Descobrir todas as variantes que pertencem ao mesmo perfume pai.

    Parametros:
        request: Requisicao HTTP atual com acesso ao store e ao agrupador.
        product_alias: Alias da variante usada como ponto de entrada.

    Retorno:
        Lista de ProductRecord do mesmo grupo, mantendo a ordem do agrupamento.

    Contexto de uso:
        Base para formularios de edicao em lote, onde o operador precisa
        enxergar e salvar o conjunto de variantes do perfume.
    """

    all_products = _get_store_service(request).list_products()
    grouped_product = _get_product_group_service(request).get_group_for_alias(all_products, product_alias)
    if grouped_product is None:
        fallback_product = _get_store_service(request).get_by_alias(product_alias)
        return [fallback_product] if fallback_product is not None else []

    return [grouped_variant.product for grouped_variant in grouped_product.variants]


def _ensure_batch_aliases_are_available_for_edit(
    product_store: ProductStoreService,
    products_to_persist: List[ProductRecord],
    allowed_current_aliases: set[str],
) -> Optional[str]:
    """
    Responsabilidade:
        Validar aliases de uma edicao em lote sem bloquear os aliases atuais.

    Parametros:
        product_store: Storage usado para consultar colisões existentes.
        products_to_persist: Lote final de variantes que será salvo.
        allowed_current_aliases: Aliases que já pertencem ao grupo em edição.

    Retorno:
        Mensagem de erro quando houver colisão; caso contrário, None.

    Contexto de uso:
        A edição do grupo pode manter aliases antigos, remover linhas e criar
        novas variantes. Esta validação precisa aceitar os aliases do próprio
        grupo sem liberar colisões com produtos de fora.
    """

    seen_aliases: set[str] = set()
    for product in products_to_persist:
        normalized_alias = product.alias.strip()
        if normalized_alias in seen_aliases:
            return f"O alias '{normalized_alias}' foi repetido no lote de variantes."
        seen_aliases.add(normalized_alias)

        existing_product = product_store.get_by_alias(normalized_alias)
        if existing_product is None:
            continue

        if existing_product.alias in allowed_current_aliases:
            continue

        return f"Ja existe um produto cadastrado com o alias '{normalized_alias}'."

    return None


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
            "source_type",
            "concentration",
            "shelf_reference_label",
            "notes",
            "image_url",
            "stock_qty",
            "variant_notes",
        ]
    }
    submitted_data["shelf_number"] = _normalize_optional_numeric_text(form_data.get("shelf_number"))
    submitted_data["display_order"] = _normalize_optional_numeric_text(form_data.get("display_order"))
    submitted_data["source_type"] = submitted_data["source_type"] or "site"
    submitted_data["stock_qty"] = _normalize_optional_numeric_text(form_data.get("stock_qty")) or "0"
    submitted_data["is_active"] = "1" if str(form_data.get("is_active", "1")).strip() not in {"0", "false", "off"} else "0"
    submitted_data["last_known_sku"] = submitted_data["last_known_sku"] or "unknown"
    return submitted_data


def _resolve_image_url_for_edit_submission(
    request: Request,
    existing_product: ProductRecord,
    submitted_data: Dict[str, str],
    product_image_file: UploadFile | None,
) -> str:
    """
    Responsabilidade:
        Definir qual imagem deve ser persistida ao editar um produto existente.

    Parametros:
        request: Requisicao HTTP atual para acessar uploads e previews.
        existing_product: Produto persistido antes da edicao.
        submitted_data: Payload atual do formulario ja normalizado.
        product_image_file: Upload enviado explicitamente pelo operador.

    Retorno:
        URL final da imagem que deve ficar gravada no cadastro.

    Contexto de uso:
        Evita que um produto perca a imagem ao sair do fluxo do site para
        `manual` ou `legacy`. Nesses casos, se a UI estava usando apenas o
        preview visual do site, promovemos essa imagem para `image_url`
        persistida antes de salvar a edicao.
    """

    if product_image_file is not None:
        return _get_uploaded_image_service(request).save_uploaded_file(
            product_image_file,
            product_alias=submitted_data.get("alias", existing_product.alias),
            variant_label=submitted_data.get("variant", ""),
        )

    submitted_image_url = str(submitted_data.get("image_url", "")).strip()
    if submitted_image_url:
        return submitted_image_url

    if existing_product.image_url:
        return existing_product.image_url

    normalized_source_type = str(submitted_data.get("source_type", existing_product.source_type)).strip().lower()
    if normalized_source_type not in {"manual", "legacy"}:
        return ""

    preview_service = _get_preview_service(request)
    if preview_service is None:
        return ""

    cached_preview = preview_service.get_cached_preview(existing_product)
    if cached_preview is None:
        cached_preview = preview_service.ensure_preview(existing_product)

    if cached_preview is None:
        return ""

    return str(cached_preview.image_url or "").strip()


def _build_group_products_for_edit_submission(
    request: Request,
    submitted_data: Dict[str, str],
    manual_variants: List[Dict[str, Any]],
    current_group_products: List[ProductRecord],
    product_image_file: UploadFile | None,
) -> List[ProductRecord]:
    """
    Responsabilidade:
        Transformar a edição em lote de um perfume no conjunto final de variantes.

    Parametros:
        request: Requisicao HTTP atual para uploads e resolução de preview.
        submitted_data: Dados comuns do formulário aplicados ao grupo inteiro.
        manual_variants: Linhas visíveis da seção de variantes.
        current_group_products: Variantes atualmente persistidas para o grupo.
        product_image_file: Upload geral do produto usado como fallback visual.

    Retorno:
        Lista de ProductRecord pronta para substituir/adicionar variantes.

    Contexto de uso:
        Dá suporte à manutenção real de perfumes com múltiplos volumes sem
        desmontar o modelo atual em que cada variante ainda é uma linha plana.
    """

    if not current_group_products:
        return _build_product_records_from_submission(
            request=request,
            submitted_data=submitted_data,
            manual_variants=manual_variants,
            product_image_file=product_image_file,
        )

    existing_products_by_alias = {product.alias: product for product in current_group_products}
    anchor_product = existing_products_by_alias.get(submitted_data.get("alias", "")) or current_group_products[0]
    group_parent_reference = next(
        (product.parent_reference for product in current_group_products if product.parent_reference),
        "",
    ) or _build_default_parent_reference(submitted_data)
    group_base_alias = group_parent_reference or anchor_product.alias or submitted_data.get("alias", "")
    product_level_image_url = _resolve_image_url_for_edit_submission(
        request=request,
        existing_product=anchor_product,
        submitted_data=submitted_data,
        product_image_file=product_image_file,
    )

    normalized_variant_rows = manual_variants or [
        {
            "alias": anchor_product.alias,
            "label": submitted_data.get("variant", ""),
            "code": submitted_data.get("last_known_sku", ""),
            "site_url": submitted_data.get("last_known_url", ""),
            "stock_qty": submitted_data.get("stock_qty", "0"),
            "notes": submitted_data.get("variant_notes", ""),
            "image_file": None,
        }
    ]

    products_to_persist: List[ProductRecord] = []
    for row_index, variant_row in enumerate(normalized_variant_rows):
        current_variant_alias = str(variant_row.get("alias", "")).strip()
        current_variant_product = existing_products_by_alias.get(current_variant_alias)
        variant_image_url = current_variant_product.image_url if current_variant_product is not None else product_level_image_url
        variant_image_file = variant_row.get("image_file")
        if variant_image_file is not None:
            variant_image_url = _get_uploaded_image_service(request).save_uploaded_file(
                variant_image_file,
                product_alias=group_base_alias,
                variant_label=str(variant_row.get("label", "")),
            )
        elif not variant_image_url:
            variant_image_url = product_level_image_url

        variant_submission = {
            **submitted_data,
            "alias": current_variant_alias
            or _build_manual_variant_alias(
                base_alias=group_base_alias,
                variant_label=str(variant_row.get("label", "")),
                row_index=row_index,
            ),
            "variant": str(variant_row.get("label", "")).strip(),
            "last_known_sku": str(variant_row.get("code", "")).strip(),
            "stock_qty": _normalize_optional_numeric_text(variant_row.get("stock_qty")) or "0",
            "variant_notes": str(variant_row.get("notes", "")).strip(),
            "image_url": variant_image_url,
            "last_known_url": _resolve_variant_site_url(
                submitted_data=submitted_data,
                variant_row=variant_row,
                current_variant_product=current_variant_product,
            ),
            "parent_reference": group_parent_reference,
        }
        products_to_persist.append(_build_product_record_from_submission(variant_submission))

    return products_to_persist


def _persist_group_edit_submission(
    request: Request,
    current_group_products: List[ProductRecord],
    products_to_persist: List[ProductRecord],
    preferred_alias: str = "",
) -> ProductRecord:
    """
    Responsabilidade:
        Aplicar a edição em lote do grupo, incluindo adição e remoção de variantes.

    Parametros:
        request: Requisicao HTTP atual para acessar store e estados auxiliares.
        current_group_products: Variantes atualmente salvas para o perfume pai.
        products_to_persist: Lote final gerado a partir do formulário.
        preferred_alias: Alias que deve ser priorizado no retorno final.

    Retorno:
        Primeiro ProductRecord persistido do lote, usado como destino do redirect.

    Contexto de uso:
        Mantém o contrato atual do storage por variante, mas permite que a UI
        trate a manutenção do perfume como uma operação única por grupo.
    """

    store_service = _get_store_service(request)
    current_products_by_alias = {product.alias: product for product in current_group_products}
    persisted_products: List[ProductRecord] = []

    for product_to_persist in products_to_persist:
        if product_to_persist.alias in current_products_by_alias:
            persisted_product = store_service.replace_product(
                current_alias=product_to_persist.alias,
                updated_product=product_to_persist,
            )
        else:
            persisted_product = store_service.upsert_product(product_to_persist)
        persisted_products.append(persisted_product)

    persisted_aliases = {product.alias for product in products_to_persist}
    aliases_to_remove = [
        current_product.alias
        for current_product in current_group_products
        if current_product.alias not in persisted_aliases
    ]
    for removed_alias in aliases_to_remove:
        removed_product = store_service.delete_product(removed_alias)
        _get_saved_service(request).unsave_alias(removed_product.alias)
        last_update_by_alias.pop(removed_product.alias, None)

    normalized_preferred_alias = preferred_alias.strip()
    if normalized_preferred_alias:
        for persisted_product in persisted_products:
            if persisted_product.alias == normalized_preferred_alias:
                return persisted_product

    return persisted_products[0]


def _validate_product_submission(
    submitted_data: Dict[str, str],
    manual_variants: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    Responsabilidade:
        Validar os campos minimos para persistencia confiavel do produto.

    Parametros:
        submitted_data: Payload ja normalizado vindo do formulario HTML.
        manual_variants: Variantes extras enviadas no fluxo manual.

    Retorno:
        Mensagem de erro quando houver dado invalido; caso contrario, None.

    Contexto de uso:
        Evita gravacoes inconsistentes ou invisiveis na UI, como alias vazio ou
        URL ausente, que poderiam dar a impressao de cadastro bem-sucedido.
    """

    manual_variants = manual_variants or []
    required_fields = {
        "alias": "Informe um alias para identificar o produto.",
        "brand": "Informe a marca do produto.",
        "name": "Informe o nome do produto.",
    }
    for field_name, error_message in required_fields.items():
        if not str(submitted_data.get(field_name, "")).strip():
            return error_message

    source_type = str(submitted_data.get("source_type", "site")).strip().lower()
    if source_type == "site" and not str(submitted_data.get("last_known_url", "")).strip():
        return "Informe a URL conhecida do produto."

    if manual_variants:
        for variant_index, variant_row in enumerate(manual_variants, start=1):
            if not variant_row.get("label"):
                return f"Informe o rótulo da variante {variant_index}."
            if not variant_row.get("code"):
                return f"Informe o código da variante {variant_index}."
            raw_variant_stock = str(variant_row.get("stock_qty", "")).strip()
            if raw_variant_stock:
                try:
                    if int(raw_variant_stock) < 0:
                        return f"O estoque da variante {variant_index} não pode ser negativo."
                except ValueError:
                    return f"O estoque da variante {variant_index} precisa ser um número inteiro."

    if source_type in {"manual", "legacy"}:
        if manual_variants:
            pass
        elif not str(submitted_data.get("last_known_sku", "")).strip():
            return "Informe ao menos um código para o cadastro manual."

    if source_type in {"manual", "legacy"}:
        for variant_index, variant_row in enumerate(manual_variants, start=1):
            normalized_variant_code = str(variant_row.get("code", "")).strip().lower()
            if normalized_variant_code in {"", "unknown"}:
                return f"Informe o codigo da variante {variant_index}."

        if not manual_variants and str(submitted_data.get("last_known_sku", "")).strip().lower() in {"", "unknown"}:
            return "Informe ao menos um codigo para o cadastro manual."

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

    raw_stock_qty = str(submitted_data.get("stock_qty", "")).strip()
    if raw_stock_qty:
        try:
            if int(raw_stock_qty) < 0:
                return "O estoque da variante não pode ser negativo."
        except ValueError:
            return "O estoque da variante precisa ser um número inteiro."

    return None


def _is_duplicate_site_variant_row(
    submitted_data: Dict[str, str],
    variant_row: Dict[str, Any],
) -> bool:
    """
    Responsabilidade:
        Detectar quando uma linha adicional repete a variante principal do site.

    Parametros:
        submitted_data: Payload principal do formulário com a variante base.
        variant_row: Linha extra informada na seção de variantes.

    Retorno:
        `True` quando a linha representa a mesma combinação de variante/código
        já presente no bloco principal do produto importado; caso contrário,
        `False`.

    Contexto de uso:
        O auto-preenchimento do site já populariza a variante principal. Ao
        abrir o fluxo de múltiplas variantes no mesmo cadastro, evitamos criar
        uma cópia redundante da primeira linha.
    """

    normalized_primary_label = normalize_variant(submitted_data.get("variant", ""))
    normalized_primary_code = str(submitted_data.get("last_known_sku", "")).strip()
    normalized_row_label = normalize_variant(str(variant_row.get("label", "")))
    normalized_row_code = str(variant_row.get("code", "")).strip()

    if not normalized_row_label and not normalized_row_code:
        return False

    return normalized_row_label == normalized_primary_label and normalized_row_code == normalized_primary_code


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

    parent_reference = submitted_data.get("parent_reference") or _build_default_parent_reference(submitted_data)
    normalized_source_type = str(submitted_data.get("source_type", "site")).strip().lower() or "site"
    normalized_site_link_status = "linked_to_site" if normalized_source_type == "site" else "manual_unlinked"
    normalized_current_code = submitted_data["last_known_sku"]

    return ProductRecord(
        alias=submitted_data["alias"],
        brand=submitted_data["brand"],
        name=submitted_data["name"],
        variant=submitted_data["variant"],
        last_known_url=submitted_data["last_known_url"],
        last_known_sku=submitted_data["last_known_sku"],
        parent_reference=parent_reference,
        source_type=normalized_source_type,
        concentration=submitted_data["concentration"],
        shelf_reference_label=submitted_data["shelf_reference_label"],
        notes=submitted_data["notes"],
        image_url=submitted_data["image_url"],
        stock_qty=int(submitted_data["stock_qty"]) if submitted_data["stock_qty"] else 0,
        variant_notes=submitted_data["variant_notes"],
        is_active=submitted_data.get("is_active", "1") != "0",
        shelf_number=int(submitted_data["shelf_number"]) if submitted_data["shelf_number"] else None,
        display_order=int(submitted_data["display_order"]) if submitted_data["display_order"] else None,
        site_link_status=normalized_site_link_status,
        current_site_code=normalized_current_code if normalized_source_type == "site" else "",
        current_barcode_value=normalized_current_code,
    )


def _build_manual_variant_alias(
    base_alias: str,
    variant_label: str,
    row_index: int,
) -> str:
    """
    Responsabilidade:
        Gerar alias previsível para variantes manuais a partir do alias pai.

    Parâmetros:
        base_alias: Alias base informado para o produto pai.
        variant_label: Rótulo textual da variante, como 50ml ou 100ml.
        row_index: Índice da linha no formulário, usado como fallback estável.

    Retorno:
        Alias único e legível para a variante persistida.

    Contexto de uso:
        Permite criar várias variantes manuais sem obrigar o operador a pensar
        no alias interno de cada uma delas durante o cadastro inicial.
    """

    normalized_base_alias = _build_safe_alias_fragment(base_alias) or "produto"
    normalized_variant_alias = _build_safe_alias_fragment(variant_label)
    if normalized_variant_alias:
        return f"{normalized_base_alias}_{normalized_variant_alias}"
    return f"{normalized_base_alias}_variante_{row_index + 1}"


def _ensure_batch_aliases_are_available(
    product_store: ProductStoreService,
    products_to_persist: List[ProductRecord],
    current_alias: Optional[str] = None,
) -> Optional[str]:
    """
    Responsabilidade:
        Validar colisões de alias considerando um lote inteiro de variantes.

    Parâmetros:
        product_store: Storage consultado para verificar aliases persistidos.
        products_to_persist: Lote de produtos que será salvo de uma vez.
        current_alias: Alias atual permitido no fluxo de edição simples.

    Retorno:
        Mensagem de erro quando houver colisão; caso contrário, None.

    Contexto de uso:
        Impede que o cadastro manual de múltiplas variantes sobrescreva itens
        existentes silenciosamente ou gere aliases duplicados no próprio lote.
    """

    seen_aliases: set[str] = set()
    for product in products_to_persist:
        normalized_alias = product.alias.strip()
        if normalized_alias in seen_aliases:
            return f"O alias '{normalized_alias}' foi repetido no lote de variantes."
        seen_aliases.add(normalized_alias)

        alias_error = _validate_alias_availability(
            product_store=product_store,
            desired_alias=normalized_alias,
            current_alias=current_alias,
        )
        if alias_error:
            return alias_error

    return None


def _build_product_records_from_submission(
    request: Request,
    submitted_data: Dict[str, str],
    manual_variants: List[Dict[str, Any]],
    product_image_file: UploadFile | None,
) -> List[ProductRecord]:
    """
    Responsabilidade:
        Converter o formulário em um lote de ProductRecord persistíveis.

    Parâmetros:
        request: Requisição atual para acesso ao serviço de uploads.
        submitted_data: Payload principal já validado.
        manual_variants: Linhas extras de variantes do cadastro manual.
        product_image_file: Upload geral do produto, usado como fallback visual.

    Retorno:
        Lista de ProductRecord pronta para persistência no storage atual.

    Contexto de uso:
        Reaproveita o modelo plano por variante da aplicação e evita criar um
        segundo formato de persistência apenas para o fluxo manual.
    """

    uploaded_image_service = _get_uploaded_image_service(request)
    product_level_image_url = submitted_data.get("image_url", "")
    if product_image_file is not None:
        product_level_image_url = uploaded_image_service.save_uploaded_file(
            product_image_file,
            product_alias=submitted_data.get("alias", ""),
            variant_label=submitted_data.get("variant", ""),
        )

    source_type = submitted_data.get("source_type", "site")
    parent_reference = _build_default_parent_reference(submitted_data)

    if source_type in {"manual", "legacy"} and manual_variants:
        variant_products: List[ProductRecord] = []
        for row_index, variant_row in enumerate(manual_variants):
            variant_image_url = product_level_image_url
            variant_image_file = variant_row.get("image_file")
            if variant_image_file is not None:
                variant_image_url = uploaded_image_service.save_uploaded_file(
                    variant_image_file,
                    product_alias=submitted_data.get("alias", ""),
                    variant_label=str(variant_row.get("label", "")),
                )

            variant_submission = {
                **submitted_data,
                "alias": variant_row.get("alias") or _build_manual_variant_alias(
                    base_alias=submitted_data.get("alias", ""),
                    variant_label=str(variant_row.get("label", "")),
                    row_index=row_index,
                ),
                "variant": str(variant_row.get("label", "")).strip(),
                "last_known_sku": str(variant_row.get("code", "")).strip(),
                "stock_qty": _normalize_optional_numeric_text(variant_row.get("stock_qty")) or "0",
                "variant_notes": str(variant_row.get("notes", "")).strip(),
                "image_url": variant_image_url,
                "last_known_url": _resolve_variant_site_url(
                    submitted_data=submitted_data,
                    variant_row=variant_row,
                ),
                "parent_reference": parent_reference,
            }
            variant_products.append(_build_product_record_from_submission(variant_submission))

        return variant_products

    if source_type == "site" and manual_variants:
        # Decisao tecnica:
        # No cadastro importado do site, mantemos os campos principais como a
        # variante base sincronizavel e tratamos as linhas adicionais como
        # extensoes do mesmo perfume pai. Isso permite cadastrar 100ml/200ml
        # de uma vez sem obrigar o operador a repetir todo o fluxo.
        site_variant_products: List[ProductRecord] = [
            _build_product_record_from_submission(
                {
                    **submitted_data,
                    "image_url": product_level_image_url,
                    "parent_reference": parent_reference,
                }
            )
        ]

        for row_index, variant_row in enumerate(manual_variants):
            if _is_duplicate_site_variant_row(submitted_data, variant_row):
                continue

            variant_image_url = product_level_image_url
            variant_image_file = variant_row.get("image_file")
            if variant_image_file is not None:
                variant_image_url = uploaded_image_service.save_uploaded_file(
                    variant_image_file,
                    product_alias=submitted_data.get("alias", ""),
                    variant_label=str(variant_row.get("label", "")),
                )

            variant_submission = {
                **submitted_data,
                "alias": variant_row.get("alias") or _build_manual_variant_alias(
                    base_alias=submitted_data.get("alias", ""),
                    variant_label=str(variant_row.get("label", "")),
                    row_index=row_index + 1,
                ),
                "variant": str(variant_row.get("label", "")).strip(),
                "last_known_sku": str(variant_row.get("code", "")).strip(),
                "stock_qty": _normalize_optional_numeric_text(variant_row.get("stock_qty")) or "0",
                "variant_notes": str(variant_row.get("notes", "")).strip(),
                "image_url": variant_image_url,
                "last_known_url": _resolve_variant_site_url(
                    submitted_data=submitted_data,
                    variant_row=variant_row,
                ),
                "parent_reference": parent_reference,
            }
            site_variant_products.append(_build_product_record_from_submission(variant_submission))

        return site_variant_products

    single_variant_submission = {
        **submitted_data,
        "image_url": product_level_image_url,
        "parent_reference": parent_reference,
    }
    return [_build_product_record_from_submission(single_variant_submission)]


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

    preview_map: Dict[str, Optional[ProductPreview]] = {}
    preview_service = _get_preview_service(request)
    fetched_count = 0
    for product in products:
        if product.image_url:
            preview_map[product.alias] = ProductPreview(
                alias=product.alias,
                source_url=product.last_known_url,
                title=product.name,
                image_url=product.image_url,
                cached_at="",
            )
            continue

        if preview_service is None:
            preview_map[product.alias] = None
            continue

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

    if product.site_link_status == "candidate_found":
        return {
            "status_key": "candidate_found",
            "status_tone": "warning",
            "status_label": "Possível correspondência",
            "badge_label": "Revisar vínculo",
            "status_message": "Esse item manual pode ser o mesmo produto que voltou ao site.",
            "timestamp": product.last_matched_at or None,
            "timestamp_label": _format_timestamp_label(product.last_matched_at),
            "is_today": _is_today(product.last_matched_at),
        }

    if product.source_type == "manual" and product.site_link_status != "linked_to_site":
        return {
            "status_key": "manual_catalog",
            "status_tone": "neutral",
            "status_label": "Cadastro interno",
            "badge_label": "Sem sync",
            "status_message": "Produto mantido manualmente no catálogo operacional.",
            "timestamp": None,
            "timestamp_label": "Sem dependência de sync",
            "is_today": False,
        }

    if product.source_type == "legacy" and product.site_link_status != "linked_to_site":
        return {
            "status_key": "legacy_catalog",
            "status_tone": "warning",
            "status_label": "Fora do site",
            "badge_label": "Sem sync",
            "status_message": "Item preservado no catálogo mesmo sem página ativa no site.",
            "timestamp": None,
            "timestamp_label": "Sync desativado",
            "is_today": False,
        }

    if manual_snapshot:
        recorded_at = manual_snapshot.get("recorded_at")
        if manual_snapshot.get("success"):
            return {
                "status_key": "manual_ok",
                "status_tone": "success",
                "status_label": "Atualizado agora",
                "badge_label": "Atualizado",
                "status_message": manual_snapshot.get("message") or "Atualização manual concluída.",
                "timestamp": recorded_at,
                "timestamp_label": _format_timestamp_label(recorded_at),
                "is_today": _is_today(recorded_at),
            }

        return {
            "status_key": "manual_error",
            "status_tone": "error",
            "status_label": "Falha na tentativa",
            "badge_label": "Falha",
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
            "badge_label": "Sem sync",
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
            "badge_label": "Falha",
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
            "badge_label": "Código mudou",
            "status_message": change_description,
            "timestamp": latest_event.timestamp,
            "timestamp_label": _format_timestamp_label(latest_event.timestamp),
            "is_today": _is_today(latest_event.timestamp),
        }

    return {
        "status_key": "synced",
        "status_tone": "success",
        "status_label": "Sincronizado",
        "badge_label": "Sem mudança",
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
    return_query_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar a estrutura enxuta consumida pelos cards de produto.

    Parametros:
        product: Produto persistido.
        preview: Preview visual cached ou recem-buscado.
        activity: Status operacional consolidado do produto.
        is_saved: Indica se o produto esta salvo como atalho.
        return_query_params: Query params opcionais para preservar o contexto
            atual ao abrir detalhe ou barcode a partir de uma lista.

    Retorno:
        Dicionario com campos prontos para os templates de lista.

    Contexto de uso:
        Padroniza exibicao entre Home, Search e Saved.
    """

    variant_summary_parts = [part for part in [product.brand, product.variant] if str(part).strip()]
    detail_href = _append_dashboard_query_params(
        f"/dashboard/products/{product.alias}",
        return_query_params,
    )
    barcode_href = _append_dashboard_query_params(
        f"/dashboard/products/{product.alias}/barcode",
        return_query_params,
    )
    return {
        "alias": product.alias,
        "name": product.name,
        "brand": product.brand,
        "variant": product.variant,
        "concentration": product.concentration,
        "variant_summary": " • ".join(variant_summary_parts) if variant_summary_parts else "Sem variante",
        "sku": product.last_known_sku,
        "url": product.last_known_url,
        "image_url": product.image_url or (preview.image_url if preview and preview.image_url else None),
        "preview_title": preview.title if preview else None,
        "activity": activity,
        "is_saved": is_saved,
        "source_type": product.source_type,
        "source_label": product.source_label,
        "stock_qty": product.stock_qty,
        "is_syncable": product.is_syncable,
        "detail_href": detail_href,
        "barcode_href": barcode_href,
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
        haystack = str(card.get("search_text") or "").lower()
        if not haystack:
            haystack = " ".join(
                [
                    str(card.get("alias", "")),
                    str(card.get("name", "")),
                    str(card.get("brand", "")),
                    str(card.get("variant", "")),
                    str(card.get("sku", "")),
                ]
            ).lower()
        if normalized_query and normalized_query not in haystack:
            continue

        if normalized_brand and str(card.get("brand", "")).lower() != normalized_brand:
            continue

        if normalized_sync_status and str(card.get("activity", {}).get("status_key", "")) != normalized_sync_status:
            continue

        if normalized_updated_scope == "today" and not card.get("activity", {}).get("is_today"):
            continue

        if normalized_updated_scope == "recent" and not card.get("activity", {}).get("timestamp"):
            continue

        if saved_only and not card.get("is_saved"):
            continue

        if image_only and not card.get("image_url"):
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


def _build_search_status_options() -> List[Dict[str, str]]:
    """
    Responsabilidade:
        Centralizar as opções de filtro de status exibidas na busca.

    Parametros:
        Nenhum.

    Retorno:
        Lista de dicionários com `value` e `label` para o select de status.

    Contexto de uso:
        Evita que a UI da busca tenha uma lista manual espalhada pelo template
        e mantém os rótulos operacionais alinhados ao resumo de status da app.
    """

    return [
        {"value": "manual_ok", "label": "Atualizado"},
        {"value": "manual_error", "label": "Falha manual"},
        {"value": "candidate_found", "label": "Revisar vínculo"},
        {"value": "manual_catalog", "label": "Cadastro interno"},
        {"value": "legacy_catalog", "label": "Fora do site"},
        {"value": "changed", "label": "Código mudou"},
        {"value": "failed", "label": "Falha"},
        {"value": "synced", "label": "Sem mudança"},
        {"value": "idle", "label": "Sem sync"},
    ]


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
    saved_aliases: Optional[set[str]] = None,
    return_query_params: Optional[Dict[str, Any]] = None,
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
        saved_aliases: Conjunto opcional com os aliases salvos pelo operador.
        return_query_params: Query params opcionais para preservar contexto
            de origem, como a prateleira aberta antes do detalhe.

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

    is_saved = variant_product.alias in (saved_aliases or set())
    detail_href = _append_dashboard_query_params(
        f"/dashboard/products/{variant_product.alias}",
        return_query_params,
    )
    barcode_href = _append_dashboard_query_params(
        f"/dashboard/products/{variant_product.alias}/barcode",
        return_query_params,
    )

    return {
        "alias": variant_product.alias,
        "label": variant_label,
        "variant_code": variant_product.variant_code,
        "parent_page_sku": grouped_product.parent_page_sku,
        "image_url": variant_product.image_url or (preview.image_url if preview and preview.image_url else None),
        "detail_href": detail_href,
        "barcode_href": barcode_href,
        "update_href": f"/dashboard/products/{variant_product.alias}/update",
        "edit_href": f"/dashboard/products/{variant_product.alias}/edit",
        "delete_href": f"/dashboard/products/{variant_product.alias}/delete",
        "save_href": f"/dashboard/products/{variant_product.alias}/toggle-saved",
        "is_saved": is_saved,
        "save_button_label": "Remover dos salvos" if is_saved else "Salvar",
        "last_known_url": variant_product.last_known_url,
        "status_key": activity["status_key"],
        "status_label": activity.get("badge_label") or activity["status_label"],
        "status_description": activity["status_label"],
        "status_tone": activity["status_tone"],
        "timestamp_label": activity["timestamp_label"],
        "barcode_data_uri": barcode_data_uri,
        "source_type": variant_product.source_type,
        "source_label": variant_product.source_label,
        "site_link_status": variant_product.site_link_status,
        "site_link_status_label": variant_product.site_link_status_label,
        "has_site_candidate": variant_product.has_site_candidate,
        "candidate_confirm_href": f"/dashboard/products/{variant_product.alias}/confirm-site-link",
        "candidate_ignore_href": f"/dashboard/products/{variant_product.alias}/ignore-site-candidate",
        "candidate_code": variant_product.site_candidate_code,
        "candidate_product_id": variant_product.site_candidate_id,
        "candidate_confidence_label": f"{round((variant_product.match_confidence or 0) * 100)}%" if variant_product.match_confidence is not None else "",
        "candidate_signals_text": " • ".join(variant_product.match_signals or []),
        "stock_qty": variant_product.stock_qty,
        "concentration": variant_product.concentration,
        "variant_notes": variant_product.variant_notes,
        "is_syncable": variant_product.is_syncable,
    }


def _build_group_card_support_tags(
    activity: Dict[str, Any],
    stock_qty: int,
    location_label: str = "",
) -> List[str]:
    """
    Responsabilidade:
        Definir os pequenos apoios textuais exibidos no card agrupado.

    Parametros:
        activity: Resumo operacional consolidado da variante selecionada.
        stock_qty: Estoque atual da variante ativa.
        location_label: Texto opcional de localização, usado fora da prateleira.

    Retorno:
        Lista curta de rótulos úteis para escaneabilidade rápida no card.

    Contexto de uso:
        A busca e a prateleira precisam mostrar só o suficiente para orientar
        a bipagem, sem transformar cada card em uma mini tela de detalhe.
    """

    support_tags: List[str] = []
    normalized_location_label = str(location_label).strip()
    if normalized_location_label:
        support_tags.append(normalized_location_label)

    normalized_badge_label = str(activity.get("badge_label") or "").strip()
    status_key = str(activity.get("status_key") or "").strip()
    should_show_status_tag = status_key not in {"idle", "synced"} and bool(normalized_badge_label)
    if should_show_status_tag:
        support_tags.append(normalized_badge_label)

    if stock_qty > 0:
        support_tags.append(f"Estoque {stock_qty}")

    if not support_tags and normalized_badge_label:
        support_tags.append(normalized_badge_label)

    return support_tags


def _build_grouped_catalog_card(
    request: Request,
    grouped_product: GroupedParentProduct,
    preview_map: Dict[str, Optional[ProductPreview]],
    latest_events: Dict[str, SkuEvent],
    saved_aliases: set[str],
    return_query_params: Optional[Dict[str, Any]],
    *,
    variant_storage_prefix: str,
    placement: Optional[ShelfPlacement] = None,
    include_barcode_data_uri: bool = True,
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Montar um card agrupado pronto para busca e prateleira.

    Parametros:
        request: Requisição atual para acesso aos services compartilhados.
        grouped_product: Produto pai com variantes já agrupadas.
        preview_map: Mapa de previews previamente carregados para as variantes.
        latest_events: Último evento conhecido por alias.
        saved_aliases: Conjunto de aliases salvos pelo operador.
        return_query_params: Query params de contexto para detalhe/barcode.
        variant_storage_prefix: Prefixo usado no localStorage da variante ativa.
        placement: Localização física opcional do produto selecionado.
        include_barcode_data_uri: Indica se o card precisa trazer o SVG inline.

    Retorno:
        Dicionário serializável e estável para o template do card agrupado.

    Contexto de uso:
        Evita duplicação entre a busca e a prateleira ao centralizar a regra
        do card semântico "produto pai + variantes + acesso rápido ao código".
    """

    group_service = _get_product_group_service(request)
    selected_variant = group_service.choose_default_variant(grouped_product)
    selected_activity = _build_product_activity(
        selected_variant.product,
        latest_events.get(selected_variant.alias),
        last_update_by_alias.get(selected_variant.alias),
    )

    variant_options: List[Dict[str, Any]] = []
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
                include_barcode_data_uri=include_barcode_data_uri,
                saved_aliases=saved_aliases,
                return_query_params=return_query_params,
            )
        )

    selected_variant_payload = next(
        (
            variant_option
            for variant_option in variant_options
            if variant_option.get("alias") == selected_variant.alias
        ),
        variant_options[0],
    )

    location_label = ""
    if placement is not None:
        location_label = f"Prateleira {placement.shelf_number:02d}"

    return {
        "alias": selected_variant.alias,
        "group_id": grouped_product.group_id,
        "variant_storage_key": f"{variant_storage_prefix}-{grouped_product.group_id}",
        "name": _build_short_product_name(grouped_product.parent_name, grouped_product.brand),
        "brand": grouped_product.brand,
        "variant_code": selected_variant_payload["variant_code"],
        "sku": selected_variant_payload["variant_code"],
        "parent_page_sku": grouped_product.parent_page_sku,
        "image_url": selected_variant_payload["image_url"],
        "barcode_href": selected_variant_payload["barcode_href"],
        "detail_href": selected_variant_payload["detail_href"],
        "status_label": selected_activity.get("badge_label") or selected_activity["status_label"],
        "status_description": selected_activity["status_label"],
        "status_tone": selected_activity["status_tone"],
        "activity": selected_activity,
        "source_label": selected_variant.product.source_label,
        "source_type": selected_variant.product.source_type,
        "stock_qty": selected_variant.product.stock_qty,
        "barcode_data_uri": selected_variant_payload.get("barcode_data_uri"),
        "concentration": selected_variant.product.concentration,
        "is_syncable": selected_variant.product.is_syncable,
        "placement": placement,
        "location_label": location_label,
        "support_tags": _build_group_card_support_tags(
            activity=selected_activity,
            stock_qty=selected_variant.product.stock_qty,
            location_label=location_label,
        ),
        "selected_alias": selected_variant.alias,
        "selected_variant_label": selected_variant.label,
        "variants": variant_options,
        "search_text": _build_group_search_text(grouped_product),
        "is_saved": any(variant_option.get("is_saved") for variant_option in variant_options),
    }


def _append_dashboard_query_params(base_path: str, query_params: Optional[Dict[str, Any]]) -> str:
    """
    Responsabilidade:
        Acrescentar query params de contexto a um caminho interno do dashboard.

    Parametros:
        base_path: Caminho base da rota que recebera os parametros.
        query_params: Dicionario opcional com pares chave/valor serializaveis.

    Retorno:
        URL final com query string estavel quando houver parametros validos.

    Contexto de uso:
        Permite preservar de onde o operador veio, como a prateleira atual,
        para que a tela seguinte consiga oferecer um "voltar" coerente.
    """

    if not query_params:
        return base_path

    normalized_items = {
        str(key): str(value)
        for key, value in query_params.items()
        if value not in (None, "")
    }
    if not normalized_items:
        return base_path

    return f"{base_path}?{urlencode(normalized_items)}"


def _resolve_return_query_params(request: Request, fallback_shelf_number: Optional[int] = None) -> Dict[str, str]:
    """
    Responsabilidade:
        Definir quais parametros de retorno devem acompanhar os links da UI.

    Parametros:
        request: Requisicao atual para inspecionar origem explicitada na URL.
        fallback_shelf_number: Numero da prateleira a ser usado quando a URL
            atual nao trouxer um contexto de origem explicito.

    Retorno:
        Dicionario enxuto com query params usados para reconstruir o retorno.

    Contexto de uso:
        Mantem a experiencia previsivel ao abrir um produto a partir da
        prateleira, sem depender apenas do historico do navegador.
    """

    explicit_return_to = request.query_params.get("return_to", "").strip()
    if explicit_return_to.startswith("/dashboard"):
        return {"return_to": explicit_return_to}

    from_shelf_value = request.query_params.get("from_shelf", "").strip()
    if from_shelf_value.isdigit():
        return {"from_shelf": from_shelf_value}

    current_path = str(request.url.path)
    current_query = str(request.url.query)
    current_dashboard_locations = {
        "/dashboard",
        "/dashboard/search",
        "/dashboard/saved",
    }
    if current_path in current_dashboard_locations or current_path.startswith("/dashboard/prateleiras/"):
        normalized_return_to = current_path if not current_query else f"{current_path}?{current_query}"
        return {"return_to": normalized_return_to}

    if fallback_shelf_number is not None:
        return {"return_to": f"/dashboard/prateleiras/{fallback_shelf_number}"}

    return {}


def _build_back_navigation(
    request: Request,
    *,
    fallback_href: str,
    fallback_label: str,
    shelf_placement: Optional[ShelfPlacement] = None,
) -> Dict[str, str]:
    """
    Responsabilidade:
        Montar o destino de retorno exibido nas telas secundarias do app.

    Parametros:
        request: Requisicao atual, usada para ler um contexto explicito de
            retorno vindo da URL.
        fallback_href: URL usada quando nao houver contexto mais especifico.
        fallback_label: Texto amigavel correspondente ao fallback.
        shelf_placement: Posicao fisica do produto, quando conhecida.

    Retorno:
        Dicionario com `href` e `label` pronto para o template.

    Contexto de uso:
        O fluxo operacional depende de voltar rapidamente para a prateleira
        depois de inspecionar um produto ou abrir o barcode em tela cheia.
    """

    explicit_return_to = request.query_params.get("return_to", "").strip()
    if explicit_return_to.startswith("/dashboard/prateleiras/"):
        shelf_fragment = explicit_return_to.removeprefix("/dashboard/prateleiras/").split("?", maxsplit=1)[0].strip()
        if shelf_fragment.isdigit():
            return {
                "href": explicit_return_to,
                "label": f"Voltar para a prateleira {int(shelf_fragment):02d}",
            }

    if explicit_return_to.startswith("/dashboard/search"):
        return {"href": explicit_return_to, "label": "Voltar para Buscar"}

    if explicit_return_to.startswith("/dashboard/saved"):
        return {"href": explicit_return_to, "label": "Voltar para Salvos"}

    if explicit_return_to == "/dashboard" or explicit_return_to.startswith("/dashboard?"):
        return {"href": explicit_return_to, "label": "Voltar para Início"}

    from_shelf_value = request.query_params.get("from_shelf", "").strip()
    if from_shelf_value.isdigit():
        return {
            "href": f"/dashboard/prateleiras/{from_shelf_value}",
            "label": f"Voltar para a prateleira {int(from_shelf_value):02d}",
        }

    if shelf_placement is not None:
        return {
            "href": f"/dashboard/prateleiras/{shelf_placement.shelf_number}",
            "label": f"Voltar para a prateleira {shelf_placement.shelf_number:02d}",
        }

    return {"href": fallback_href, "label": fallback_label}


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


def _run_builtin_catalog_seed_import(request: Request, seed_name: str) -> tuple[bool, str, int]:
    """
    Responsabilidade:
        Executar um seed interno de catalogo sem depender de validacao remota.

    Parametros:
        request: Requisicao atual para obter o storage compartilhado.
        seed_name: Nome logico do seed interno que deve ser aplicado.

    Retorno:
        Tupla com sucesso, mensagem amigavel e quantidade processada.

    Contexto de uso:
        Permite subir na Railway itens legacy ou fora do site que ja foram
        curados localmente e devem existir no catalogo operacional.
    """

    seed_file_path = resolve_builtin_internal_catalog_seed_file(seed_name)
    import_service = InternalCatalogSeedService(
        product_store=_get_store_service(request),
    )
    products = import_service.load_products_from_file(seed_file_path)
    results = import_service.import_products(products)
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
    return_query_params = _resolve_return_query_params(request, fallback_shelf_number=shelf_number)
    latest_events = _build_latest_event_map(_get_history_store(request).list_events())
    preview_map = _build_preview_map(request, shelf_products, fetch_limit=max(12, len(shelf_products)))
    raw_query_text = request.query_params.get("q", "").strip()
    query_text = raw_query_text.lower()
    selected_brand = request.query_params.get("brand", "").strip()
    shelf_search_reset_href = _append_dashboard_query_params(
        f"/dashboard/prateleiras/{shelf_number}",
        {"brand": selected_brand} if selected_brand else None,
    )
    brand_filters = _build_shelf_brand_filters(
        shelf_number=shelf_number,
        grouped_products=grouped_products,
        query_text=raw_query_text,
        selected_brand=selected_brand,
    )

    shelf_product_cards = []
    saved_aliases = _get_saved_service(request).get_saved_aliases_set()
    for grouped_product in grouped_products:
        if selected_brand and grouped_product.brand != selected_brand:
            continue
        if query_text and query_text not in _build_group_search_text(grouped_product):
            continue

        selected_variant = _get_product_group_service(request).choose_default_variant(grouped_product)
        shelf_product_cards.append(
            _build_grouped_catalog_card(
                request=request,
                grouped_product=grouped_product,
                preview_map=preview_map,
                latest_events=latest_events,
                saved_aliases=saved_aliases,
                return_query_params=return_query_params,
                variant_storage_prefix="shelf",
                placement=shelf_service.get_product_placement(
                    product=selected_variant.product,
                    all_products=products,
                ),
                include_barcode_data_uri=True,
            )
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
            "shelf_search_reset_href": shelf_search_reset_href,
            "back_navigation": {"href": "/dashboard", "label": "Voltar para Início"},
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
    return_query_params = _resolve_return_query_params(request)

    cards = [
        _build_product_card(
            product=product,
            preview=preview_map.get(product.alias),
            activity=_build_product_activity(product, latest_events.get(product.alias), last_update_by_alias.get(product.alias)),
            is_saved=product.alias in saved_aliases,
            return_query_params=return_query_params,
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

    if request.query_params.get("sync_blocked", "") == "1":
        return "Este item nao depende mais da sincronizacao do site."

    if request.query_params.get("site_linked", "") == "1":
        return "Item vinculado ao site com sucesso. A sincronizacao automatica foi retomada."

    if request.query_params.get("site_candidate_ignored", "") == "1":
        return "A sugestao de vinculo foi ignorada e o cadastro interno foi mantido."

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
    grouped_products = _get_product_group_service(request).group_products(products)
    history_events = _get_history_store(request).list_events()
    latest_events = _build_latest_event_map(history_events)
    saved_aliases = saved_service.get_saved_aliases_set()
    preview_map = _build_preview_map(request, products, fetch_limit=12)
    return_query_params = _resolve_return_query_params(request)

    all_cards = [
        _build_grouped_catalog_card(
            request=request,
            grouped_product=grouped_product,
            preview_map=preview_map,
            latest_events=latest_events,
            saved_aliases=saved_aliases,
            return_query_params=return_query_params,
            variant_storage_prefix="search",
            placement=_get_shelf_service(request).get_product_placement(
                product=_get_product_group_service(request).choose_default_variant(grouped_product).product,
                all_products=products,
            ),
            include_barcode_data_uri=True,
        )
        for grouped_product in grouped_products
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
            "available_statuses": _build_search_status_options(),
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
    return_query_params = _resolve_return_query_params(request)

    cards = [
        _build_product_card(
            product=product,
            preview=preview_map.get(product.alias),
            activity=_build_product_activity(product, latest_events.get(product.alias), last_update_by_alias.get(product.alias)),
            is_saved=True,
            return_query_params=return_query_params,
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
    return_query_params = _resolve_return_query_params(request)
    back_navigation = _build_back_navigation(
        request,
        fallback_href="/dashboard/search",
        fallback_label="Voltar para Buscar",
        shelf_placement=shelf_placement,
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
    saved_aliases = _get_saved_service(request).get_saved_aliases_set()
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
                saved_aliases=saved_aliases,
                return_query_params=return_query_params,
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
            "back_navigation": back_navigation,
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


@router.post("/imports/prestige-shelf-09")
def dashboard_import_prestige_shelf_09(request: Request) -> RedirectResponse:
    """
    Responsabilidade:
        Importar no ambiente atual o seed interno da prateleira 09.

    Parametros:
        request: Requisicao HTTP atual com acesso aos servicos compartilhados.

    Retorno:
        RedirectResponse para a Home com feedback de sucesso ou falha.

    Contexto de uso:
        Facilita a carga da prateleira Ralph Lauren na Railway, inclusive para
        produtos legacy que nao dependem mais de pagina ativa no site.
    """

    import_succeeded, import_message, processed_count = _run_builtin_catalog_seed_import(
        request=request,
        seed_name="prestige_shelf_09_catalog",
    )
    query_params = {
        "seed": "prestige-shelf-09",
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


@router.post("/imports/prestige-shelf-02")
def dashboard_import_prestige_shelf_02(request: Request) -> RedirectResponse:
    """
    Responsabilidade:
        Importar no ambiente atual o seed interno da prateleira 02.

    Parametros:
        request: Requisicao HTTP atual com acesso aos servicos compartilhados.

    Retorno:
        RedirectResponse para a Home com feedback de sucesso ou falha.

    Contexto de uso:
        Facilita subir a prateleira com a referencia fisica Azzaro na Railway,
        incluindo itens que hoje dependem de cadastro interno por nao terem
        pagina sincronizavel na Renner ou Ashua.
    """

    import_succeeded, import_message, processed_count = _run_builtin_catalog_seed_import(
        request=request,
        seed_name="prestige_shelf_02_catalog",
    )
    query_params = {
        "seed": "prestige-shelf-02",
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


@router.post("/imports/prestige-shelf-01")
def dashboard_import_prestige_shelf_01(request: Request) -> RedirectResponse:
    """
    Responsabilidade:
        Importar no ambiente atual o seed interno da prateleira 01.

    Parametros:
        request: Requisicao HTTP atual com acesso aos servicos compartilhados.

    Retorno:
        RedirectResponse para a Home com feedback de sucesso ou falha.

    Contexto de uso:
        Facilita subir a prateleira de perfumes arabes na Railway sem depender
        de shell, reaproveitando o mesmo fluxo administrativo das outras seeds
        internas do catalogo.
    """

    import_succeeded, import_message, processed_count = _run_builtin_catalog_seed_import(
        request=request,
        seed_name="prestige_shelf_01_catalog",
    )
    query_params = {
        "seed": "prestige-shelf-01",
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


@router.get("/uploads/{filename}")
def dashboard_uploaded_image(request: Request, filename: str) -> FileResponse:
    """
    Responsabilidade:
        Servir imagens manuais persistidas no storage do catálogo.

    Parâmetros:
        request: Requisição HTTP atual.
        filename: Nome do arquivo solicitado pela interface.

    Retorno:
        FileResponse com a imagem persistida.

    Contexto de uso:
        Permite que fotos enviadas no cadastro manual sejam exibidas em cards,
        detalhe e variantes mesmo estando fora do diretório estático versionado.
    """

    resolved_image_path = _get_uploaded_image_service(request).resolve_public_path(filename)
    if resolved_image_path is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")

    return FileResponse(resolved_image_path)


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
                    **_build_new_product_form_context(
                        submitted_data={"source_type": "site", "stock_qty": "0", "is_active": "1"}
                    ),
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
            manual_variant_rows=[{"alias": "", "label": "", "code": "", "site_url": submitted_url, "stock_qty": "0", "notes": ""}],
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
            manual_variant_rows=[{"alias": "", "label": "", "code": "", "site_url": submitted_url, "stock_qty": "0", "notes": ""}],
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
        "source_type": "site",
        "stock_qty": "0",
        "is_active": "1",
    }
    context = _build_new_product_form_context(
        submitted_data=submitted_data,
        manual_variant_rows=[
            {
                "alias": submitted_data["alias"],
                "label": submitted_data["variant"],
                "code": submitted_data["last_known_sku"],
                "site_url": submitted_data["last_known_url"],
                "stock_qty": "0",
                "notes": "",
            }
        ],
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
    current_group_products = _resolve_group_products_for_alias(request, alias)
    grouped_product = _get_product_group_service(request).get_group_for_alias(
        _get_store_service(request).list_products(),
        alias,
    )
    manual_variant_rows = (
        _build_manual_variant_rows_from_group(grouped_product)
        if grouped_product is not None
        else _build_single_manual_variant_row(_build_submitted_data_from_product(product), alias)
    )
    context = _build_new_product_form_context(
        submitted_data=_build_submitted_data_from_product(product),
        manual_variant_rows=manual_variant_rows,
        form_mode="edit",
        form_action_url=f"/dashboard/products/{alias}/edit",
        submit_button_label="Salvar alteracoes",
        cancel_url=f"/dashboard/products/{alias}",
        allows_site_variants=True if current_group_products else False,
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
    if not context.get("error_message"):
        return_query_params = _resolve_return_query_params(request)
        context["back_navigation"] = _build_back_navigation(
            request,
            fallback_href=_append_dashboard_query_params(f"/dashboard/products/{alias}", return_query_params),
            fallback_label="Voltar para o produto",
            shelf_placement=context.get("shelf_placement"),
        )
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
    manual_variants = _extract_manual_variant_submissions(form_data)
    product_image_file = _normalize_uploaded_file(form_data.get("product_image_file"))

    validation_error = _validate_product_submission(submitted_data, manual_variants)
    if validation_error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            manual_variant_rows=manual_variants,
            error_message=validation_error,
        )
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

    products_to_persist = _build_product_records_from_submission(
        request=request,
        submitted_data=submitted_data,
        manual_variants=manual_variants,
        product_image_file=product_image_file,
    )

    alias_error = _ensure_batch_aliases_are_available(
        _get_store_service(request),
        products_to_persist,
    )
    if alias_error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            manual_variant_rows=manual_variants,
            error_message=alias_error,
        )
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
        saved_product = products_to_persist[0]
        for product_to_persist in products_to_persist:
            persisted_product = _get_store_service(request).upsert_product(product_to_persist)
            if product_to_persist.alias == saved_product.alias:
                saved_product = persisted_product
    except (RuntimeError, ValueError) as error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            manual_variant_rows=manual_variants,
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

    current_group_products = _resolve_group_products_for_alias(request, alias)
    form_data = await request.form()
    submitted_data = _extract_product_form_submission(form_data)
    manual_variants = _extract_manual_variant_submissions(form_data)
    use_group_edit_mode = len(current_group_products) > 1 or len(manual_variants) > 1
    if len(current_group_products) <= 1:
        submitted_data, manual_variants = _normalize_single_manual_variant_for_edit(
            submitted_data=submitted_data,
            manual_variants=manual_variants,
            fallback_alias=alias,
        )
    product_image_file = _normalize_uploaded_file(form_data.get("product_image_file"))

    validation_error = _validate_product_submission(submitted_data, manual_variants)
    if validation_error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            manual_variant_rows=manual_variants or _build_single_manual_variant_row(submitted_data, alias),
            error_message=validation_error,
            form_mode="edit",
            form_action_url=f"/dashboard/products/{alias}/edit",
            submit_button_label="Salvar alteracoes",
            cancel_url=f"/dashboard/products/{alias}",
            allows_site_variants=True,
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

    if use_group_edit_mode:
        products_to_persist = _build_group_products_for_edit_submission(
            request=request,
            submitted_data=submitted_data,
            manual_variants=manual_variants,
            current_group_products=current_group_products or [existing_product],
            product_image_file=product_image_file,
        )
        alias_error = _ensure_batch_aliases_are_available_for_edit(
            product_store=_get_store_service(request),
            products_to_persist=products_to_persist,
            allowed_current_aliases={product.alias for product in current_group_products or [existing_product]},
        )
    else:
        products_to_persist = []
        alias_error = _validate_alias_availability(
            _get_store_service(request),
            desired_alias=submitted_data["alias"],
            current_alias=alias,
        )

    if alias_error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            manual_variant_rows=manual_variants or _build_single_manual_variant_row(submitted_data, alias),
            error_message=alias_error,
            form_mode="edit",
            form_action_url=f"/dashboard/products/{alias}/edit",
            submit_button_label="Salvar alteracoes",
            cancel_url=f"/dashboard/products/{alias}",
            allows_site_variants=True,
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
        if products_to_persist:
            updated_product = _persist_group_edit_submission(
                request=request,
                current_group_products=current_group_products or [existing_product],
                products_to_persist=products_to_persist,
                preferred_alias=alias,
            )
        else:
            submitted_data["image_url"] = _resolve_image_url_for_edit_submission(
                request=request,
                existing_product=existing_product,
                submitted_data=submitted_data,
                product_image_file=product_image_file,
            )

            submitted_data["parent_reference"] = existing_product.parent_reference or _build_default_parent_reference(submitted_data)
            submitted_data["source_type"] = submitted_data.get("source_type") or existing_product.source_type
            updated_product = _get_store_service(request).replace_product(
                current_alias=alias,
                updated_product=_build_product_record_from_submission(submitted_data),
            )
            _migrate_auxiliary_alias_references(
                request=request,
                previous_alias=alias,
                updated_alias=updated_product.alias,
            )
    except (RuntimeError, ValueError) as error:
        context = _build_new_product_form_context(
            submitted_data=submitted_data,
            manual_variant_rows=manual_variants or _build_single_manual_variant_row(submitted_data, alias),
            error_message=f"Nao foi possivel salvar as alteracoes: {error}",
            form_mode="edit",
            form_action_url=f"/dashboard/products/{alias}/edit",
            submit_button_label="Salvar alteracoes",
            cancel_url=f"/dashboard/products/{alias}",
            allows_site_variants=True,
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


@router.post("/products/{alias}/confirm-site-link")
def dashboard_confirm_site_link(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Confirmar manualmente a correspondencia de um item interno com o site.

    Parametros:
        request: Requisicao HTTP atual.
        alias: Alias da variante que possui candidato salvo para vinculacao.

    Retorno:
        RedirectResponse para o detalhe atualizado ou TemplateResponse em erro.

    Contexto de uso:
        Fluxo manual de reconciliacao quando o operador reconhece que um item
        manual realmente voltou ao site e deve retomar a sincronizacao.
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

    try:
        updated_product = store_service.confirm_site_candidate(alias)
    except ValueError:
        return RedirectResponse(
            url=f"/dashboard/products/{alias}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        url=f"/dashboard/products/{updated_product.alias}?site_linked=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/products/{alias}/ignore-site-candidate")
def dashboard_ignore_site_candidate(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Ignorar uma sugestao de correspondencia entre cadastro interno e site.

    Parametros:
        request: Requisicao HTTP atual.
        alias: Alias da variante que possui candidato salvo.

    Retorno:
        RedirectResponse para o detalhe atualizado ou TemplateResponse em erro.

    Contexto de uso:
        Permite que o operador descarte candidatos ambivalentes sem perder o
        item manual nem transformar a tela em alerta permanente.
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

    try:
        updated_product = store_service.ignore_site_candidate(alias)
    except ValueError:
        return RedirectResponse(
            url=f"/dashboard/products/{alias}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        url=f"/dashboard/products/{updated_product.alias}?site_candidate_ignored=1",
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

    existing_product = _get_store_service(request).get_by_alias(alias)
    if existing_product is None:
        return RedirectResponse(url="/dashboard/search", status_code=status.HTTP_303_SEE_OTHER)

    if not existing_product.is_syncable:
        return RedirectResponse(
            url=f"/dashboard/products/{alias}?sync_blocked=1",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    resolve_result = _get_resolver_service(request).resolve_sku_for_alias(alias)
    last_update_by_alias[alias] = _build_update_snapshot(resolve_result)
    return RedirectResponse(url=f"/dashboard/products/{alias}", status_code=status.HTTP_303_SEE_OTHER)
