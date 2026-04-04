"""
Testes de normalização temporal com UTC interno e exibição em São Paulo.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services import datetime_service


def test_parse_persisted_timestamp_assume_utc_para_valor_ingenuo() -> None:
    """
    Responsabilidade:
        Garantir que timestamps antigos sem timezone passem a ser lidos como UTC.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum; valida o parse timezone-aware do helper central.

    Contexto de uso:
        Protege dados legados que podem ter sido gravados como ISO ingênuo e
        hoje não podem mais depender do timezone do container para interpretação.
    """

    parsed_timestamp = datetime_service.parse_persisted_timestamp("2026-04-04T03:15:00")

    assert parsed_timestamp is not None
    assert parsed_timestamp.tzinfo == timezone.utc
    assert parsed_timestamp.isoformat() == "2026-04-04T03:15:00+00:00"


def test_convert_utc_timestamp_to_display_usa_sao_paulo_por_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Responsabilidade:
        Garantir que a exibição use São Paulo mesmo sem depender do timezone local.

    Parâmetros:
        monkeypatch: Fixture do pytest usada para controlar a variável `TZ`.

    Retorno:
        Nenhum; valida a conversão explícita para o fuso operacional.

    Contexto de uso:
        Reproduz o cenário de deploy em container UTC, onde a interface ainda
        precisa mostrar o horário correto da loja no Brasil.
    """

    monkeypatch.delenv("TZ", raising=False)

    localized_timestamp = datetime_service.convert_utc_timestamp_to_display("2026-04-04T03:15:00+00:00")

    assert localized_timestamp is not None
    assert localized_timestamp.strftime("%Y-%m-%d %H:%M") == "2026-04-04 00:15"
    assert localized_timestamp.tzinfo is not None


def test_format_operational_timestamp_label_respeita_hoje_em_sao_paulo(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Responsabilidade:
        Garantir que o rótulo "Hoje" use a virada de dia de São Paulo.

    Parâmetros:
        monkeypatch: Fixture do pytest usada para congelar o "agora" em UTC.

    Retorno:
        Nenhum; valida o rótulo operacional produzido para a interface.

    Contexto de uso:
        Protege labels como "Atualizado hoje" e "Última sincronização", que
        precisam seguir o horário da loja e não o horário do servidor.
    """

    monkeypatch.setattr(
        datetime_service,
        "get_current_utc_datetime",
        lambda: datetime(2026, 4, 4, 14, 0, tzinfo=timezone.utc),
    )

    formatted_label = datetime_service.format_operational_timestamp_label("2026-04-04T13:30:00+00:00")

    assert formatted_label == "Hoje 10:30"


def test_is_timestamp_in_display_today_respeita_fronteira_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Responsabilidade:
        Garantir que a noção de "hoje" siga São Paulo perto da meia-noite UTC.

    Parâmetros:
        monkeypatch: Fixture do pytest usada para congelar o horário atual.

    Retorno:
        Nenhum; valida o helper usado por filtros e contadores de recência.

    Contexto de uso:
        Evita que um evento de madrugada UTC apareça como "hoje" ou "ontem"
        errado quando convertido para o horário da operação no Brasil.
    """

    monkeypatch.setattr(
        datetime_service,
        "get_current_utc_datetime",
        lambda: datetime(2026, 4, 4, 2, 30, tzinfo=timezone.utc),
    )

    assert datetime_service.is_timestamp_in_display_today("2026-04-04T01:50:00+00:00") is True
    assert datetime_service.is_timestamp_in_display_today("2026-04-04T03:10:00+00:00") is False


def test_ensure_process_timezone_environment_define_tz_quando_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Responsabilidade:
        Garantir que o bootstrap consiga reforçar `TZ` no processo quando faltar.

    Parâmetros:
        monkeypatch: Fixture do pytest usada para limpar e inspecionar o ambiente.

    Retorno:
        Nenhum; valida o comportamento de fallback da infraestrutura.

    Contexto de uso:
        Ajuda logs e bibliotecas de terceiros a seguirem o mesmo timezone-base
        operacional, sem transformar isso na única estratégia de correção.
    """

    monkeypatch.delenv("TZ", raising=False)

    datetime_service.ensure_process_timezone_environment()

    assert datetime_service.os.getenv("TZ") == "America/Sao_Paulo"
