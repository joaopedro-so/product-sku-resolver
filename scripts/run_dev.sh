#!/usr/bin/env bash

# Responsabilidade:
#   Automatizar a preparação do ambiente de desenvolvimento em Linux/macOS,
#   garantindo uso de Python 3.11, instalação de dependências e subida do
#   servidor FastAPI com recarregamento automático.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Código de saída do processo do bootstrap ou do servidor Uvicorn.
#
# Contexto de uso:
#   Script principal para desenvolvedores que desejam iniciar o projeto com um
#   único comando e com uma versão de Python compatível com o repositório.

set -euo pipefail


# Responsabilidade:
#   Escrever mensagens padronizadas no terminal para facilitar diagnóstico do
#   fluxo de bootstrap sem depender de ferramentas externas de logging.
#
# Parâmetros:
#   $1: Nível da mensagem, como INFO, AVISO ou ERRO.
#   $2: Texto que será exibido no terminal.
#
# Retorno:
#   Nenhum.
#
# Contexto de uso:
#   Função utilitária usada por todo o script para deixar o feedback legível e
#   consistente durante instalação, validação e execução.
log_message() {
  local log_level="$1"
  local log_text="$2"
  printf '[%s] %s\n' "${log_level}" "${log_text}"
}


# Responsabilidade:
#   Descobrir a raiz do projeto a partir da localização do script para que os
#   comandos funcionem mesmo quando chamados fora da pasta raiz.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Imprime no stdout o caminho absoluto da raiz do projeto.
#
# Contexto de uso:
#   Usada no bootstrap inicial para localizar `requirements.txt`, `.venv` e o
#   pacote `api` sem depender do diretório atual do usuário.
get_project_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cd "${script_dir}/.." && pwd
}


# Responsabilidade:
#   Verificar se o comando `python3.11` já está disponível no sistema.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Retorna zero se o comando existir; caso contrário, retorna código de erro.
#
# Contexto de uso:
#   Primeira etapa do fluxo para decidir se o script pode seguir diretamente
#   para a criação da venv ou se precisa tentar instalar Python 3.11.
has_python_311() {
  command -v python3.11 >/dev/null 2>&1
}


# Responsabilidade:
#   Tentar instalar Python 3.11 usando o gerenciador de pacotes disponível no
#   sistema operacional do desenvolvedor.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Retorna zero se a instalação for bem-sucedida; caso contrário, erro.
#
# Contexto de uso:
#   Acionada apenas quando `python3.11` não está presente, reduzindo atrito no
#   primeiro bootstrap de uma máquina nova.
install_python_311() {
  if command -v apt-get >/dev/null 2>&1; then
    log_message "INFO" "Python 3.11 não encontrado. Tentando instalar via apt-get."
    sudo apt-get update
    sudo apt-get install -y python3.11 python3.11-venv
    return 0
  fi

  if command -v dnf >/dev/null 2>&1; then
    log_message "INFO" "Python 3.11 não encontrado. Tentando instalar via dnf."
    sudo dnf install -y python3.11
    return 0
  fi

  if command -v brew >/dev/null 2>&1; then
    log_message "INFO" "Python 3.11 não encontrado. Tentando instalar via Homebrew."
    brew install python@3.11

    # Decisão técnica:
    # O Homebrew pode instalar o binário sem vinculá-lo imediatamente ao PATH.
    # Por isso incluímos os diretórios mais comuns antes de falhar.
    if [[ -x "/opt/homebrew/bin/python3.11" ]]; then
      export PATH="/opt/homebrew/bin:${PATH}"
    elif [[ -x "/usr/local/bin/python3.11" ]]; then
      export PATH="/usr/local/bin:${PATH}"
    fi

    return 0
  fi

  log_message "ERRO" "Nenhum gerenciador suportado encontrado. Instale Python 3.11 manualmente."
  return 1
}


# Responsabilidade:
#   Garantir que o interpretador `python3.11` esteja disponível antes de criar
#   ou validar o ambiente virtual do projeto.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Nenhum; encerra o script com erro caso Python 3.11 não possa ser obtido.
#
# Contexto de uso:
#   Centraliza a política de compatibilidade da stack para evitar que o projeto
#   seja iniciado com versões novas demais ou antigas demais do Python.
ensure_python_311() {
  if has_python_311; then
    log_message "INFO" "Python 3.11 encontrado no sistema."
    return 0
  fi

  install_python_311

  if ! has_python_311; then
    log_message "ERRO" "Não foi possível disponibilizar o comando python3.11 após a instalação."
    exit 1
  fi

  log_message "INFO" "Python 3.11 instalado com sucesso."
}


# Responsabilidade:
#   Validar se a venv existente foi criada com Python 3.11 para impedir uso de
#   um ambiente inconsistente com a base do projeto.
#
# Parâmetros:
#   $1: Caminho absoluto da raiz do projeto.
#
# Retorno:
#   Nenhum; encerra o script com erro se a venv existir em versão incorreta.
#
# Contexto de uso:
#   Garante idempotência sem recriar a venv automaticamente quando ela já
#   existe, preservando o pedido de não destruir o ambiente do usuário.
ensure_virtualenv() {
  local project_root="$1"
  local venv_python="${project_root}/.venv/bin/python"

  if [[ ! -x "${venv_python}" ]]; then
    log_message "INFO" "Criando ambiente virtual com Python 3.11 em ${project_root}/.venv."
    python3.11 -m venv "${project_root}/.venv"
    return 0
  fi

  if ! "${venv_python}" -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 11) else 1)"; then
    log_message "ERRO" "A venv existente não usa Python 3.11. Remova .venv e execute novamente."
    exit 1
  fi

  log_message "INFO" "Ambiente virtual existente já está em Python 3.11."
}


# Responsabilidade:
#   Ativar a venv do projeto no shell atual para garantir que `pip` e `uvicorn`
#   apontem para o ambiente isolado e previsível do desenvolvimento.
#
# Parâmetros:
#   $1: Caminho absoluto da raiz do projeto.
#
# Retorno:
#   Nenhum.
#
# Contexto de uso:
#   Etapa executada após a validação da venv e antes da instalação de
#   dependências do projeto.
activate_virtualenv() {
  local project_root="$1"
  # shellcheck disable=SC1091
  source "${project_root}/.venv/bin/activate"
  log_message "INFO" "Ambiente virtual ativado."
}


# Responsabilidade:
#   Instalar dependências declaradas no projeto e o pacote adicional exigido
#   pelo parsing de formulários HTML do dashboard.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Nenhum.
#
# Contexto de uso:
#   Executada em toda inicialização para tornar o script idempotente e manter o
#   ambiente sincronizado com os requisitos atuais do repositório.
install_project_dependencies() {
  log_message "INFO" "Atualizando pip do ambiente virtual."
  python -m pip install --upgrade pip

  log_message "INFO" "Instalando dependências declaradas em requirements.txt."
  pip install -r requirements.txt

  # Decisão técnica:
  # `python-multipart` é necessário para `request.form()` no dashboard web e
  # ainda não está presente em `requirements.txt`.
  log_message "INFO" "Instalando dependência adicional do dashboard: python-multipart."
  pip install python-multipart
}


# Responsabilidade:
#   Iniciar o servidor FastAPI usando o ponto de entrada padronizado do pacote
#   `api`, mantendo recarregamento automático para desenvolvimento local.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Substitui o processo atual pelo Uvicorn e propaga seu código de saída.
#
# Contexto de uso:
#   Última etapa do bootstrap, quando o ambiente já está preparado.
start_development_server() {
  log_message "INFO" "Iniciando servidor FastAPI em http://127.0.0.1:8000/dashboard."
  exec uvicorn api.main:app --reload
}


# Responsabilidade:
#   Orquestrar todas as etapas do bootstrap local em ordem segura e previsível.
#
# Parâmetros:
#   Nenhum.
#
# Retorno:
#   Nenhum.
#
# Contexto de uso:
#   Função principal do script, usada para deixar o fluxo mais didático e
#   modular para manutenção futura.
main() {
  local project_root
  project_root="$(get_project_root)"

  cd "${project_root}"
  log_message "INFO" "Raiz do projeto detectada em ${project_root}."

  ensure_python_311
  ensure_virtualenv "${project_root}"
  activate_virtualenv "${project_root}"
  install_project_dependencies
  start_development_server
}

main "$@"
