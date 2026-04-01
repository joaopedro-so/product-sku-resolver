"""
Servico de leitura de overrides manuais para reconciliacao com o site.

Este modulo permite que a operacao declare, em um arquivo simples, quais
variantes internas devem ser vinculadas a produtos especificos do site quando
as heuristicas automaticas nao forem suficientes ou forem arriscadas demais.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.storage_path_service import resolve_default_data_file


@dataclass(slots=True)
class SiteLinkOverrideDefinition:
    """
    Responsabilidade:
        Representar um override manual de vínculo entre item interno e site.

    Parâmetros:
        internal_alias: Alias exato da variante interna que deve ser alvo do vínculo.
        internal_parent_reference: Referência pai interna usada como fallback.
        site_product_id: Identificador estável do produto pai no site.
        site_variant_label: Rótulo esperado da variante no site, como 100ml.
        site_variant_code: Código atual esperado da variante do site.

    Retorno:
        Estrutura tipada pronta para consumo pela camada de reconciliação.

    Contexto de uso:
        Aplicada antes das heurísticas para que a curadoria manual tenha a
        prioridade máxima em casos sensíveis ou recorrentes.
    """

    internal_alias: str = ""
    internal_parent_reference: str = ""
    site_product_id: str = ""
    site_variant_label: str = ""
    site_variant_code: str = ""


class SiteLinkOverrideService:
    """
    Responsabilidade:
        Ler e normalizar o arquivo de overrides manuais de vínculo ao site.

    Parâmetros:
        storage_file_path: Caminho opcional do arquivo JSON de overrides.

    Retorno:
        Instância pronta para entregar definições de override tipadas.

    Contexto de uso:
        Consumida pela reconciliação antes do matching automático, evitando
        decisões ambíguas em produtos que exigem curadoria humana.
    """

    def __init__(self, storage_file_path: Optional[Path] = None) -> None:
        """
        Responsabilidade:
            Inicializar o serviço com um caminho estável para o arquivo JSON.

        Parâmetros:
            storage_file_path: Caminho opcional do arquivo de overrides.

        Retorno:
            Nenhum.

        Contexto de uso:
            Permite usar o arquivo padrão em produção e arquivos temporários
            isolados nos testes automatizados.
        """

        self.storage_file_path = storage_file_path or _resolve_default_override_file_path()

    def list_overrides(self) -> List[SiteLinkOverrideDefinition]:
        """
        Responsabilidade:
            Carregar todos os overrides declarados no arquivo de configuração.

        Parâmetros:
            Nenhum.

        Retorno:
            Lista de SiteLinkOverrideDefinition já normalizada.

        Contexto de uso:
            Chamado pela camada de reconciliação para aplicar prioridade manual
            antes de qualquer heurística de matching.
        """

        payload = self._read_payload()
        raw_overrides = payload.get("overrides", [])
        if not isinstance(raw_overrides, list):
            raise ValueError("Arquivo de overrides de vínculo deve conter uma lista em 'overrides'")

        return [
            self._parse_override(raw_override)
            for raw_override in raw_overrides
            if isinstance(raw_override, dict)
        ]

    def _read_payload(self) -> Dict[str, Any]:
        """
        Responsabilidade:
            Ler o JSON bruto de overrides com fallback seguro.

        Parâmetros:
            Nenhum.

        Retorno:
            Dicionário com a estrutura raiz do arquivo.

        Contexto de uso:
            Mantém a feature opcional: se o arquivo não existir, o app segue
            funcionando normalmente com lista vazia de overrides.
        """

        if not self.storage_file_path.exists():
            return {"overrides": []}

        try:
            raw_content = self.storage_file_path.read_text(encoding="utf-8")
            raw_payload = json.loads(raw_content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de overrides de vínculo contém JSON inválido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de overrides de vínculo") from error

        if isinstance(raw_payload, list):
            return {"overrides": raw_payload}
        if isinstance(raw_payload, dict):
            return raw_payload

        raise ValueError("Arquivo de overrides de vínculo deve conter um objeto JSON ou uma lista")

    def _parse_override(self, raw_override: Dict[str, Any]) -> SiteLinkOverrideDefinition:
        """
        Responsabilidade:
            Converter um override bruto em estrutura tipada e previsível.

        Parâmetros:
            raw_override: Dicionário individual vindo do JSON de configuração.

        Retorno:
            SiteLinkOverrideDefinition já validada e normalizada.

        Contexto de uso:
            Centraliza o contrato do arquivo de configuração e evita lógica de
            parsing espalhada pela camada de reconciliação.
        """

        return SiteLinkOverrideDefinition(
            internal_alias=str(raw_override.get("internal_alias", "")).strip(),
            internal_parent_reference=str(raw_override.get("internal_parent_reference", "")).strip(),
            site_product_id=str(raw_override.get("site_product_id", "")).strip(),
            site_variant_label=str(raw_override.get("site_variant_label", "")).strip(),
            site_variant_code=str(raw_override.get("site_variant_code", "")).strip(),
        )


def _resolve_default_override_file_path() -> Path:
    """
    Responsabilidade:
        Resolver o caminho padrão do arquivo de overrides de vínculo.

    Parâmetros:
        Nenhum.

    Retorno:
        Path absoluto apontando para o JSON de overrides do projeto.

    Contexto de uso:
        Mantém a configuração acessível por variável de ambiente sem perder o
        fallback simples para `data/manual_site_link_overrides.json`.
    """

    configured_path = os.getenv("MANUAL_SITE_LINK_OVERRIDES_FILE", "").strip()
    if configured_path:
        return Path(configured_path)

    return resolve_default_data_file("manual_site_link_overrides.json")
