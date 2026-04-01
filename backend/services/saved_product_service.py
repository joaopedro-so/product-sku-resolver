"""
Servico de persistencia para atalhos de produtos salvos.

Este modulo mantem uma lista simples de aliases favoritos para alimentar a
area "Saved" do dashboard mobile-first sem alterar o schema principal
dos produtos monitorados.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Set


class SavedProductService:
    """
    Responsabilidade:
        Gerenciar lista persistida de aliases salvos pelo operador.

    Parametros:
        storage_file_path: Caminho do arquivo JSON de produtos salvos.

    Retorno:
        Instancia pronta para leitura e escrita dos atalhos.

    Contexto de uso:
        Utilizada pelo dashboard para a aba Saved e para a acao de salvar.
    """

    def __init__(self, storage_file_path: Path) -> None:
        """
        Responsabilidade:
            Inicializar o servico e garantir arquivo valido em disco.

        Parametros:
            storage_file_path: Caminho persistente dos aliases salvos.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construido no primeiro acesso da camada web para evitar setup manual.
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

    def _read_all(self) -> List[str]:
        """
        Responsabilidade:
            Ler aliases salvos do arquivo com validacao estrutural simples.

        Parametros:
            Nenhum.

        Retorno:
            Lista ordenada de aliases persistidos.

        Contexto de uso:
            Base para consultas da aba Saved e operacoes de toggle.
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

        normalized_aliases = []
        for raw_item in raw_items:
            normalized_alias = str(raw_item).strip()
            if normalized_alias:
                normalized_aliases.append(normalized_alias)

        return normalized_aliases

    def _write_all(self, aliases: List[str]) -> None:
        """
        Responsabilidade:
            Persistir aliases salvos em escrita atomica simplificada.

        Parametros:
            aliases: Lista completa de aliases a ser gravada.

        Retorno:
            Nenhum.

        Contexto de uso:
            Metodo interno usado por save, unsave e toggle.
        """

        temporary_file_path = self.storage_file_path.with_suffix(".tmp")

        try:
            temporary_file_path.write_text(
                json.dumps(aliases, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file_path.replace(self.storage_file_path)
        except OSError as error:
            raise RuntimeError("Falha ao salvar arquivo de produtos salvos") from error

    def list_saved_aliases(self) -> List[str]:
        """
        Responsabilidade:
            Retornar todos os aliases salvos em ordem de persistencia.

        Parametros:
            Nenhum.

        Retorno:
            Lista de aliases salvos.

        Contexto de uso:
            Usada para montar a tela Saved e destacar itens em outras listas.
        """

        return self._read_all()

    def get_saved_aliases_set(self) -> Set[str]:
        """
        Responsabilidade:
            Expor aliases salvos em formato otimizado para membership test.

        Parametros:
            Nenhum.

        Retorno:
            Conjunto com aliases persistidos.

        Contexto de uso:
            Facilita renderizacao de listas grandes com badge de salvo.
        """

        return set(self._read_all())

    def is_saved(self, alias: str) -> bool:
        """
        Responsabilidade:
            Indicar se um alias especifico esta salvo pelo operador.

        Parametros:
            alias: Alias a ser consultado.

        Retorno:
            True quando o alias estiver presente no storage de salvos.

        Contexto de uso:
            Utilizada no dashboard para controlar estado visual do botao salvar.
        """

        normalized_alias = alias.strip()
        return normalized_alias in self.get_saved_aliases_set()

    def save_alias(self, alias: str) -> List[str]:
        """
        Responsabilidade:
            Adicionar alias a lista de salvos sem duplicacao.

        Parametros:
            alias: Alias do produto que deve virar atalho salvo.

        Retorno:
            Lista atualizada de aliases salvos.

        Contexto de uso:
            Chamada por acoes explicitas de salvar no dashboard.
        """

        normalized_alias = alias.strip()
        if not normalized_alias:
            return self._read_all()

        saved_aliases = self._read_all()
        if normalized_alias not in saved_aliases:
            saved_aliases.append(normalized_alias)
            self._write_all(saved_aliases)

        return saved_aliases

    def unsave_alias(self, alias: str) -> List[str]:
        """
        Responsabilidade:
            Remover alias salvo sem falhar quando ele nao existir.

        Parametros:
            alias: Alias que deve deixar a lista de atalhos.

        Retorno:
            Lista atualizada de aliases salvos.

        Contexto de uso:
            Utilizada pelo toggle de salvar/desalvar produtos.
        """

        normalized_alias = alias.strip()
        saved_aliases = [saved_alias for saved_alias in self._read_all() if saved_alias != normalized_alias]
        self._write_all(saved_aliases)
        return saved_aliases

    def toggle_alias(self, alias: str) -> bool:
        """
        Responsabilidade:
            Alternar estado salvo/desalvado de um alias.

        Parametros:
            alias: Alias alvo da acao de toggle.

        Retorno:
            True quando o alias terminar salvo; False quando terminar removido.

        Contexto de uso:
            Acao principal do botao Save na interface mobile-first.
        """

        normalized_alias = alias.strip()
        if not normalized_alias:
            return False

        if self.is_saved(normalized_alias):
            self.unsave_alias(normalized_alias)
            return False

        self.save_alias(normalized_alias)
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
            Utilizada pelo fluxo de edicao do dashboard para evitar que um
            produto perca o estado de salvo quando o operador altera o alias.
        """

        normalized_old_alias = old_alias.strip()
        normalized_new_alias = new_alias.strip()
        saved_aliases = self._read_all()

        if not normalized_old_alias or not normalized_new_alias:
            return saved_aliases

        if normalized_old_alias == normalized_new_alias:
            return saved_aliases

        migrated_aliases: List[str] = []
        has_inserted_new_alias = False

        for current_alias in saved_aliases:
            if current_alias in {normalized_old_alias, normalized_new_alias}:
                # Decisao tecnica:
                # Se o alias antigo ja estava salvo, trocamos pelo novo sem
                # duplicar a entrada caso o alias novo ja tenha aparecido por
                # outro fluxo operacional ou por tentativa anterior de migracao.
                if not has_inserted_new_alias:
                    migrated_aliases.append(normalized_new_alias)
                    has_inserted_new_alias = True
                continue

            migrated_aliases.append(current_alias)

        self._write_all(migrated_aliases)
        return migrated_aliases
