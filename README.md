
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





