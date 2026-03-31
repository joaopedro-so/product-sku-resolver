"""
Servico de importacao curada de perfumes da Renner para o catalogo operacional.

Este modulo existe para transformar uma lista manualmente revisada de produtos
da Renner em registros persistidos no `products.json`, sem acoplar scraping ou
regras de cadastro diretamente nas rotas web.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import ParseResult, parse_qsl, urlencode, urlparse, urlunparse

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService
from backend.services.storage_path_service import resolve_project_file
from backend.utils.fetcher import Fetcher
from backend.utils.parser import PageData, parse_page_data


@dataclass(slots=True)
class CuratedRennerImportEntry:
    """
    Responsabilidade:
        Representar um item curado manualmente para importacao em lote.

    Parametros:
        alias: Alias canonico que sera usado no storage local.
        brand: Marca amigavel exibida no app.
        name: Nome operacional do perfume, sem marketing excessivo.
        variant: Variante curta usada na interface, como 50ml ou 100ml.
        sku: Codigo operacional que deve ser persistido para barcode.
        page_url: URL base da pagina da Renner validada na curadoria.
        shelf_number: Numero fisico da prateleira onde o item fica.
        display_order: Ordem fisica opcional dentro da prateleira.
        expected_title_fragment: Trecho opcional do titulo esperado da pagina.

    Retorno:
        Estrutura tipada pronta para ser validada e persistida.

    Contexto de uso:
        Utilizada por seeds internos quando o time ja conferiu manualmente
        qual pagina e qual rotulo operacional devem representar cada perfume.
    """

    alias: str
    brand: str
    name: str
    variant: str
    sku: str
    page_url: str
    shelf_number: int
    display_order: Optional[int] = None
    expected_title_fragment: str = ""

    @classmethod
    def from_dict(cls, raw_entry: dict[str, Any]) -> "CuratedRennerImportEntry":
        """
        Responsabilidade:
            Converter um dicionario bruto do seed em entrada tipada e valida.

        Parametros:
            raw_entry: Objeto carregado do JSON de importacao curada.

        Retorno:
            CuratedRennerImportEntry normalizado para consumo pelo servico.

        Contexto de uso:
            Mantem a validacao do seed centralizada, evitando que scripts e
            testes precisem repetir regras basicas de estrutura.
        """

        required_fields = [
            "alias",
            "brand",
            "name",
            "variant",
            "sku",
            "page_url",
            "shelf_number",
        ]
        missing_fields = [field_name for field_name in required_fields if field_name not in raw_entry]
        if missing_fields:
            missing_description = ", ".join(missing_fields)
            raise ValueError(f"Entrada curada invalida: campos ausentes: {missing_description}")

        raw_display_order = raw_entry.get("display_order")
        normalized_display_order: Optional[int]
        if raw_display_order in (None, ""):
            normalized_display_order = None
        else:
            normalized_display_order = int(raw_display_order)

        return cls(
            alias=str(raw_entry["alias"]).strip(),
            brand=str(raw_entry["brand"]).strip(),
            name=str(raw_entry["name"]).strip(),
            variant=str(raw_entry["variant"]).strip(),
            sku=str(raw_entry["sku"]).strip(),
            page_url=str(raw_entry["page_url"]).strip(),
            shelf_number=int(raw_entry["shelf_number"]),
            display_order=normalized_display_order,
            expected_title_fragment=str(raw_entry.get("expected_title_fragment", "")).strip(),
        )


@dataclass(slots=True)
class CuratedRennerImportResult:
    """
    Responsabilidade:
        Representar o resultado de importacao de um item curado individual.

    Parametros:
        alias: Alias do produto tentado na importacao.
        success: Indica se o produto foi persistido com sucesso.
        message: Mensagem operacional explicando sucesso ou falha.
        product: Produto persistido quando a operacao foi bem-sucedida.

    Retorno:
        Estrutura simples para logs, scripts e testes de importacao.

    Contexto de uso:
        Permite que a importacao em lote continue mesmo quando uma entrada
        falha, sem esconder os detalhes necessarios para revisao manual.
    """

    alias: str
    success: bool
    message: str
    product: Optional[ProductRecord] = None


class CuratedRennerImportService:
    """
    Responsabilidade:
        Importar perfumes curados da Renner para o storage do app.

    Parametros:
        fetcher: Cliente HTTP reutilizado para validar as paginas da Renner.
        product_store: Storage definitivo onde os produtos serao persistidos.

    Retorno:
        Servico pronto para importar seeds curados de forma deterministica.

    Contexto de uso:
        Serve como ponte entre uma curadoria manual externa e o modelo atual
        do app, preservando o fluxo de barcode, sync e listagem existente.
    """

    def __init__(self, fetcher: Fetcher, product_store: ProductStoreService) -> None:
        """
        Responsabilidade:
            Guardar as dependencias necessarias para validacao e persistencia.

        Parametros:
            fetcher: Cliente HTTP usado para checar as paginas da Renner.
            product_store: Servico responsavel por gravar o produto no JSON.

        Retorno:
            Nenhum.

        Contexto de uso:
            A composicao via injecao facilita teste isolado e reuso por script.
        """

        self.fetcher = fetcher
        self.product_store = product_store

    def import_entries(self, entries: List[CuratedRennerImportEntry]) -> List[CuratedRennerImportResult]:
        """
        Responsabilidade:
            Processar uma lista de entradas curadas e persistir cada produto.

        Parametros:
            entries: Lista de itens revisados manualmente para importacao.

        Retorno:
            Lista de resultados individuais com sucesso ou falha por item.

        Contexto de uso:
            Entrada principal usada por scripts de carga inicial e curadoria.
        """

        results: List[CuratedRennerImportResult] = []
        for entry in entries:
            results.append(self.import_single_entry(entry))
        return results

    def import_single_entry(self, entry: CuratedRennerImportEntry) -> CuratedRennerImportResult:
        """
        Responsabilidade:
            Validar uma entrada curada, montar o ProductRecord e persisti-lo.

        Parametros:
            entry: Produto curado manualmente com dados da Renner.

        Retorno:
            CuratedRennerImportResult com o status final da importacao.

        Contexto de uso:
            Mantem o loop da importacao em lote pequeno e facilita testes
            focados em casos de sucesso e falha.
        """

        try:
            page_data = self._validate_source_page(entry)
            product_to_save = self._build_product_record(entry=entry, page_data=page_data)
            persisted_product = self.product_store.upsert_product(product_to_save)
        except Exception as error:
            return CuratedRennerImportResult(
                alias=entry.alias,
                success=False,
                message=f"Falha ao importar '{entry.alias}': {error}",
                product=None,
            )

        return CuratedRennerImportResult(
            alias=entry.alias,
            success=True,
            message=f"Produto '{entry.alias}' importado com sucesso.",
            product=persisted_product,
        )

    def load_entries_from_file(self, seed_file_path: Path) -> List[CuratedRennerImportEntry]:
        """
        Responsabilidade:
            Ler um arquivo JSON de seed e convertelo em entradas tipadas.

        Parametros:
            seed_file_path: Caminho do arquivo curado com as entradas da Renner.

        Retorno:
            Lista de CuratedRennerImportEntry validas.

        Contexto de uso:
            Reaproveitado por scripts internos para manter o seed fora do codigo.
        """

        try:
            content = seed_file_path.read_text(encoding="utf-8")
            raw_payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de seed curado contem JSON invalido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de seed curado") from error

        raw_entries = raw_payload.get("entries", [])
        if not isinstance(raw_entries, list):
            raise ValueError("Arquivo de seed curado deve conter uma lista em 'entries'")

        return [CuratedRennerImportEntry.from_dict(raw_entry) for raw_entry in raw_entries if isinstance(raw_entry, dict)]

    def _validate_source_page(self, entry: CuratedRennerImportEntry) -> PageData:
        """
        Responsabilidade:
            Validar se a pagina curada realmente corresponde ao SKU informado.

        Parametros:
            entry: Entrada curada com URL base e SKU esperado.

        Retorno:
            PageData extraido da pagina base, util para mensagens e auditoria.

        Contexto de uso:
            Evita persistir um SKU em pagina errada apenas porque a URL com
            query `sku=` aceitou o valor sem confirmar a variante real.
        """

        base_fetch_result = self.fetcher.fetch_page(entry.page_url)
        if entry.sku not in base_fetch_result.html_content:
            raise ValueError(
                f"O SKU '{entry.sku}' nao foi confirmado no HTML da pagina base informada"
            )

        page_data = parse_page_data(
            page_url=base_fetch_result.final_url,
            html_content=base_fetch_result.html_content,
            configured_fallback_sku=None,
        )

        normalized_title_fragment = entry.expected_title_fragment.lower().strip()
        normalized_page_title = str(page_data.title or "").lower().strip()
        if normalized_title_fragment and normalized_title_fragment not in normalized_page_title:
            raise ValueError(
                "O titulo da pagina validada nao corresponde ao trecho esperado da curadoria"
            )

        return page_data

    def _build_product_record(
        self,
        entry: CuratedRennerImportEntry,
        page_data: PageData,
    ) -> ProductRecord:
        """
        Responsabilidade:
            Transformar a entrada curada em um ProductRecord persistivel.

        Parametros:
            entry: Entrada curada que define identidade operacional do perfume.
            page_data: Dados parseados da pagina base validada.

        Retorno:
            ProductRecord pronto para ser salvo no storage do app.

        Contexto de uso:
            Mantem a montagem do modelo isolada da parte de rede e da parte de
            persistencia, o que deixa a importacao mais didatica e extensivel.
        """

        final_product_url = self._build_variant_url(base_page_url=page_data.url or entry.page_url, sku=entry.sku)
        return ProductRecord(
            alias=entry.alias,
            brand=entry.brand,
            name=entry.name,
            variant=entry.variant,
            last_known_url=final_product_url,
            last_known_sku=entry.sku,
            page_family_sku=ProductRecord.from_dict(
                {
                    "alias": entry.alias,
                    "brand": entry.brand,
                    "name": entry.name,
                    "variant": entry.variant,
                    "last_known_url": final_product_url,
                    "last_known_sku": entry.sku,
                }
            ).page_family_sku,
            shelf_number=entry.shelf_number,
            display_order=entry.display_order,
        )

    def _build_variant_url(self, base_page_url: str, sku: str) -> str:
        """
        Responsabilidade:
            Garantir que a URL persistida aponte para a variante operacional.

        Parametros:
            base_page_url: URL canonica da pagina do produto pai.
            sku: Codigo operacional da variante selecionada.

        Retorno:
            URL com query `sku` atualizada para a variante correspondente.

        Contexto de uso:
            A interface e o barcode usam essa URL como ultima referencia para
            atualizacao manual e futuras conciliacoes de codigo.
        """

        parsed_url: ParseResult = urlparse(base_page_url)
        existing_query_items = [(key, value) for key, value in parse_qsl(parsed_url.query, keep_blank_values=True) if key != "sku"]
        existing_query_items.append(("sku", sku))
        normalized_query = urlencode(existing_query_items)
        return urlunparse(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                normalized_query,
                parsed_url.fragment,
            )
        )


def resolve_builtin_curated_seed_file(seed_name: str) -> Path:
    """
    Responsabilidade:
        Resolver o caminho de um seed interno embarcado no codigo do projeto.

    Parametros:
        seed_name: Nome logico do seed sem extensao nem caminho.

    Retorno:
        Path absoluto do arquivo JSON versionado no repositorio.

    Contexto de uso:
        Permite que o dashboard e scripts internos leiam seeds curados mesmo
        quando a pasta `data/` estiver montada como volume na Railway.
    """

    normalized_seed_name = str(seed_name).strip().replace("\\", "/").split("/")[-1]
    if not normalized_seed_name:
        raise ValueError("O nome do seed interno nao pode ser vazio")

    return resolve_project_file(f"backend/resources/imports/{normalized_seed_name}.json")
