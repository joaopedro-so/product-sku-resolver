"""
Serviço de jobs assíncronos para sincronização em lote do catálogo.

Este módulo mantém um estado leve em memória para que a interface web consiga:
- iniciar o sync sem bloquear a requisição
- acompanhar progresso por `job_id`
- reaproveitar o mesmo snapshot ao trocar de aba ou recarregar a tela
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from threading import RLock, Thread
from uuid import uuid4
from typing import Callable, Optional

from backend.services.datetime_service import get_current_utc_isoformat
from monitoring.monitor_service import (
    MonitorProgressUpdate,
    MonitorRunPlan,
    MonitorRunSummary,
    MonitorService,
)


@dataclass(slots=True)
class SyncJobSnapshot:
    """
    Responsabilidade:
        Representar o estado observável de um job de sincronização em lote.

    Parâmetros:
        job_id: Identificador único do job em execução ou já concluído.
        status: Estado atual (`queued`, `running`, `completed` ou `failed`).
        total: Total de itens programados para processamento.
        processed: Quantidade concluída até o momento.
        updated: Quantidade concluída com alteração detectada.
        unchanged: Quantidade concluída sem mudança.
        failed: Quantidade concluída com falha.
        skipped: Quantidade ignorada antes do processamento.
        current_item: Nome do item em foco no momento.
        started_at: Timestamp UTC do início do job.
        finished_at: Timestamp UTC do encerramento, quando existir.
        error_message: Erro fatal do job, quando houver.

    Retorno:
        Snapshot leve e serializável para a camada web.

    Contexto de uso:
        O dashboard lê esse snapshot periodicamente para desenhar a barra de
        progresso e transmitir confiança durante o sync em lote.
    """

    job_id: str
    status: str
    total: int
    processed: int
    updated: int
    unchanged: int
    failed: int
    skipped: int
    current_item: str
    started_at: str
    finished_at: str = ""
    error_message: str = ""


class SyncJobService:
    """
    Responsabilidade:
        Orquestrar jobs assíncronos de sincronização com progresso consultável.

    Parâmetros:
        monitor_service: Serviço de monitoramento reutilizado pelo job.
        on_job_finished: Callback opcional executado ao final do lote.
        max_workers: Limite seguro de paralelismo por rodada.
        skip_recent_seconds: Janela opcional para pular itens recentes.

    Retorno:
        Serviço pronto para iniciar, observar e reaproveitar jobs.

    Contexto de uso:
        A camada web do dashboard usa esse serviço para transformar o antigo
        POST bloqueante em um fluxo assíncrono com polling e progresso real.
    """

    def __init__(
        self,
        monitor_service: MonitorService,
        on_job_finished: Optional[Callable[[MonitorRunSummary, SyncJobSnapshot], None]] = None,
        max_workers: int = 6,
        skip_recent_seconds: int = 0,
    ) -> None:
        """
        Responsabilidade:
            Guardar dependências e inicializar o estado interno do orquestrador.

        Parâmetros:
            monitor_service: Serviço que executa o sync real dos produtos.
            on_job_finished: Callback opcional para snapshot final persistido.
            max_workers: Quantidade máxima de workers por rodada.
            skip_recent_seconds: Janela opcional de skip para itens recentes.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construído uma vez por processo e reutilizado entre várias visitas
            ao dashboard, mantendo o progresso estável durante a sessão.
        """

        self.monitor_service = monitor_service
        self.on_job_finished = on_job_finished
        self.max_workers = max(1, int(max_workers))
        self.skip_recent_seconds = max(0, int(skip_recent_seconds))
        self._jobs_by_id: dict[str, SyncJobSnapshot] = {}
        self._active_job_id = ""
        self._latest_job_id = ""
        self._jobs_lock = RLock()

    def start_job(self) -> tuple[SyncJobSnapshot, bool]:
        """
        Responsabilidade:
            Iniciar um novo job ou reaproveitar o job ativo quando já existir.

        Parâmetros:
            Nenhum.

        Retorno:
            Tupla com o snapshot inicial e um booleano indicando se o job foi
            realmente criado nesta chamada.

        Contexto de uso:
            O frontend chama esse método ao clicar em `Atualizar todos` e usa o
            `job_id` retornado para começar o polling de progresso.
        """

        with self._jobs_lock:
            active_snapshot = self._resolve_active_snapshot()
            if active_snapshot is not None:
                return replace(active_snapshot), False

            run_plan = self.monitor_service.build_run_plan(
                skip_recent_seconds=self.skip_recent_seconds,
            )
            job_id = uuid4().hex
            snapshot = SyncJobSnapshot(
                job_id=job_id,
                status="queued",
                total=run_plan.total_count,
                processed=0,
                updated=0,
                unchanged=0,
                failed=0,
                skipped=run_plan.skipped_count,
                current_item="",
                started_at=get_current_utc_isoformat(),
            )
            self._jobs_by_id[job_id] = snapshot
            self._active_job_id = job_id
            self._latest_job_id = job_id

        worker_thread = Thread(
            target=self._run_job_in_background,
            args=(job_id, run_plan),
            name=f"sync-job-{job_id[:8]}",
            daemon=True,
        )
        worker_thread.start()
        return replace(snapshot), True

    def get_job_snapshot(self, job_id: str) -> Optional[SyncJobSnapshot]:
        """
        Responsabilidade:
            Consultar o snapshot de um job específico por identificador.

        Parâmetros:
            job_id: Identificador do job retornado no start.

        Retorno:
            Snapshot copiado do job quando ele existir; senão None.

        Contexto de uso:
            Endpoint de polling consulta este método para desenhar a evolução
            sem expor referências mutáveis do estado interno.
        """

        normalized_job_id = str(job_id).strip()
        if not normalized_job_id:
            return None

        with self._jobs_lock:
            snapshot = self._jobs_by_id.get(normalized_job_id)
            return replace(snapshot) if snapshot is not None else None

    def get_preferred_snapshot(self, preferred_job_id: str = "") -> Optional[SyncJobSnapshot]:
        """
        Responsabilidade:
            Resolver qual snapshot a UI deve mostrar ao abrir a tela de updates.

        Parâmetros:
            preferred_job_id: Job explicitamente pedido pela query string, quando existir.

        Retorno:
            Snapshot do job pedido, do job ativo ou do job mais recente.

        Contexto de uso:
            Permite que a página de updates continue mostrando progresso mesmo
            após recarregar, trocar de aba ou voltar para a tela mais tarde.
        """

        normalized_job_id = str(preferred_job_id).strip()
        with self._jobs_lock:
            if normalized_job_id and normalized_job_id in self._jobs_by_id:
                return replace(self._jobs_by_id[normalized_job_id])

            active_snapshot = self._resolve_active_snapshot()
            if active_snapshot is not None:
                return replace(active_snapshot)

            latest_snapshot = self._jobs_by_id.get(self._latest_job_id)
            return replace(latest_snapshot) if latest_snapshot is not None else None

    def _run_job_in_background(self, job_id: str, run_plan: MonitorRunPlan) -> None:
        """
        Responsabilidade:
            Executar o job em thread própria e atualizar o snapshot em memória.

        Parâmetros:
            job_id: Identificador do job que está sendo processado.
            run_plan: Plano já calculado para o lote atual.

        Retorno:
            Nenhum.

        Contexto de uso:
            Isola a execução longa da requisição web, permitindo que o frontend
            consulte progresso por polling sem manter a conexão inicial aberta.
        """

        self._update_snapshot(
            job_id=job_id,
            status="running",
            current_item="Preparando sincronização...",
        )

        try:
            summary = self.monitor_service.run_plan(
                run_plan=run_plan,
                max_workers=self.max_workers,
                progress_callback=lambda progress: self._handle_progress_update(job_id, progress),
            )
            finished_snapshot = self._update_snapshot(
                job_id=job_id,
                status="completed",
                processed=summary.processed_count,
                updated=summary.updated_count,
                unchanged=summary.unchanged_count,
                failed=summary.failed_count,
                current_item="",
                finished_at=get_current_utc_isoformat(),
                error_message="",
            )
            if finished_snapshot is not None and self.on_job_finished is not None:
                self.on_job_finished(summary, finished_snapshot)
        except Exception as error:  # pragma: no cover - proteção operacional
            self._update_snapshot(
                job_id=job_id,
                status="failed",
                current_item="",
                finished_at=get_current_utc_isoformat(),
                error_message=str(error),
            )
        finally:
            with self._jobs_lock:
                if self._active_job_id == job_id:
                    self._active_job_id = ""

    def _handle_progress_update(self, job_id: str, progress: MonitorProgressUpdate) -> None:
        """
        Responsabilidade:
            Traduzir callbacks do monitor em atualização persistente do snapshot.

        Parâmetros:
            job_id: Identificador do job dono do progresso recebido.
            progress: Snapshot incremental emitido pelo monitor.

        Retorno:
            Nenhum.

        Contexto de uso:
            Mantém o estado da UI centralizado em um único lugar, sem deixar a
            camada web reconstruir contadores a partir de vários eventos soltos.
        """

        current_item = progress.current_item
        if progress.stage == "finished" and progress.item_status:
            current_item = progress.product_name

        self._update_snapshot(
            job_id=job_id,
            status="running",
            processed=progress.processed_count,
            updated=progress.updated_count,
            unchanged=progress.unchanged_count,
            failed=progress.failed_count,
            current_item=current_item,
        )

    def _update_snapshot(
        self,
        job_id: str,
        status: str,
        processed: Optional[int] = None,
        updated: Optional[int] = None,
        unchanged: Optional[int] = None,
        failed: Optional[int] = None,
        current_item: Optional[str] = None,
        finished_at: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Optional[SyncJobSnapshot]:
        """
        Responsabilidade:
            Atualizar parcialmente o snapshot de um job de forma thread-safe.

        Parâmetros:
            job_id: Identificador do job a ser alterado.
            status: Novo estado geral do job.
            processed: Novo valor opcional de itens processados.
            updated: Novo valor opcional de itens alterados.
            unchanged: Novo valor opcional de itens sem mudança.
            failed: Novo valor opcional de itens com falha.
            current_item: Novo item em foco da UI.
            finished_at: Timestamp opcional de término.
            error_message: Mensagem opcional de erro fatal do job.

        Retorno:
            Snapshot atualizado, quando o job existir.

        Contexto de uso:
            Centraliza todas as mutações do estado do job e evita divergência
            entre contadores, texto atual e status geral no polling.
        """

        with self._jobs_lock:
            current_snapshot = self._jobs_by_id.get(job_id)
            if current_snapshot is None:
                return None

            updated_snapshot = replace(
                current_snapshot,
                status=status,
                processed=current_snapshot.processed if processed is None else processed,
                updated=current_snapshot.updated if updated is None else updated,
                unchanged=current_snapshot.unchanged if unchanged is None else unchanged,
                failed=current_snapshot.failed if failed is None else failed,
                current_item=current_snapshot.current_item if current_item is None else current_item,
                finished_at=current_snapshot.finished_at if finished_at is None else finished_at,
                error_message=current_snapshot.error_message if error_message is None else error_message,
            )
            self._jobs_by_id[job_id] = updated_snapshot
            self._latest_job_id = job_id
            return replace(updated_snapshot)

    def _resolve_active_snapshot(self) -> Optional[SyncJobSnapshot]:
        """
        Responsabilidade:
            Encontrar o job que ainda está ativo dentro do serviço.

        Parâmetros:
            Nenhum.

        Retorno:
            Snapshot do job ativo quando existir; senão None.

        Contexto de uso:
            Impede que o usuário inicie múltiplas rodadas concorrentes sem
            necessidade e mantém a UX mais previsível na tela de updates.
        """

        if not self._active_job_id:
            return None

        active_snapshot = self._jobs_by_id.get(self._active_job_id)
        if active_snapshot is None:
            self._active_job_id = ""
            return None

        if active_snapshot.status not in {"queued", "running"}:
            self._active_job_id = ""
            return None

        return active_snapshot


def build_sync_job_service(
    monitor_service: MonitorService,
    on_job_finished: Optional[Callable[[MonitorRunSummary, SyncJobSnapshot], None]] = None,
) -> SyncJobService:
    """
    Responsabilidade:
        Construir o serviço de job usando configuração do ambiente atual.

    Parâmetros:
        monitor_service: Serviço de monitoramento usado pelo job.
        on_job_finished: Callback opcional para snapshot final persistido.

    Retorno:
        SyncJobService configurado com limites seguros de paralelismo.

    Contexto de uso:
        Evita espalhar leitura de environment variables pelas rotas web e
        mantém a política operacional do sync concentrada em um único lugar.
    """

    max_workers = _read_positive_int_env("SYNC_JOB_MAX_WORKERS", default_value=6)
    skip_recent_seconds = _read_non_negative_int_env("SYNC_SKIP_RECENT_SECONDS", default_value=0)
    return SyncJobService(
        monitor_service=monitor_service,
        on_job_finished=on_job_finished,
        max_workers=max_workers,
        skip_recent_seconds=skip_recent_seconds,
    )


def _read_positive_int_env(environment_name: str, default_value: int) -> int:
    """
    Responsabilidade:
        Ler um inteiro positivo do ambiente com fallback seguro.

    Parâmetros:
        environment_name: Nome da variável de ambiente consultada.
        default_value: Valor usado quando o ambiente vier vazio ou inválido.

    Retorno:
        Inteiro sempre positivo e pronto para uso operacional.

    Contexto de uso:
        A concorrência do job não pode depender de parsing espalhado nem de
        valores negativos inválidos vindos da infraestrutura.
    """

    raw_value = os.getenv(environment_name, "").strip()
    if not raw_value:
        return max(1, int(default_value))

    try:
        parsed_value = int(raw_value)
    except ValueError:
        return max(1, int(default_value))

    return max(1, parsed_value)


def _read_non_negative_int_env(environment_name: str, default_value: int) -> int:
    """
    Responsabilidade:
        Ler um inteiro não negativo do ambiente com fallback seguro.

    Parâmetros:
        environment_name: Nome da variável de ambiente consultada.
        default_value: Valor usado quando o ambiente vier vazio ou inválido.

    Retorno:
        Inteiro sempre maior ou igual a zero.

    Contexto de uso:
        O skip de itens recentes é opcional. Por isso o helper aceita zero como
        valor legítimo e protege o serviço contra configurações inválidas.
    """

    raw_value = os.getenv(environment_name, "").strip()
    if not raw_value:
        return max(0, int(default_value))

    try:
        parsed_value = int(raw_value)
    except ValueError:
        return max(0, int(default_value))

    return max(0, parsed_value)
