"""
Servico de cache para previews visuais de produtos.

Este modulo reduz custo de rede no dashboard mobile-first ao persistir titulo
e imagem principal inferidos da pagina do produto, sem alterar o contrato
principal do ProductRecord.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from backend.services.datetime_service import get_current_utc_isoformat
from backend.models.product import ProductRecord
from backend.utils.fetcher import FetchResult, Fetcher
from backend.utils.parser import PageData, parse_page_data


@dataclass(slots=True)
class ProductPreview:
    """
    Responsabilidade:
        Representar sinais visuais leves reutilizados pela interface.

    Parametros:
        alias: Alias do produto associado ao preview.
        source_url: URL usada para gerar o cache do preview.
        title: Titulo de pagina inferido para apoio visual.
        image_url: URL da imagem principal quando disponivel.
        cached_at: Timestamp UTC da geracao do preview.

    Retorno:
        Estrutura enxuta para cards, listas e cabecalhos de detalhe.

    Contexto de uso:
        Alimenta telas mobile-first sem novo fetch em toda navegacao.
    """

    alias: str
    source_url: str
    title: Optional[str]
    image_url: Optional[str]
    cached_at: str

    @classmethod
    def from_dict(cls, raw_item: Dict[str, object]) -> "ProductPreview":
        """
        Responsabilidade:
            Reconstruir preview persistido a partir de dicionario JSON.

        Parametros:
            raw_item: Objeto bruto vindo do arquivo de cache.

        Retorno:
            ProductPreview com campos normalizados.

        Contexto de uso:
            Utilizado na leitura do cache em disco do dashboard.
        """

        return cls(
            alias=str(raw_item.get("alias", "")).strip(),
            source_url=str(raw_item.get("source_url", "")).strip(),
            title=_optional_to_str(raw_item.get("title")),
            image_url=_optional_to_str(raw_item.get("image_url")),
            cached_at=str(raw_item.get("cached_at", "")).strip(),
        )

    def to_dict(self) -> Dict[str, Optional[str]]:
        """
        Responsabilidade:
            Serializar preview para formato JSON persistivel.

        Parametros:
            Nenhum.

        Retorno:
            Dicionario com os campos relevantes do preview.

        Contexto de uso:
            Chamado pelo servico durante escrita do cache em disco.
        """

        return {
            "alias": self.alias,
            "source_url": self.source_url,
            "title": self.title,
            "image_url": self.image_url,
            "cached_at": self.cached_at,
        }


class ProductPreviewService:
    """
    Responsabilidade:
        Ler, persistir e atualizar previews visuais de produtos.

    Parametros:
        storage_file_path: Caminho do arquivo JSON de cache.
        fetcher: Cliente HTTP reutilizado para coletar sinais visuais.

    Retorno:
        Instancia do servico pronta para uso pela camada web.

    Contexto de uso:
        Reaproveitado por listas e tela de detalhe para reduzir latencia.
    """

    def __init__(self, storage_file_path: Path, fetcher: Fetcher) -> None:
        """
        Responsabilidade:
            Inicializar servico e garantir existencia do arquivo de cache.

        Parametros:
            storage_file_path: Arquivo onde o cache sera persistido.
            fetcher: Cliente HTTP usado para buscar paginas remotas.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construido uma vez por processo e reutilizado entre requests.
        """

        self.storage_file_path = storage_file_path
        self.fetcher = fetcher
        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        """
        Responsabilidade:
            Garantir diretorio e arquivo base do cache em disco.

        Parametros:
            Nenhum.

        Retorno:
            Nenhum.

        Contexto de uso:
            Evita falhas em primeiro acesso ou ambiente recem-criado.
        """

        self.storage_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_file_path.exists():
            self.storage_file_path.write_text("{}", encoding="utf-8")

    def _read_all(self) -> Dict[str, ProductPreview]:
        """
        Responsabilidade:
            Ler todo o cache de previews do disco.

        Parametros:
            Nenhum.

        Retorno:
            Mapa de alias para ProductPreview.

        Contexto de uso:
            Base para consulta, merge e escrita atomica do cache.
        """

        try:
            raw_content = self.storage_file_path.read_text(encoding="utf-8")
            raw_cache = json.loads(raw_content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de cache de previews contem JSON invalido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de cache de previews") from error

        if not isinstance(raw_cache, dict):
            raise ValueError("Arquivo de cache de previews deve conter objeto JSON")

        parsed_cache: Dict[str, ProductPreview] = {}
        for alias, raw_item in raw_cache.items():
            if not isinstance(raw_item, dict):
                continue
            parsed_cache[str(alias).strip()] = ProductPreview.from_dict(raw_item)

        return parsed_cache

    def _write_all(self, preview_map: Dict[str, ProductPreview]) -> None:
        """
        Responsabilidade:
            Persistir cache completo em escrita atomica simplificada.

        Parametros:
            preview_map: Mapa atualizado de alias para preview.

        Retorno:
            Nenhum.

        Contexto de uso:
            Metodo interno usado em atualizacao do cache.
        """

        serializable_cache = {alias: preview.to_dict() for alias, preview in preview_map.items()}
        temporary_file_path = self.storage_file_path.with_suffix(".tmp")

        try:
            temporary_file_path.write_text(
                json.dumps(serializable_cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file_path.replace(self.storage_file_path)
        except OSError as error:
            raise RuntimeError("Falha ao salvar arquivo de cache de previews") from error

    def get_cached_preview(self, product: ProductRecord) -> Optional[ProductPreview]:
        """
        Responsabilidade:
            Retornar preview persistido quando a URL cacheada ainda e valida.

        Parametros:
            product: Produto consultado pela interface.

        Retorno:
            ProductPreview quando houver cache compativel; senao None.

        Contexto de uso:
            Usado por listas para renderizacao rapida sem rede.
        """

        preview_map = self._read_all()
        cached_preview = preview_map.get(product.alias)
        if cached_preview is None:
            return None

        if cached_preview.source_url != product.last_known_url.strip():
            return None

        return cached_preview

    def ensure_preview(self, product: ProductRecord) -> Optional[ProductPreview]:
        """
        Responsabilidade:
            Garantir preview atualizado, buscando a pagina quando necessario.

        Parametros:
            product: Produto que precisa de sinais visuais para a UI.

        Retorno:
            ProductPreview quando a coleta for bem-sucedida; senao None.

        Contexto de uso:
            Utilizado em areas criticas como Home e tela de detalhe.
        """

        cached_preview = self.get_cached_preview(product)
        if cached_preview is not None:
            return cached_preview

        if not product.last_known_url.strip():
            return None

        try:
            fetch_result: FetchResult = self.fetcher.fetch_page(product.last_known_url)
        except Exception:
            # Tratamento de erro:
            # O preview visual nao pode bloquear navegacao; em falha retornamos
            # None para que a interface use placeholder seguro.
            return None

        page_data: PageData = parse_page_data(
            page_url=fetch_result.final_url,
            html_content=fetch_result.html_content,
            configured_fallback_sku=product.last_known_sku,
        )
        preview = ProductPreview(
            alias=product.alias,
            source_url=product.last_known_url.strip(),
            title=page_data.title or page_data.name,
            image_url=page_data.image_url,
            cached_at=get_current_utc_isoformat(),
        )

        preview_map = self._read_all()
        preview_map[product.alias] = preview
        self._write_all(preview_map)
        return preview


def _optional_to_str(raw_value: object) -> Optional[str]:
    """
    Responsabilidade:
        Normalizar valor opcional para string limpa.

    Parametros:
        raw_value: Valor possivelmente nulo vindo do JSON.

    Retorno:
        String quando houver conteudo; caso contrario, None.

    Contexto de uso:
        Auxiliar interno para leitura resiliente do cache de preview.
    """

    if raw_value is None:
        return None

    normalized_value = str(raw_value).strip()
    return normalized_value or None
