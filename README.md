⚠️ Projeto experimental para estudo de automação e scraping.
---

product-sku-resolver

Sistema para localizar automaticamente a página atual de um produto em e-commerce e manter seu SKU atualizado, mesmo quando a URL ou estrutura da página muda.

O projeto separa identidade estável do produto (marca, nome, variante) de dados mutáveis (URL e SKU), permitindo atualização automática de códigos.


---

Problema que o projeto resolve

Em e-commerces:

SKUs podem mudar

URLs podem mudar

HTML do site pode mudar


Se o sistema depender apenas do SKU ou da URL antiga, ele quebra.

Este projeto resolve isso usando:

1. resolução de produto


2. validação de identidade


3. extração robusta de SKU




---

Arquitetura

O sistema é dividido em camadas:

resolver
│
├── fetcher
│   responsável por baixar páginas
│
├── parser
│   extrai dados da página (sku, nome, marca)
│
├── matcher
│   valida se a página corresponde ao produto esperado
│
└── resolver
    coordena o fluxo completo de atualização


---

Estrutura do projeto

product-sku-resolver/

backend/
    api/
    services/
    utils/
    models/

tests/

products.json

requirements.txt
README.md
AGENTS.md


---

Fluxo de funcionamento

Para atualizar um produto:

1. abrir a last_known_url


2. validar se a página ainda corresponde ao produto esperado


3. extrair SKU atual


4. se falhar:

buscar novamente o produto

selecionar melhor candidato

validar correspondência

extrair novo SKU



5. atualizar cadastro




---

Estrutura de dados do produto

Exemplo em products.json:

[
  {
    "alias": "one_million_200ml",
    "brand": "Paco Rabanne",
    "name": "One Million",
    "variant": "200ml",
    "last_known_url": "https://www.lojasrenner.com.br/...",
    "last_known_sku": "546594103"
  }
]


---

API (backend)

Endpoints principais:

GET    /products
POST   /products
GET    /products/{alias}
POST   /products/{alias}/update
POST   /products/update-all
GET    /health


---

Como rodar o projeto

Instalar dependências:

pip install -r requirements.txt

Rodar servidor:

uvicorn main:app --reload

Servidor disponível em:

http://localhost:8000


---

Rodando o projeto em desenvolvimento

Arquitetura do bootstrap:

- `scripts/run_dev.sh` é o ponto de entrada para Linux/macOS
- `scripts/run_dev.bat` é o ponto de entrada para Windows
- ambos garantem uso de Python 3.11, criam a `.venv` apenas quando necessário,
  instalam dependências e sobem o servidor via `uvicorn api.main:app --reload`

Observações importantes:

- se `python3.11` não existir no Linux/macOS, o script tenta instalar com
  `apt-get`, `dnf` ou `brew`
- se Python 3.11 não existir no Windows, o script tenta instalar com `winget`
- se a pasta `.venv` já existir, ela **não será recriada**
- se a `.venv` existente não usar Python 3.11, o script interrompe a execução
  e pede para remover a pasta `.venv` antes de tentar novamente

Linux/macOS:

```bash
chmod +x ./scripts/run_dev.sh
./scripts/run_dev.sh
```

Windows:

```bat
scripts\run_dev.bat
```

Servidor disponível em:

```text
http://127.0.0.1:8000
```

Dashboard web:

```text
http://127.0.0.1:8000/dashboard
```


---

Testes

Rodar testes:

pytest

Testes cobrem:

normalização de texto

matching de produto

extração de SKU

validação de página



---

Cliente Android

O projeto inclui um cliente Android que consome a API.

Tecnologias:

Kotlin

Jetpack Compose

Retrofit

Coroutines


Funções do app:

listar produtos

atualizar SKU

adicionar produtos

visualizar validação



---

Regras de código

Este repositório usa AGENTS.md para definir regras de geração de código por IA.

Principais regras:

comentários em Português Brasil

código modular

legibilidade priorizada

explicação de lógica complexa



---

Possíveis evoluções

suporte a múltiplos varejistas

histórico de SKUs

notificações de mudança

painel web

scraping com browser automation

monitoramento automático



---

Licença

MIT


---






---

Fluxo manual (cadastro + resolução sem API)

Para testar rapidamente o pipeline atual sem endpoints REST, use:

```bash
python examples/manual_flow.py \
  --alias one_million_200ml \
  --brand "Paco Rabanne" \
  --name "One Million" \
  --variant "200ml" \
  --url "https://www.exemplo.com/produto?sku=546594103" \
  --seed-sku "unknown"
```

O script irá:

1. cadastrar/atualizar o produto no `data/products.json`
2. executar o resolver com `last_known_url`
3. imprimir resultado de sucesso/erro, score de matching e SKU final

Observação:

- Se a página não corresponder ao produto esperado, o sistema **não atualiza** SKU.
- Nesta versão ainda não há busca automática de nova URL.
