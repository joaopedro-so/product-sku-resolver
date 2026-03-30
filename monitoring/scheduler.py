"""
Scheduler simples para execução periódica do monitoramento automático.

Este módulo oferece loop controlado com intervalos configuráveis e proteção
contra execução infinita não intencional via limites opcionais.
"""

from __future__ import annotations

import logging
import time
from threading import Event
from typing import Optional

from config import MONITOR_INTERVAL_MINUTES
from monitoring.monitor_service import MonitorService


class MonitorScheduler:
    """
    Responsabilidade:
        Executar monitoramento em loop com pausa entre ciclos.

    Parâmetros:
        monitor_service: Serviço responsável por executar cada ciclo.
        interval_minutes: Intervalo entre ciclos de execução.

    Retorno:
        Scheduler configurado para execução contínua controlada.

    Contexto de uso:
        Pode ser acionado por processo dedicado de monitoramento.
    """

    def __init__(self, monitor_service: MonitorService, interval_minutes: int = MONITOR_INTERVAL_MINUTES) -> None:
        """
        Responsabilidade:
            Configurar scheduler com dependências e intervalo de execução.

        Parâmetros:
            monitor_service: Serviço que processa um ciclo de monitoramento.
            interval_minutes: Minutos de espera entre ciclos consecutivos.

        Retorno:
            Nenhum.

        Contexto de uso:
            Instanciado por camada operacional para iniciar loop agendado.
        """

        self.monitor_service = monitor_service
        self.interval_seconds = max(1, interval_minutes) * 60
        self.logger = logging.getLogger(__name__)

    def run_forever(self, stop_event: Optional[Event] = None, max_cycles: Optional[int] = None) -> None:
        """
        Responsabilidade:
            Executar loop de monitoramento até sinal de parada ou limite.

        Parâmetros:
            stop_event: Evento opcional para parada graciosa do loop.
            max_cycles: Limite opcional de ciclos para proteção adicional.

        Retorno:
            Nenhum.

        Contexto de uso:
            Utilizado em execução contínua de monitoramento automático.
        """

        executed_cycles = 0
        local_stop_event = stop_event or Event()

        while not local_stop_event.is_set():
            # Regra de negócio:
            # max_cycles permite rodar em modo controlado em ambientes de teste
            # e evita loop infinito acidental em integrações operacionais.
            if max_cycles is not None and executed_cycles >= max_cycles:
                self.logger.info("Scheduler encerrado por max_cycles=%s", max_cycles)
                break

            try:
                summary = self.monitor_service.run()
                self.logger.info(
                    "Ciclo monitoramento concluído: processados=%s sucesso=%s erros=%s eventos=%s",
                    summary.processed_count,
                    summary.success_count,
                    summary.error_count,
                    len(summary.emitted_events),
                )
            except Exception as error:
                # Tratamento de erro:
                # Não quebramos o loop por falhas pontuais; registramos e
                # aguardamos próximo ciclo para aumentar resiliência.
                self.logger.exception("Falha inesperada no ciclo de monitoramento: %s", error)

            executed_cycles += 1
            time.sleep(self.interval_seconds)
