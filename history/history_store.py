"""
Persistência e consulta de histórico de eventos de SKU.

Este módulo salva eventos em JSON para auditoria operacional do monitoramento.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from backend.models.sku_event import SkuEvent


class HistoryStore:
    """
    Responsabilidade:
        Salvar e consultar eventos de histórico em arquivo JSON.

    Parâmetros:
        history_file_path: Caminho do arquivo de histórico de eventos.

    Retorno:
        Serviço pronto para registrar e consultar eventos de monitoramento.

    Contexto de uso:
        Usado por monitor_service, API e CLI para auditoria operacional.
    """

    def __init__(self, history_file_path: Path) -> None:
        """
        Responsabilidade:
            Inicializar serviço e garantir arquivo de histórico existente.

        Parâmetros:
            history_file_path: Arquivo JSON de eventos.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construído no bootstrap para evitar falhas de primeira execução.
        """

        self.history_file_path = history_file_path
        self._ensure_history_exists()

    def _ensure_history_exists(self) -> None:
        """
        Responsabilidade:
            Garantir diretório e arquivo base do histórico no disco.

        Parâmetros:
            Nenhum.

        Retorno:
            Nenhum.

        Contexto de uso:
            Evita erros de IO em ambientes recém-inicializados.
        """

        self.history_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.history_file_path.exists():
            self.history_file_path.write_text("[]", encoding="utf-8")

    def _read_all(self) -> List[SkuEvent]:
        """
        Responsabilidade:
            Ler todos os eventos persistidos com validação estrutural.

        Parâmetros:
            Nenhum.

        Retorno:
            Lista de SkuEvent carregada do armazenamento.

        Contexto de uso:
            Base para operações de listagem geral e filtro por alias.
        """

        try:
            raw_content = self.history_file_path.read_text(encoding="utf-8")
            raw_items = json.loads(raw_content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de histórico contém JSON inválido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de histórico") from error

        if not isinstance(raw_items, list):
            raise ValueError("Arquivo de histórico deve conter lista JSON")

        events: List[SkuEvent] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            events.append(SkuEvent.from_dict(raw_item))

        return events

    def _write_all(self, events: List[SkuEvent]) -> None:
        """
        Responsabilidade:
            Persistir eventos em escrita atômica simplificada.

        Parâmetros:
            events: Lista completa de eventos a ser gravada.

        Retorno:
            Nenhum.

        Contexto de uso:
            Método interno de persistência chamado por save_event.
        """

        payload = [event.to_dict() for event in events]
        temporary_file_path = self.history_file_path.with_suffix(".tmp")

        try:
            temporary_file_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file_path.replace(self.history_file_path)
        except OSError as error:
            raise RuntimeError("Falha ao salvar arquivo de histórico") from error

    def save_event(self, event: SkuEvent) -> SkuEvent:
        """
        Responsabilidade:
            Adicionar novo evento ao final do histórico persistido.

        Parâmetros:
            event: Evento de monitoramento que será registrado.

        Retorno:
            O próprio evento persistido para encadeamento opcional.

        Contexto de uso:
            Chamado pelo monitor_service ao detectar mudanças ou erros.
        """

        events = self._read_all()
        events.append(event)
        self._write_all(events)
        return event

    def list_events(self) -> List[SkuEvent]:
        """
        Responsabilidade:
            Retornar todos os eventos históricos em ordem de persistência.

        Parâmetros:
            Nenhum.

        Retorno:
            Lista completa de SkuEvent.

        Contexto de uso:
            Usado por API/CLI para visualização geral de auditoria.
        """

        return self._read_all()

    def list_events_by_alias(self, alias: str) -> List[SkuEvent]:
        """
        Responsabilidade:
            Filtrar eventos históricos de um produto específico por alias.

        Parâmetros:
            alias: Alias do produto de interesse para filtragem.

        Retorno:
            Lista de SkuEvent relacionados ao alias informado.

        Contexto de uso:
            Usado por API/CLI para investigações pontuais de produto.
        """

        normalized_alias = alias.strip()
        return [event for event in self._read_all() if event.alias == normalized_alias]
