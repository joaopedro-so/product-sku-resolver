"""
Modelos de domínio relacionados ao produto monitorado.

Este módulo concentra o contrato de dados usado pelo armazenamento e pelas
camadas de serviço, mantendo validações simples, explícitas e estáveis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(slots=True)
class ProductRecord:
    """
    Responsabilidade:
        Representar uma variante persistida do catálogo operacional.

    Parâmetros:
        alias: Identificador interno amigável para API e armazenamento.
        brand: Marca estável usada em validações e agrupamento.
        name: Nome estável do produto usado em validações e agrupamento.
        variant: Variante estável da linha, como volume ou tamanho.
        last_known_url: URL mais recente considerada válida para o produto.
        last_known_sku: Código operacional mais recente da variante.
        page_family_sku: Identificador estável da página/produto pai do site.
        parent_reference: Identificador estável interno do produto pai no catálogo.
        source_type: Origem principal do item (`site`, `manual` ou `legacy`).
        concentration: Concentração ou tipo do perfume, como EDT ou EDP.
        shelf_reference_label: Referência física complementar da prateleira.
        notes: Observações gerais do produto pai/variante.
        image_url: URL persistida da imagem manual ou curada da variante.
        stock_qty: Quantidade atual em estoque da variante.
        variant_notes: Observações específicas da variante.
        is_active: Define se a variante ainda deve aparecer no catálogo.

    Retorno:
        Instância tipada de ProductRecord para uso interno no backend.

    Contexto de uso:
        Utilizada por product_store_service para leitura e escrita em JSON,
        garantindo um contrato único de dados em toda a aplicação.
    """

    alias: str
    brand: str
    name: str
    variant: str
    last_known_url: str
    last_known_sku: str
    page_family_sku: str = ""
    parent_reference: str = ""
    source_type: str = "site"
    concentration: str = ""
    shelf_reference_label: str = ""
    notes: str = ""
    image_url: str = ""
    stock_qty: int = 0
    variant_notes: str = ""
    is_active: bool = True
    shelf_number: int | None = None
    display_order: int | None = None

    @classmethod
    def from_dict(cls, source: Dict[str, Any]) -> "ProductRecord":
        """
        Responsabilidade:
            Criar ProductRecord a partir de dicionário com validação mínima.

        Parâmetros:
            source: Dicionário bruto vindo de JSON, API ou outro adaptador.

        Retorno:
            ProductRecord devidamente normalizado para uso interno.

        Contexto de uso:
            Chamado na leitura do arquivo de produtos para transformar dados
            não tipados em estrutura confiável antes das regras de negócio.
        """

        required_keys = [
            "alias",
            "brand",
            "name",
            "variant",
            "last_known_sku",
        ]

        missing_keys = [key for key in required_keys if key not in source]
        if missing_keys:
            missing_description = ", ".join(missing_keys)
            raise ValueError(
                f"Registro de produto inválido: campos ausentes: {missing_description}"
            )

        normalized_url = str(source.get("last_known_url", "")).strip()
        normalized_source_type = _normalize_source_type(source.get("source_type"))
        normalized_parent_reference = str(source.get("parent_reference", "")).strip()

        # Decisão técnica:
        # Forçamos string para reduzir inconsistência de tipos vindos de JSON
        # ou payloads externos, simplificando as camadas seguintes.
        return cls(
            alias=str(source["alias"]).strip(),
            brand=str(source["brand"]).strip(),
            name=str(source["name"]).strip(),
            variant=str(source["variant"]).strip(),
            last_known_url=normalized_url,
            last_known_sku=str(source["last_known_sku"]).strip(),
            page_family_sku=_resolve_page_family_sku(
                raw_page_family_sku=source.get("page_family_sku"),
                last_known_url=normalized_url,
            ),
            parent_reference=normalized_parent_reference,
            source_type=normalized_source_type,
            concentration=str(source.get("concentration", "")).strip(),
            shelf_reference_label=str(source.get("shelf_reference_label", "")).strip(),
            notes=str(source.get("notes", "")).strip(),
            image_url=str(source.get("image_url", "")).strip(),
            stock_qty=_optional_to_non_negative_int(source.get("stock_qty"), default_value=0),
            variant_notes=str(source.get("variant_notes", "")).strip(),
            is_active=_optional_to_bool(source.get("is_active"), default_value=True),
            shelf_number=_optional_to_int(source.get("shelf_number")),
            display_order=_optional_to_int(source.get("display_order")),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Responsabilidade:
            Serializar ProductRecord para formato dicionário persistível.

        Parâmetros:
            Nenhum.

        Retorno:
            Dicionário com os campos que devem ser gravados no armazenamento.

        Contexto de uso:
            Utilizado na persistência em products.json ou retorno de API,
            mantendo formato consistente para integrações externas.
        """

        payload: Dict[str, Any] = {
            "alias": self.alias,
            "brand": self.brand,
            "name": self.name,
            "variant": self.variant,
            "last_known_url": self.last_known_url,
            "last_known_sku": self.last_known_sku,
            "page_family_sku": self.page_family_sku,
            "parent_reference": self.parent_reference,
            "source_type": self.source_type,
            "concentration": self.concentration,
            "shelf_reference_label": self.shelf_reference_label,
            "notes": self.notes,
            "image_url": self.image_url,
            "stock_qty": self.stock_qty,
            "variant_notes": self.variant_notes,
            "is_active": self.is_active,
        }
        if self.shelf_number is not None:
            payload["shelf_number"] = self.shelf_number
        if self.display_order is not None:
            payload["display_order"] = self.display_order
        return payload

    @property
    def variant_code(self) -> str:
        """
        Responsabilidade:
            Expor o código operacional da variante com nome semântico claro.

        Parâmetros:
            Nenhum.

        Retorno:
            Código atualmente usado para operação, barcode e conferência.

        Contexto de uso:
            Ajuda a separar mentalmente o código da variante do identificador
            estável da página, sem quebrar compatibilidade com o storage atual.
        """

        return self.last_known_sku

    @property
    def source_label(self) -> str:
        """
        Responsabilidade:
            Traduzir o tipo de origem em um rótulo amigável para a interface.

        Parâmetros:
            Nenhum.

        Retorno:
            Texto curto como `Manual`, `Fora do site` ou `Site`.

        Contexto de uso:
            Usado pela camada web para diferenciar produtos internos sem fazer
            o operador interpretar flags técnicas diretamente no template.
        """

        if self.source_type == "manual":
            return "Manual"
        if self.source_type == "legacy":
            return "Fora do site"
        return "Site"

    @property
    def is_syncable(self) -> bool:
        """
        Responsabilidade:
            Indicar se a variante ainda depende de sincronização com o site.

        Parâmetros:
            Nenhum.

        Retorno:
            True quando a origem ainda suporta sync automático; False caso contrário.

        Contexto de uso:
            Permite que a UI esconda ações de update para itens manuais ou
            legados, sem precisar repetir essa regra em vários módulos.
        """

        return self.source_type == "site"


def _optional_to_int(raw_value: Any) -> int | None:
    """
    Responsabilidade:
        Normalizar um valor opcional para inteiro de forma resiliente.

    Parâmetros:
        raw_value: Valor bruto vindo de JSON ou formulário.

    Retorno:
        Inteiro quando houver conteúdo válido; caso contrário, None.

    Contexto de uso:
        Mantém compatibilidade com produtos antigos que ainda não tinham
        localização de prateleira persistida.
    """

    if raw_value in (None, ""):
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _optional_to_non_negative_int(raw_value: Any, default_value: int = 0) -> int:
    """
    Responsabilidade:
        Normalizar um valor numérico opcional garantindo que ele não seja negativo.

    Parâmetros:
        raw_value: Valor bruto vindo de JSON ou formulário.
        default_value: Valor usado quando o conteúdo não for válido.

    Retorno:
        Inteiro não negativo, pronto para persistência.

    Contexto de uso:
        Estoque por variante não deve quebrar a leitura do catálogo por causa
        de valores vazios ou inválidos vindos de formulários manuais.
    """

    normalized_value = _optional_to_int(raw_value)
    if normalized_value is None:
        return default_value
    return max(0, normalized_value)


def _optional_to_bool(raw_value: Any, default_value: bool = True) -> bool:
    """
    Responsabilidade:
        Normalizar diferentes representações de booleano em um valor seguro.

    Parâmetros:
        raw_value: Valor bruto vindo de JSON ou payloads externos.
        default_value: Valor usado quando o conteúdo for nulo ou vazio.

    Retorno:
        Booleano consolidado para uso no modelo persistido.

    Contexto de uso:
        Mantém compatibilidade com registros antigos e com campos opcionais
        como `is_active`, que podem vir como texto, número ou booleano.
    """

    if raw_value in (None, ""):
        return default_value

    if isinstance(raw_value, bool):
        return raw_value

    normalized_value = str(raw_value).strip().lower()
    if normalized_value in {"1", "true", "sim", "yes", "on"}:
        return True
    if normalized_value in {"0", "false", "nao", "não", "no", "off"}:
        return False
    return default_value


def _normalize_source_type(raw_source_type: Any) -> str:
    """
    Responsabilidade:
        Garantir que o tipo de origem caia em um conjunto controlado.

    Parâmetros:
        raw_source_type: Valor bruto recebido do JSON ou formulário.

    Retorno:
        Uma das strings válidas: `site`, `manual` ou `legacy`.

    Contexto de uso:
        Evita que erros de digitação ou payloads antigos criem estados de
        origem desconhecidos que a UI não saberia interpretar.
    """

    normalized_source_type = str(raw_source_type or "").strip().lower()
    if normalized_source_type in {"manual", "legacy"}:
        return normalized_source_type
    return "site"


def _resolve_page_family_sku(raw_page_family_sku: Any, last_known_url: str) -> str:
    """
    Responsabilidade:
        Resolver o identificador estável da página a partir do dado persistido
        ou da URL conhecida quando o campo ainda não existir no JSON.

    Parâmetros:
        raw_page_family_sku: Valor bruto opcional vindo do storage.
        last_known_url: URL usada como fallback para derivar o SKU da página.

    Retorno:
        Identificador estável do produto pai, ou string vazia.

    Contexto de uso:
        Mantém retrocompatibilidade com registros antigos enquanto introduz a
        separação entre SKU da página e código operacional da variante.
    """

    normalized_page_family_sku = str(raw_page_family_sku or "").strip()
    if normalized_page_family_sku:
        return normalized_page_family_sku

    url_match = re.search(r"/A-(\d+)-", str(last_known_url), flags=re.IGNORECASE)
    if url_match:
        return url_match.group(1).strip()

    return ""
