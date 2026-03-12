Regras para agentes de IA que geram código neste repositório.

Estilo de código:

- Comentários sempre em Português Brasil.
- Explicar lógica e decisões técnicas importantes.
- Não gerar código sem comentários.

Arquitetura:

- Código deve ser modular.
- Cada responsabilidade em um módulo separado.
- Evitar funções gigantes.

Organização:

- lógica de negócio em services/
- parsing e scraping em utils/
- rotas API em api/

Qualidade:

- usar type hints sempre que possível
- adicionar tratamento de erro
- priorizar legibilidade sobre compactação
- evitar dependências desnecessárias

Sempre explicar a arquitetura antes de gerar código novo.
