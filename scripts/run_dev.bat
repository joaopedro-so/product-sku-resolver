@echo off
setlocal enabledelayedexpansion

REM Responsabilidade:
REM   Automatizar a preparação do ambiente de desenvolvimento no Windows,
REM   garantindo uso de Python 3.11, instalação de dependências e subida do
REM   servidor FastAPI com recarregamento automático.
REM
REM Parâmetros:
REM   Nenhum.
REM
REM Retorno:
REM   Código de saída do bootstrap ou do processo do servidor.
REM
REM Contexto de uso:
REM   Script principal para iniciar o projeto localmente com uma configuração
REM   compatível, reduzindo erros causados por múltiplas versões de Python.

set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"

REM Decisão técnica:
REM   O script usa o `py launcher` porque ele é o método mais confiável no
REM   Windows para escolher explicitamente a versão 3.11 quando há várias
REM   instalações de Python na mesma máquina.
where py >nul 2>nul
if not %errorlevel%==0 (
  echo [ERRO] O py launcher nao foi encontrado. Instale o Python Launcher para Windows.
  exit /b 1
)

REM Decisão técnica:
REM   Validamos antes de criar a venv para evitar que uma versão como 3.14 seja
REM   usada por acidente em um ambiente desenvolvido para 3.11+.
py -3.11 -c "import sys; print(sys.version)"
if not %errorlevel%==0 (
  echo [AVISO] Python 3.11 nao encontrado via py launcher.

  where winget >nul 2>nul
  if %errorlevel%==0 (
    echo [INFO] Tentando instalar Python 3.11 com winget...
    winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
  ) else (
    echo [ERRO] winget nao encontrado. Instale o Python 3.11 manualmente e execute novamente.
    exit /b 1
  )

  py -3.11 -c "import sys; print(sys.version)"
  if not %errorlevel%==0 (
    echo [ERRO] Python 3.11 continua indisponivel apos a tentativa de instalacao.
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Criando ambiente virtual com Python 3.11.
  py -3.11 -m venv .venv
  if not %errorlevel%==0 exit /b %errorlevel%
) else (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)"
  if not %errorlevel%==0 (
    echo [ERRO] A venv existente nao usa Python 3.11. Remova .venv e execute novamente.
    exit /b 1
  )
  echo [INFO] Ambiente virtual existente ja esta em Python 3.11.
)

REM Decisão técnica:
REM   A ativação deixa o comportamento mais previsível para comandos que possam
REM   depender de PATH, embora a instalação use os executáveis da venv.
call ".venv\Scripts\activate.bat"
if not %errorlevel%==0 exit /b %errorlevel%

echo [INFO] Atualizando pip do ambiente virtual.
python -m pip install --upgrade pip
if not %errorlevel%==0 exit /b %errorlevel%

echo [INFO] Instalando dependencias declaradas em requirements.txt.
pip install -r requirements.txt
if not %errorlevel%==0 exit /b %errorlevel%

REM Decisão técnica:
REM   `python-multipart` é necessário para o dashboard web interpretar
REM   formulários HTML corretamente durante o desenvolvimento.
echo [INFO] Instalando dependencia adicional do dashboard: python-multipart.
pip install python-multipart
if not %errorlevel%==0 exit /b %errorlevel%

echo [INFO] Iniciando servidor FastAPI em http://127.0.0.1:8000/dashboard.
uvicorn api.main:app --reload
exit /b %errorlevel%
