# Registro de Alteração — Plano de Testes OBS

## Contexto e objetivo
Foi solicitado criar um **plano de testes completo e executável** para o projeto OBS, com foco em cobertura funcional e não-funcional dos módulos críticos (autenticação, chaves API, bot trading, financeiro interno, administração, Docker e observabilidade), mantendo consistência com a documentação AS-IS existente.

## Escopo técnico e arquivos modificados
- **Arquivo criado:** `docs/plano-de-testes.md`
- **Arquivo criado:** `review/2026-03-09-0029-plano-testes-obs.md`

Conteúdos incorporados no plano:
- Objetivo e escopo
- Estratégia de testes por nível
- Matriz de cobertura US/UC x tipos de teste
- Critérios de entrada e saída
- Ambientes e dados de teste
- Gestão de defeitos, riscos e priorização
- Plano de automação por fases
- Diretrizes de pipeline/CI
- Checklist de regressão por módulo
- Diagrama Mermaid
- Suposições explícitas para lacunas

## ADR resumido (decisão, alternativas, trade-offs)
- **Decisão:** estruturar o plano usando stack real do projeto (Python/Streamlit/SQLite/Docker), evitando pressupor frameworks não presentes no código atual.
- **Alternativas consideradas:**
  1. Plano orientado a Django/DRF (descartado por falta de aderência ao AS-IS).
  2. Plano focado apenas em testes manuais (descartado por baixa escalabilidade).
- **Trade-offs:**
  - **Pró:** documento imediatamente aplicável ao repositório atual.
  - **Contra:** algumas automações avançadas (ex.: cobertura automatizada em CI) dependem de formalização de dependências de desenvolvimento.

## Evidências de validação (revisão e checagens)
1. Conferência de aderência aos artefatos de referência: `README.md`, `docs/user-stories.md`, `docs/cases/*.md`, `SUMARIO_EXECUTIVO.md`, `RELATORIO_ANALISE_AS-IS.md`.
2. Verificação de presença de todos os itens obrigatórios solicitados no pedido.
3. Revisão de coerência terminológica e rastreabilidade entre US/UC e módulos.
4. Inclusão de suposições explícitas para lacunas sem bloquear entrega.

## Riscos, impacto e rollback
- **Riscos**
  - Interpretação divergente da estratégia E2E por ausência de framework de automação de UI consolidado no repositório.
  - Dependência de definição de gate de cobertura no pipeline para enforcement automático.
- **Impacto esperado**
  - Melhora imediata de governança de QA e rastreabilidade de testes.
  - Base para planejamento de automação incremental com foco em risco.
- **Rollback**
  1. Remover `docs/plano-de-testes.md`.
  2. Remover este registro de `review/`.
  3. Retornar ao estado anterior de documentação via Git.

## Próximos passos
1. Validar com stakeholders os gates formais de qualidade (cobertura, severidade bloqueante, critérios Go/No-Go).
2. Materializar estrutura de diretórios de testes (`tests/unit`, `tests/integration`, `tests/e2e`, `tests/non_functional`).
3. Integrar execução das suítes no pipeline de CI já utilizado pelo time.
4. Criar baseline de casos automatizados para UCs Must (001/002/010/020/021/022/030/031/032/033/034/050).

```mermaid
flowchart LR
    A[Artefatos AS-IS] --> B[Plano de Testes consolidado]
    B --> C[Matriz US/UC x níveis de teste]
    C --> D[Critérios de entrada/saída + riscos]
    D --> E[Automação e pipeline]
    E --> F[Checklist de regressão por módulo]
```

