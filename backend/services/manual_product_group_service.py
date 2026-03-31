"""
Servico de leitura de agrupamentos manuais de produtos.

Este modulo cria uma camada pequena e explicita para curadoria interna dos
grupos de perfumes. A ideia e permitir que o time defina manualmente quais
SKUs pertencem ao mesmo produto pai quando o site de origem nao modela isso
de forma confiavel.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class ManualProductGroupMember:
    """
    Responsabilidade:
        Representar um SKU especifico que pertence a um grupo manual.

    Parametros:
        alias: Alias persistido do produto variante no storage atual.
        label: Rotulo da variante exibido na interface, como 50ml.
        display_order: Ordem manual opcional para o seletor de variantes.

    Retorno:
        Estrutura leve usada para montar grupos curados manualmente.

    Contexto de uso:
        Permite que a curadoria controle tanto quais SKUs pertencem ao mesmo
        perfume quanto a ordem de exibicao das variantes no app.
    """

    alias: str
    label: str = ""
    display_order: Optional[int] = None


@dataclass(slots=True)
class ManualProductGroupDefinition:
    """
    Responsabilidade:
        Representar a configuracao curada de um produto pai agrupado manualmente.

    Parametros:
        group_id: Identificador interno estavel do grupo manual.
        display_name: Nome amigavel do produto pai exibido no app.
        brand: Marca principal do grupo.
        family_name: Linha/familia mais ampla do perfume.
        product_type: Categoria opcional como EDT ou EDP.
        variant_members: Lista ordenada de variantes pertencentes ao grupo.

    Retorno:
        Estrutura tipada usada pelo servico de agrupamento principal.

    Contexto de uso:
        Separa claramente o conceito de familia, grupo e variantes, sem
        espalhar regras especiais diretamente nas rotas ou templates.
    """

    group_id: str
    display_name: str
    brand: str = ""
    family_name: str = ""
    product_type: str = ""
    variant_members: List[ManualProductGroupMember] | None = None


class ManualProductGroupService:
    """
    Responsabilidade:
        Ler e normalizar a configuracao de agrupamentos manuais.

    Parametros:
        storage_file_path: Caminho opcional do arquivo JSON de overrides.

    Retorno:
        Instancia pronta para entregar grupos manuais tipados ao agrupador.

    Contexto de uso:
        Fica como camada de infraestrutura pequena e reaproveitavel, deixando
        o ProductGroupService focado apenas na semantica de agrupamento.
    """

    def __init__(self, storage_file_path: Optional[Path] = None) -> None:
        """
        Responsabilidade:
            Inicializar o servico e garantir um caminho previsivel de leitura.

        Parametros:
            storage_file_path: Caminho opcional do JSON de grupos manuais.

        Retorno:
            Nenhum.

        Contexto de uso:
            Permite usar o arquivo padrao do projeto em producao e um arquivo
            temporario isolado durante testes.
        """

        self.storage_file_path = storage_file_path or _resolve_default_manual_group_file_path()

    def list_groups(self) -> List[ManualProductGroupDefinition]:
        """
        Responsabilidade:
            Carregar todos os grupos manuais declarados no arquivo de configuracao.

        Parametros:
            Nenhum.

        Retorno:
            Lista tipada de grupos manuais validos.

        Contexto de uso:
            Chamado pelo agrupador principal antes da heuristica automatica,
            garantindo que a curadoria manual tenha prioridade final.
        """

        raw_payload = self._read_payload()
        raw_groups = raw_payload.get("groups", [])
        if not isinstance(raw_groups, list):
            raise ValueError("Arquivo de grupos manuais deve conter uma lista em 'groups'")

        parsed_groups = [
            self._parse_group_definition(raw_group)
            for raw_group in raw_groups
            if isinstance(raw_group, dict)
        ]
        self._validate_duplicate_members(parsed_groups)
        return parsed_groups

    def _read_payload(self) -> Dict[str, Any]:
        """
        Responsabilidade:
            Ler o JSON bruto de agrupamentos manuais com fallback seguro.

        Parametros:
            Nenhum.

        Retorno:
            Dicionario com a estrutura raiz do arquivo.

        Contexto de uso:
            Evita que a ausencia inicial do arquivo quebre o app, ao mesmo
            tempo em que mantem a configuracao externa e editavel.
        """

        if not self.storage_file_path.exists():
            return {"groups": []}

        try:
            content = self.storage_file_path.read_text(encoding="utf-8")
            raw_payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de grupos manuais contem JSON invalido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de grupos manuais") from error

        if isinstance(raw_payload, list):
            return {"groups": raw_payload}
        if isinstance(raw_payload, dict):
            return raw_payload

        raise ValueError("Arquivo de grupos manuais deve conter um objeto JSON ou uma lista")

    def _parse_group_definition(self, raw_group: Dict[str, Any]) -> ManualProductGroupDefinition:
        """
        Responsabilidade:
            Converter um grupo bruto em estrutura tipada e validada.

        Parametros:
            raw_group: Dicionario individual vindo do JSON de configuracao.

        Retorno:
            ManualProductGroupDefinition pronto para consumo interno.

        Contexto de uso:
            Centraliza a normalizacao dos nomes de campo para manter o contrato
            da configuracao manual simples e previsivel.
        """

        group_id = str(raw_group.get("group_id", "")).strip()
        display_name = str(raw_group.get("display_name", "")).strip()
        if not group_id:
            raise ValueError("Cada grupo manual precisa de 'group_id'")
        if not display_name:
            raise ValueError(f"Grupo manual '{group_id}' precisa de 'display_name'")

        raw_members = raw_group.get("variant_members", [])
        if not isinstance(raw_members, list):
            raise ValueError(f"Grupo manual '{group_id}' precisa de lista em 'variant_members'")

        parsed_members = [
            self._parse_group_member(group_id=group_id, raw_member=raw_member)
            for raw_member in raw_members
            if isinstance(raw_member, dict)
        ]
        if not parsed_members:
            raise ValueError(f"Grupo manual '{group_id}' precisa ter ao menos um membro")

        return ManualProductGroupDefinition(
            group_id=group_id,
            display_name=display_name,
            brand=str(raw_group.get("brand", "")).strip(),
            family_name=str(raw_group.get("family_name", "")).strip(),
            product_type=str(raw_group.get("product_type", "")).strip(),
            variant_members=parsed_members,
        )

    def _parse_group_member(
        self,
        group_id: str,
        raw_member: Dict[str, Any],
    ) -> ManualProductGroupMember:
        """
        Responsabilidade:
            Normalizar um membro de variante dentro de um grupo manual.

        Parametros:
            group_id: Identificador do grupo pai para mensagens de validacao.
            raw_member: Dicionario bruto da variante vindo do JSON.

        Retorno:
            ManualProductGroupMember tipado e pronto para uso.

        Contexto de uso:
            Mantem a validacao local e facilita diagnostico quando a curadoria
            comete algum erro de alias ou estrutura no arquivo manual.
        """

        alias = str(raw_member.get("alias", "")).strip()
        if not alias:
            raise ValueError(f"Grupo manual '{group_id}' contem membro sem 'alias'")

        raw_display_order = raw_member.get("display_order")
        display_order: Optional[int]
        if raw_display_order in (None, ""):
            display_order = None
        else:
            try:
                display_order = int(raw_display_order)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Grupo manual '{group_id}' contem 'display_order' invalido para o alias '{alias}'"
                ) from error

        return ManualProductGroupMember(
            alias=alias,
            label=str(raw_member.get("label", "")).strip(),
            display_order=display_order,
        )

    def _validate_duplicate_members(self, groups: List[ManualProductGroupDefinition]) -> None:
        """
        Responsabilidade:
            Garantir que o mesmo alias nao pertença a dois grupos manuais.

        Parametros:
            groups: Lista de grupos ja parseados do arquivo de configuracao.

        Retorno:
            Nenhum.

        Contexto de uso:
            Evita ambiguidades silenciosas na curadoria, que poderiam gerar
            agrupamentos incoerentes e dificeis de depurar no app.
        """

        seen_alias_to_group: Dict[str, str] = {}
        for group in groups:
            for member in group.variant_members or []:
                previous_group_id = seen_alias_to_group.get(member.alias)
                if previous_group_id is not None:
                    raise ValueError(
                        f"Alias '{member.alias}' aparece em mais de um grupo manual: "
                        f"'{previous_group_id}' e '{group.group_id}'"
                    )
                seen_alias_to_group[member.alias] = group.group_id


def _resolve_default_manual_group_file_path() -> Path:
    """
    Responsabilidade:
        Definir o caminho padrao do arquivo de agrupamentos manuais.

    Parametros:
        Nenhum.

    Retorno:
        Caminho absoluto ou relativo do JSON de configuracao manual.

    Contexto de uso:
        Permite override por variavel de ambiente em producao, mas mantem um
        fallback simples em `data/manual_product_groups.json` no projeto.
    """

    configured_path = os.getenv("MANUAL_PRODUCT_GROUPS_FILE", "").strip()
    if configured_path:
        return Path(configured_path)

    return Path("data/manual_product_groups.json")
