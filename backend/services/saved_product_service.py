"""
Servico de persistencia para atalhos operacionais de acesso rapido.

Este modulo deixa de tratar a funcionalidade apenas como uma lista generica
de favoritos. O storage continua simples e leve, mas agora aceita metadados
que ajudam a interpretar o item salvo como acesso rapido para campanha,
monitoramento ou consulta recorrente.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

from backend.services.datetime_service import get_current_utc_isoformat

DEFAULT_SAVED_TAG = "quick_access"


@dataclass(slots=True)
class SavedProductEntry:
    """
    Responsabilidade:
        Representar um item salvo no acesso rapido com metadados opcionais.

    Parametros:
        alias: Alias real do produto salvo no catalogo.
        tag: Motivo operacional resumido do salvamento.
        saved_at: Timestamp UTC do momento em que o item entrou no acesso rapido.

    Retorno:
        Estrutura leve e tipada para transporte entre storage e camada web.

    Contexto de uso:
        Preserva compatibilidade com a lista antiga de aliases, mas abre caminho
        para tratar a area como acesso rapido operacional em vez de "favoritos".
    """

    alias: str
    tag: str = DEFAULT_SAVED_TAG
    saved_at: str = ""


def _normalize_saved_tag(raw_tag: str) -> str:
    """
    Responsabilidade:
        Consolidar a tag operacional em um conjunto pequeno e previsivel.

    Parametros:
        raw_tag: Valor bruto vindo do formulario ou do storage persistido.

    Retorno:
        Tag normalizada, pronta para ser gravada ou comparada.

    Contexto de uso:
        Evita que o storage fique poluido com variacoes triviais como
        "Quick Access", "quick-access" ou strings vazias.
    """

    normalized_tag = str(raw_tag or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized_tag:
        return DEFAULT_SAVED_TAG

    allowed_tags = {"campaign", "quick_access", "monitoring"}
    if normalized_tag in allowed_tags:
        return normalized_tag

    return DEFAULT_SAVED_TAG


class SavedProductService:
    """
    Responsabilidade:
        Gerenciar a lista persistida de produtos marcados como acesso rapido.

    Parametros:
        storage_file_path: Caminho do arquivo JSON de itens salvos.

    Retorno:
        Instancia pronta para leitura e escrita dos atalhos operacionais.

    Contexto de uso:
        Utilizada pelo dashboard para a aba de acesso rapido, para filtros de
        busca e para o toggle da acao "Adicionar ao acesso rapido".
    """

    def __init__(self, storage_file_path: Path) -> None:
        """
        Responsabilidade:
            Inicializar o servico e garantir um arquivo valido em disco.

        Parametros:
            storage_file_path: Caminho persistente do JSON de acesso rapido.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construido sob demanda pela camada web para funcionar tanto em
            ambiente local quanto no storage persistente da Railway.
        """

        self.storage_file_path = storage_file_path
        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        """
        Responsabilidade:
            Garantir que diretorio e arquivo base existam no filesystem.

        Parametros:
            Nenhum.

        Retorno:
            Nenhum.

        Contexto de uso:
            Evita falhas em ambientes novos ou apos deploy limpo.
        """

        self.storage_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_file_path.exists():
            self.storage_file_path.write_text("[]", encoding="utf-8")

    def _read_all_entries(self) -> List[SavedProductEntry]:
        """
        Responsabilidade:
            Ler o storage de acesso rapido com retrocompatibilidade estrutural.

        Parametros:
            Nenhum.

        Retorno:
            Lista ordenada de entradas tipadas do acesso rapido.

        Contexto de uso:
            O app antigo gravava apenas strings com alias. O formato novo aceita
            objetos com `alias`, `tag` e `saved_at`, sem exigir migracao manual.
        """

        try:
            raw_content = self.storage_file_path.read_text(encoding="utf-8")
            raw_items = json.loads(raw_content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de produtos salvos contem JSON invalido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de produtos salvos") from error

        if not isinstance(raw_items, list):
            raise ValueError("Arquivo de produtos salvos deve conter lista JSON")

        normalized_entries: List[SavedProductEntry] = []
        seen_aliases: Set[str] = set()
        for raw_item in raw_items:
            parsed_entry = self._parse_raw_entry(raw_item)
            if parsed_entry is None or parsed_entry.alias in seen_aliases:
                continue

            normalized_entries.append(parsed_entry)
            seen_aliases.add(parsed_entry.alias)

        return normalized_entries

    def _parse_raw_entry(self, raw_item: object) -> SavedProductEntry | None:
        """
        Responsabilidade:
            Converter uma linha bruta do JSON em uma entrada tipada e segura.

        Parametros:
            raw_item: Item bruto vindo da lista persistida em disco.

        Retorno:
            `SavedProductEntry` quando houver alias valido; caso contrario, None.

        Contexto de uso:
            Centraliza a compatibilidade entre o formato legado baseado em
            strings e o formato novo baseado em objetos.
        """

        if isinstance(raw_item, str):
            normalized_alias = raw_item.strip()
            if not normalized_alias:
                return None

            return SavedProductEntry(alias=normalized_alias, tag=DEFAULT_SAVED_TAG, saved_at="")

        if isinstance(raw_item, dict):
            normalized_alias = str(raw_item.get("alias", "")).strip()
            if not normalized_alias:
                return None

            return SavedProductEntry(
                alias=normalized_alias,
                tag=_normalize_saved_tag(str(raw_item.get("tag", DEFAULT_SAVED_TAG))),
                saved_at=str(raw_item.get("saved_at", "")).strip(),
            )

        return None

    def _write_all_entries(self, entries: List[SavedProductEntry]) -> None:
        """
        Responsabilidade:
            Persistir todas as entradas do acesso rapido de forma atomica.

        Parametros:
            entries: Lista completa de entradas que deve substituir o storage.

        Retorno:
            Nenhum.

        Contexto de uso:
            Mantem um formato unico de escrita para o schema novo, enquanto a
            leitura continua aceitando os dados antigos em lista simples.
        """

        serialized_entries = [
            {
                "alias": entry.alias,
                "tag": _normalize_saved_tag(entry.tag),
                "saved_at": entry.saved_at,
            }
            for entry in entries
        ]
        temporary_file_path = self.storage_file_path.with_suffix(".tmp")

        try:
            temporary_file_path.write_text(
                json.dumps(serialized_entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file_path.replace(self.storage_file_path)
        except OSError as error:
            raise RuntimeError("Falha ao salvar arquivo de produtos salvos") from error

    def list_entries(self) -> List[SavedProductEntry]:
        """
        Responsabilidade:
            Retornar todas as entradas do acesso rapido em ordem de persistencia.

        Parametros:
            Nenhum.

        Retorno:
            Lista tipada de itens salvos pelo operador.

        Contexto de uso:
            Base da tela de acesso rapido e de futuros resumos por tag.
        """

        return self._read_all_entries()

    def list_saved_aliases(self) -> List[str]:
        """
        Responsabilidade:
            Expor a lista simples de aliases para camadas que ainda so precisam
            da identidade operacional do produto.

        Parametros:
            Nenhum.

        Retorno:
            Lista de aliases salvos em ordem de persistencia.

        Contexto de uso:
            Preserva compatibilidade com chamadas antigas sem obrigar o resto
            do app a conhecer o schema novo imediatamente.
        """

        return [entry.alias for entry in self._read_all_entries()]

    def get_saved_aliases_set(self) -> Set[str]:
        """
        Responsabilidade:
            Expor aliases salvos em formato otimizado para membership test.

        Parametros:
            Nenhum.

        Retorno:
            Conjunto com aliases persistidos.

        Contexto de uso:
            Facilita renderizacao de listas grandes com estado de acesso rapido.
        """

        return {entry.alias for entry in self._read_all_entries()}

    def get_entries_map(self) -> Dict[str, SavedProductEntry]:
        """
        Responsabilidade:
            Montar um mapa de acesso rapido indexado por alias.

        Parametros:
            Nenhum.

        Retorno:
            Dicionario `alias -> SavedProductEntry`.

        Contexto de uso:
            Permite que a camada web recupere rapidamente tag e timestamp do
            item salvo sem varrer a lista toda a cada card.
        """

        return {entry.alias: entry for entry in self._read_all_entries()}

    def count_by_tag(self) -> Dict[str, int]:
        """
        Responsabilidade:
            Resumir quantos itens existem por tag operacional.

        Parametros:
            Nenhum.

        Retorno:
            Dicionario com contagem por tag normalizada.

        Contexto de uso:
            Base para pequenos resumos na tela de acesso rapido, sem exigir um
            painel complexo de favoritos.
        """

        tag_counts: Dict[str, int] = {}
        for entry in self._read_all_entries():
            normalized_tag = _normalize_saved_tag(entry.tag)
            tag_counts[normalized_tag] = tag_counts.get(normalized_tag, 0) + 1

        return tag_counts

    def is_saved(self, alias: str) -> bool:
        """
        Responsabilidade:
            Indicar se um alias especifico esta salvo pelo operador.

        Parametros:
            alias: Alias a ser consultado.

        Retorno:
            True quando o alias estiver presente no storage de acesso rapido.

        Contexto de uso:
            Controla o estado visual do botao "Adicionar ao acesso rapido".
        """

        normalized_alias = alias.strip()
        return normalized_alias in self.get_saved_aliases_set()

    def save_alias(self, alias: str, tag: str = DEFAULT_SAVED_TAG) -> List[str]:
        """
        Responsabilidade:
            Adicionar ou atualizar um alias no acesso rapido sem duplicacao.

        Parametros:
            alias: Alias do produto que deve entrar no acesso rapido.
            tag: Motivo operacional opcional do salvamento.

        Retorno:
            Lista atualizada de aliases salvos.

        Contexto de uso:
            Chamada pela acao explicita do operador ao marcar itens recorrentes,
            como produtos em campanha ou monitoramento.
        """

        normalized_alias = alias.strip()
        if not normalized_alias:
            return self.list_saved_aliases()

        normalized_tag = _normalize_saved_tag(tag)
        saved_entries = self._read_all_entries()
        for current_entry in saved_entries:
            if current_entry.alias != normalized_alias:
                continue

            # Decisao tecnica:
            # Quando o item ja existe, atualizamos apenas a tag operacional
            # para refletir o ultimo contexto de uso sem perder a ordem nem o
            # instante original em que ele entrou no acesso rapido.
            current_entry.tag = normalized_tag
            self._write_all_entries(saved_entries)
            return [entry.alias for entry in saved_entries]

        saved_entries.append(
            SavedProductEntry(
                alias=normalized_alias,
                tag=normalized_tag,
                saved_at=get_current_utc_isoformat(),
            )
        )
        self._write_all_entries(saved_entries)
        return [entry.alias for entry in saved_entries]

    def unsave_alias(self, alias: str) -> List[str]:
        """
        Responsabilidade:
            Remover um alias salvo sem falhar quando ele nao existir.

        Parametros:
            alias: Alias que deve deixar o acesso rapido.

        Retorno:
            Lista atualizada de aliases salvos.

        Contexto de uso:
            Utilizada pelo toggle de adicionar/remover acesso rapido.
        """

        normalized_alias = alias.strip()
        saved_entries = [entry for entry in self._read_all_entries() if entry.alias != normalized_alias]
        self._write_all_entries(saved_entries)
        return [entry.alias for entry in saved_entries]

    def toggle_alias(self, alias: str, tag: str = DEFAULT_SAVED_TAG) -> bool:
        """
        Responsabilidade:
            Alternar o estado de acesso rapido de um alias.

        Parametros:
            alias: Alias alvo da acao de toggle.
            tag: Motivo operacional opcional quando a acao terminar em salvar.

        Retorno:
            True quando o alias terminar salvo; False quando terminar removido.

        Contexto de uso:
            Acao principal do botao de acesso rapido na interface.
        """

        normalized_alias = alias.strip()
        if not normalized_alias:
            return False

        if self.is_saved(normalized_alias):
            self.unsave_alias(normalized_alias)
            return False

        self.save_alias(normalized_alias, tag=tag)
        return True

    def replace_alias(self, old_alias: str, new_alias: str) -> List[str]:
        """
        Responsabilidade:
            Migrar um alias salvo para outro quando o produto e renomeado.

        Parametros:
            old_alias: Alias antigo que deve deixar de existir na lista.
            new_alias: Novo alias que passa a representar o mesmo item.

        Retorno:
            Lista atualizada de aliases salvos apos a migracao.

        Contexto de uso:
            Evita que um produto perca o estado de acesso rapido quando o
            operador altera o alias no dashboard.
        """

        normalized_old_alias = old_alias.strip()
        normalized_new_alias = new_alias.strip()
        saved_entries = self._read_all_entries()

        if not normalized_old_alias or not normalized_new_alias:
            return [entry.alias for entry in saved_entries]

        if normalized_old_alias == normalized_new_alias:
            return [entry.alias for entry in saved_entries]

        migrated_entries: List[SavedProductEntry] = []
        has_inserted_new_alias = False
        existing_new_entry = next(
            (entry for entry in saved_entries if entry.alias == normalized_new_alias),
            None,
        )

        for current_entry in saved_entries:
            if current_entry.alias == normalized_old_alias:
                if not has_inserted_new_alias:
                    migrated_entries.append(
                        SavedProductEntry(
                            alias=normalized_new_alias,
                            tag=(existing_new_entry.tag if existing_new_entry else current_entry.tag),
                            saved_at=(existing_new_entry.saved_at if existing_new_entry else current_entry.saved_at),
                        )
                    )
                    has_inserted_new_alias = True
                continue

            if current_entry.alias == normalized_new_alias:
                if not has_inserted_new_alias:
                    migrated_entries.append(current_entry)
                    has_inserted_new_alias = True
                continue

            migrated_entries.append(current_entry)

        self._write_all_entries(migrated_entries)
        return [entry.alias for entry in migrated_entries]
