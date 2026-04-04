"""
Serviços utilitários para data e hora com timezone explícito.

Este módulo centraliza a política temporal do projeto para evitar dependência
implícita do timezone do container, do servidor local ou do processo atual.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DISPLAY_TIMEZONE_NAME = "America/Sao_Paulo"
UTC_TIMEZONE = timezone.utc
SAO_PAULO_FALLBACK_TIMEZONE = timezone(
    timedelta(hours=-3),
    name=DEFAULT_DISPLAY_TIMEZONE_NAME,
)


def ensure_process_timezone_environment() -> None:
    """
    Responsabilidade:
        Ajustar a variável de ambiente `TZ` do processo quando ela não vier
        configurada, favorecendo o fuso operacional esperado pela aplicação.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Funciona como reforço de infraestrutura para logs, ferramentas e
        dependências que ainda consultem o timezone do processo. Mesmo assim,
        a aplicação não deve depender disso para exibir horários corretos.
    """

    if not os.getenv("TZ", "").strip():
        os.environ["TZ"] = DEFAULT_DISPLAY_TIMEZONE_NAME

    if hasattr(time, "tzset"):
        time.tzset()


def get_display_timezone() -> tzinfo:
    """
    Responsabilidade:
        Resolver o timezone de exibição usado pela interface operacional.

    Parâmetros:
        Nenhum.

    Retorno:
        Objeto de timezone configurado a partir de `TZ` ou, como padrão seguro,
        `America/Sao_Paulo`.

    Contexto de uso:
        Toda conversão para texto visível ao usuário deve passar por este
        helper para impedir diferenças entre Railway, ambiente local e testes.
    """

    configured_timezone_name = os.getenv("TZ", "").strip() or DEFAULT_DISPLAY_TIMEZONE_NAME

    try:
        return ZoneInfo(configured_timezone_name)
    except ZoneInfoNotFoundError:
        if configured_timezone_name != DEFAULT_DISPLAY_TIMEZONE_NAME:
            try:
                return ZoneInfo(DEFAULT_DISPLAY_TIMEZONE_NAME)
            except ZoneInfoNotFoundError:
                return SAO_PAULO_FALLBACK_TIMEZONE

        return SAO_PAULO_FALLBACK_TIMEZONE


def get_current_utc_datetime() -> datetime:
    """
    Responsabilidade:
        Fornecer o instante atual já normalizado para UTC e timezone-aware.

    Parâmetros:
        Nenhum.

    Retorno:
        Datetime aware em UTC.

    Contexto de uso:
        Centraliza a criação de timestamps persistidos, facilitando testes e
        garantindo consistência entre histórico, reconciliação e cache.
    """

    return datetime.now(UTC_TIMEZONE)


def get_current_utc_isoformat() -> str:
    """
    Responsabilidade:
        Gerar timestamp ISO8601 padronizado em UTC para persistência.

    Parâmetros:
        Nenhum.

    Retorno:
        String ISO8601 timezone-aware em UTC.

    Contexto de uso:
        Usado em qualquer gravação de data/hora do domínio para que o storage
        permaneça estável e independente do timezone do servidor.
    """

    return get_current_utc_datetime().isoformat()


def parse_persisted_timestamp(raw_timestamp: Optional[str]) -> Optional[datetime]:
    """
    Responsabilidade:
        Interpretar timestamps persistidos de forma tolerante e segura.

    Parâmetros:
        raw_timestamp: Texto ISO8601 vindo de JSON, histórico ou snapshots.

    Retorno:
        Datetime timezone-aware em UTC quando o parse for válido; senão None.

    Contexto de uso:
        Alguns registros antigos podem ter sido persistidos sem timezone. Nesses
        casos, assumimos UTC para impedir que `astimezone()` use o fuso local do
        processo e desloque o horário de forma incorreta.
    """

    normalized_timestamp = str(raw_timestamp or "").strip()
    if not normalized_timestamp:
        return None

    try:
        parsed_timestamp = datetime.fromisoformat(normalized_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed_timestamp.tzinfo is None:
        return parsed_timestamp.replace(tzinfo=UTC_TIMEZONE)

    return parsed_timestamp.astimezone(UTC_TIMEZONE)


def convert_utc_timestamp_to_display(raw_timestamp: Optional[str]) -> Optional[datetime]:
    """
    Responsabilidade:
        Converter um timestamp persistido para o fuso operacional de exibição.

    Parâmetros:
        raw_timestamp: Texto ISO8601 armazenado internamente em UTC.

    Retorno:
        Datetime timezone-aware no fuso de exibição; senão None.

    Contexto de uso:
        Alimenta labels do dashboard como “Hoje 14:30” e “Última sincronização”
        sem depender do timezone local do container.
    """

    parsed_timestamp = parse_persisted_timestamp(raw_timestamp)
    if parsed_timestamp is None:
        return None

    return parsed_timestamp.astimezone(get_display_timezone())


def format_operational_timestamp_label(raw_timestamp: Optional[str]) -> str:
    """
    Responsabilidade:
        Traduzir um timestamp persistido em um rótulo curto orientado à operação.

    Parâmetros:
        raw_timestamp: Texto ISO8601 persistido em UTC.

    Retorno:
        Texto curto como “Hoje 14:20”, “Ontem 09:10” ou “Sem sincronização recente”.

    Contexto de uso:
        Reutilizado nas telas do dashboard para manter consistência sem repetir
        regras de timezone e de linguagem de data em vários módulos.
    """

    localized_timestamp = convert_utc_timestamp_to_display(raw_timestamp)
    if localized_timestamp is None:
        return "Sem sincronização recente"

    localized_now = get_current_utc_datetime().astimezone(get_display_timezone())
    if localized_timestamp.date() == localized_now.date():
        return f"Hoje {localized_timestamp:%H:%M}"

    if (localized_now.date() - localized_timestamp.date()).days == 1:
        return f"Ontem {localized_timestamp:%H:%M}"

    return localized_timestamp.strftime("%d/%m %H:%M")


def is_timestamp_in_display_today(raw_timestamp: Optional[str]) -> bool:
    """
    Responsabilidade:
        Informar se um timestamp pertence ao dia corrente no fuso operacional.

    Parâmetros:
        raw_timestamp: Texto ISO8601 persistido em UTC.

    Retorno:
        `True` quando o timestamp estiver no mesmo dia local de exibição;
        `False` nos demais casos.

    Contexto de uso:
        Utilizado por contadores, badges e filtros rápidos que dependem da
        noção de “hoje” da loja, e não da infraestrutura onde o app roda.
    """

    localized_timestamp = convert_utc_timestamp_to_display(raw_timestamp)
    if localized_timestamp is None:
        return False

    localized_now = get_current_utc_datetime().astimezone(get_display_timezone())
    return localized_timestamp.date() == localized_now.date()
