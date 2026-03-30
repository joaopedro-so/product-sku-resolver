"""
Configurações centrais da aplicação para monitoramento e resolução.

Este módulo concentra parâmetros operacionais para evitar valores mágicos
espalhados no código e facilitar ajustes por ambiente.
"""

from __future__ import annotations

import os


# Regra de negócio:
# Intervalo padrão de monitoramento em minutos para execução periódica.
MONITOR_INTERVAL_MINUTES: int = int(os.getenv("MONITOR_INTERVAL_MINUTES", "30"))

# Regra de negócio:
# Limiar de match para aceite de candidatos vindos de busca.
MATCH_THRESHOLD: float = float(os.getenv("MATCH_THRESHOLD", "0.75"))

# Regra de negócio:
# Limite de candidatos avaliados para evitar custo excessivo e loops longos.
MAX_SEARCH_RESULTS: int = int(os.getenv("MAX_SEARCH_RESULTS", "5"))
