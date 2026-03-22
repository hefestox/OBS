# Skill Hierarchy

Guia pratico para escolher a skill certa, evitar sobreposicao e reduzir invocacao ambigua dentro do pacote.

## Objetivo

Este documento responde a uma pergunta simples: qual skill usar para cada tipo de demanda?

Use este mapa antes de escolher uma skill em `.github/skills/`, especialmente quando houver varias alternativas parecidas no mesmo ecossistema.

## Regra geral

Escolha skills nesta ordem:

1. Primeiro, identifique o dominio principal da tarefa.
2. Depois, veja se existe uma skill de framework ou stack mais especifica.
3. So use uma skill generica se nao houver uma skill especializada mais aderente.
4. Se a tarefa for transversal, combine no maximo a skill principal com uma skill de apoio documental ou de arquitetura.

## Skills por categoria

### Arquitetura e documentacao

Use estas skills quando a tarefa principal nao for uma implementacao de framework, mas sim estrutura, documentacao, revisao ou diagramacao.

- [.github/skills/clean-architecture/](../skills/clean-architecture/): use para desenho tecnico, separacao de camadas, boundaries e revisao arquitetural
- [.github/skills/documentation-sync/](../skills/documentation-sync/): use depois de mudancas tecnicas para revisar impacto documental
- [.github/skills/review-documentation/](../skills/review-documentation/): use para registrar review tecnico, consolidacao de mudancas e evidencias
- [.github/skills/mermaid-generator/](../skills/mermaid-generator/): use quando a entrega pede diagramas Mermaid
- [.github/skills/design-md/](../skills/design-md/): use apenas quando a tarefa for gerar `DESIGN.md` a partir de Stitch MCP

### Produto e requisitos

- [.github/skills/prd-generator/](../skills/prd-generator/): use para gerar PRD
- [.github/skills/user-story-writing/](../skills/user-story-writing/): use para historias de usuario e criterios de aceite

### Seguranca

#### Quando a tarefa for seguranca transversal web

Use:

- [.github/skills/security-best-practices/](../skills/security-best-practices/)

Escopo ideal:

- HTTPS
- CORS
- cookies
- headers
- CSP
- secret handling
- hardening web em geral

#### Quando a tarefa for seguranca especifica de API

Use:

- [.github/skills/api-security-best-practices/](../skills/api-security-best-practices/)

Escopo ideal:

- auth
- authz
- token handling
- schema validation
- rate limiting
- API hardening

#### Quando a tarefa for Better Auth especificamente

Use:

- [.github/skills/better-auth-best-practices/](../skills/better-auth-best-practices/)

Nao use esta skill para auth generica. Ela e para integracao com Better Auth.

## Skills por stack

### Python generico

Use:

- [.github/skills/python-best-practices/](../skills/python-best-practices/)

Quando usar:

- type-first design
- modelagem de dominio
- contratos
- Protocol, NewType, dataclasses e fronteiras tipadas

Quando nao usar:

- nao use so porque o arquivo e Python; prefira skills de framework se a tarefa for claramente Django ou FastAPI

### FastAPI

#### Quero estruturar ou iniciar um servico

Use:

- [.github/skills/fastapi-templates/](../skills/fastapi-templates/)

#### Quero implementar endpoints, schemas, auth ou operacao principal

Use:

- [.github/skills/fastapi-expert/](../skills/fastapi-expert/)

#### Quero uma orientacao leve de estilo em um servico FastAPI ja existente

Use:

- [.github/skills/fastapi-python/](../skills/fastapi-python/)

#### Quero tratar concorrencia, performance async ou event loop safety

Use:

- [.github/skills/fastapi-async-patterns/](../skills/fastapi-async-patterns/)

Regra de prioridade para FastAPI:

1. `fastapi-expert` para implementacao principal
2. `fastapi-templates` para bootstrap e estrutura
3. `fastapi-async-patterns` para tuning async
4. `fastapi-python` para guidance leve em codigo existente

### Django

#### Quero implementar feature, model, serializer, view ou depurar ORM

Use:

- [.github/skills/django-expert/](../skills/django-expert/)

#### Quero definir estrutura, organizacao do projeto ou padroes de arquitetura Django

Use:

- [.github/skills/django-patterns/](../skills/django-patterns/)

#### Quero hardening e revisao de seguranca Django

Use:

- [.github/skills/django-security/](../skills/django-security/)

#### Quero testes, TDD, pytest-django ou infraestrutura de testes

Use:

- [.github/skills/django-tdd/](../skills/django-tdd/)

Regra de prioridade para Django:

1. `django-expert` para implementacao
2. `django-patterns` para estrutura
3. `django-security` para seguranca
4. `django-tdd` para testes

### React e frontend

#### Quero performance e composicao em React generico

Use:

- [.github/skills/frontend-react-best-practices/](../skills/frontend-react-best-practices/)

#### Quero performance orientada a Next.js, App Router ou Vercel

Use:

- [.github/skills/vercel-react-best-practices/](../skills/vercel-react-best-practices/)

#### Quero apoio de design de interface

Use:

- [.github/skills/interface-design/](../skills/interface-design/)

Regra de prioridade para frontend:

1. `vercel-react-best-practices` se o problema for claramente Next.js/Vercel
2. `frontend-react-best-practices` para React framework-agnostico
3. `interface-design` para problema de sistema visual, interface ou estrutura de UX

### Node.js e NestJS

- [.github/skills/nodejs-best-practices/](../skills/nodejs-best-practices/): use para Node.js generico
- [.github/skills/nestjs-best-practices/](../skills/nestjs-best-practices/): use quando a stack for NestJS

### PHP e Laravel

- [.github/skills/php-best-practices/](../skills/php-best-practices/): use para PHP generico
- [.github/skills/laravel-best-practices/](../skills/laravel-best-practices/): use quando a stack for Laravel

### Cloudflare Workers

- [.github/skills/workers-best-practices/](../skills/workers-best-practices/): use para Workers, wrangler, bindings, observability e praticas do ecossistema Cloudflare

## Combinacoes recomendadas

Combinacoes seguras e uteis:

- `fastapi-expert` + `api-security-best-practices`
- `django-expert` + `django-security`
- `frontend-react-best-practices` + `interface-design`
- `vercel-react-best-practices` + `interface-design`
- `clean-architecture` + `review-documentation`
- `documentation-sync` + `mermaid-generator`
- `prd-generator` + `user-story-writing`

## Combinacoes a evitar

Evite carregar juntas sem necessidade:

- `fastapi-expert` + `fastapi-python` quando o objetivo ja estiver claro
- `django-expert` + `django-patterns` para uma unica tarefa pequena
- `security-best-practices` + `api-security-best-practices` se a demanda for claramente apenas web ou apenas API
- `frontend-react-best-practices` + `vercel-react-best-practices` quando a stack ja estiver definida

## Regras de desempate

Se duas skills parecerem servir:

1. escolha a mais especifica para a stack;
2. se ambas forem da mesma stack, escolha a que mais se aproxima do objetivo principal:
   - implementar
   - estruturar
   - proteger
   - testar
   - documentar
3. adicione uma segunda skill apenas se ela cobrir uma dimensao diferente e complementar.

## Atalho por intencao

### Quero criar arquitetura ou organizar camadas

- [.github/skills/clean-architecture/](../skills/clean-architecture/)

### Quero revisar impacto documental apos uma entrega

- [.github/skills/documentation-sync/](../skills/documentation-sync/)

### Quero escrever ou consolidar um review tecnico

- [.github/skills/review-documentation/](../skills/review-documentation/)

### Quero gerar diagrama Mermaid

- [.github/skills/mermaid-generator/](../skills/mermaid-generator/)

### Quero escrever PRD ou historias

- [.github/skills/prd-generator/](../skills/prd-generator/)
- [.github/skills/user-story-writing/](../skills/user-story-writing/)

### Quero proteger uma API

- [.github/skills/api-security-best-practices/](../skills/api-security-best-practices/)

### Quero endurecer uma aplicacao web

- [.github/skills/security-best-practices/](../skills/security-best-practices/)

### Quero iniciar um servico FastAPI

- [.github/skills/fastapi-templates/](../skills/fastapi-templates/)

### Quero implementar um endpoint FastAPI

- [.github/skills/fastapi-expert/](../skills/fastapi-expert/)

### Quero estruturar ou depurar Django

- [.github/skills/django-expert/](../skills/django-expert/)

### Quero testar Django com TDD

- [.github/skills/django-tdd/](../skills/django-tdd/)

### Quero otimizar React

- [.github/skills/frontend-react-best-practices/](../skills/frontend-react-best-practices/)

### Quero otimizar Next.js

- [.github/skills/vercel-react-best-practices/](../skills/vercel-react-best-practices/)

## Resultado esperado

Ao usar este arquivo, voce deve conseguir:

- reduzir sobreposicao entre skills;
- acionar a skill certa mais cedo;
- evitar combinacoes redundantes;
- tornar a descoberta do catalogo mais previsivel.