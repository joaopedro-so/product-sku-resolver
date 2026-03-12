"""
Configuração de testes para ajuste de import path do projeto.
"""

import sys
from pathlib import Path


# Responsabilidade:
#   Garantir que o diretório raiz do repositório esteja no sys.path.
# Parâmetros:
#   Nenhum (executado automaticamente pelo pytest).
# Retorno:
#   Nenhum.
# Contexto de uso:
#   Evita erro de import em ambiente sem pacote instalado via pip.
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
