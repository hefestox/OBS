---
name: review-documentation
description: "Use when creating, updating, or backfilling technical delivery records for code changes, fixes, refactors, tests, schema changes, integrations, infrastructure work, or documentation updates. Produces audit-ready review records with decision summary, validation evidence, rollback plan, and Mermaid diagrams in the review, changelog, or delivery-log location adopted by the project. In this package, it complements but does not replace QA, approval, or Tech Lead closure templates."
---

# Review Documentation

Skill para registrar alteracoes tecnicas em um artefato formal de review, changelog tecnico ou registro de entrega, mantendo rastreabilidade clara entre mudanca, decisao, validacao e risco.

## Quando ativar

Ative esta skill quando a tarefa envolver qualquer um dos cenarios abaixo:
- criar ou atualizar um registro tecnico de entrega;
- documentar alteracao retroativa ja implementada;
- registrar PR, fix, refatoracao, ajuste de schema, testes, infraestrutura, seguranca ou documentacao;
- consolidar ADR resumido da mudanca;
- padronizar registros tecnicos de entrega do projeto.

## Regras obrigatorias

### 1. Registro obrigatorio por alteracao relevante
Toda alteracao relevante deve gerar um registro tecnico no local adotado pelo projeto, como pasta de review, changelog de entrega, journal tecnico ou artefato equivalente.

### 2. Cobertura retroativa
Se a mudanca ja foi feita e ainda nao tem registro, crie o review retroativo antes de considerar a tarefa concluida.

### 3. Padrao de nome do arquivo
Quando o projeto nao definir outro padrao, use preferencialmente:

```text
YYYY-MM-DD-HHMM-<slug-curto>.md
```

### 4. Conteudo minimo obrigatorio
Todo review deve conter:
- contexto e objetivo da alteracao;
- escopo tecnico e arquivos modificados;
- ADR resumido com decisao, alternativas e trade-offs;
- evidencias de validacao;
- riscos, impacto e plano de rollback;
- proximos passos recomendados;
- ao menos um diagrama `mermaid`.

### 5. Criterio de conclusao
Nenhuma tarefa de implementacao deve ser considerada plenamente fechada sem o registro tecnico correspondente, quando o projeto exigir esse tipo de artefato.

## Padrao estrutural recomendado

Use esta ordem de secoes:

1. Titulo objetivo da alteracao
2. `## Contexto e objetivo`
3. `## Escopo tecnico e arquivos modificados`
4. `## ADR resumido`
5. `## Evidencias de validacao`
6. `## Riscos, impacto e rollback`
7. `## Proximos passos recomendados`
8. `## Diagrama (Mermaid)`

## Regras editoriais

- Escreva de forma tecnica, direta e auditavel.
- Diferencie claramente o que foi executado do que apenas foi recomendado.
- Quando citar testes, inclua o comando executado e o resultado resumido.
- Quando nao houver execucao real, declare explicitamente que a validacao nao foi executada.
- Liste arquivos modificados em formato simples e objetivo.
- Evite texto promocional, justificativas vagas ou linguagem generica.

## Secoes opcionais por tipo de alteracao

### 1. Persistencia e dados
Documente adicionalmente quando houver mudanca em banco, modelos, eventos de dados, migracoes, trilha de auditoria, capacidade ou rollback de persistencia.

### 2. API, contratos e integracoes
Documente contratos alterados, endpoints afetados, compatibilidade retroativa, payloads, filas, eventos, webhooks ou integracoes externas.

### 3. Relatorios, arquivos gerados ou exportacoes
Documente templates impactados, fluxo de geracao, nomes de arquivo, entrada, saida e validacao aplicada.

### 4. Tempo real, mensageria ou processamento assincrono
Documente rotas, consumidores, payloads, autenticacao, reprocessamento, fallback e comportamento em indisponibilidade.

### 5. Testes e QA
Documente suite afetada, cobertura adicionada, regressao evitada, impacto em CI e evidencias reaproveitadas no fechamento.

### 6. Mudancas somente documentais
Mesmo alteracoes apenas em `docs/` podem exigir review se fizerem parte da entrega solicitada. Nesse caso, descreva documento refinado, criterio de consistencia aplicado e impacto esperado sobre requisitos, QA, arquitetura ou manutencao.

## Workflow recomendado

### Passo 1. Identificar o tipo de alteracao
Classifique a entrega por dominio principal:
- aplicacao ou API;
- dados e persistencia;
- testes e QA;
- integracoes externas;
- processamento assincrono ou eventos;
- infraestrutura e operacao;
- documentacao.

### Passo 2. Coletar evidencias
Levante:
- arquivos tocados;
- comandos executados;
- suites de teste afetadas;
- riscos, dependencias e bloqueios.

### Passo 3. Preencher o review
Use o template em [assets/template/review-record-template.md](assets/template/review-record-template.md) e adapte as secoes opcionais conforme o tipo de alteracao.

### Passo 4. Validar conformidade
Antes de concluir, confirme:
- o arquivo foi salvo no local de review adotado pelo projeto;
- o nome segue o padrao cronologico, quando aplicavel;
- ha pelo menos um diagrama `mermaid`;
- o review distingue validacao executada de validacao pendente;
- rollback e proximos passos foram registrados.

## Checklist rapido

- [ ] Arquivo salvo no local de review adotado pelo projeto
- [ ] Nome no formato esperado pelo projeto
- [ ] Contexto e objetivo preenchidos
- [ ] Arquivos modificados listados
- [ ] ADR resumido preenchido
- [ ] Evidencias de validacao informadas
- [ ] Riscos, impacto e rollback descritos
- [ ] Proximos passos registrados
- [ ] Diagrama `mermaid` incluido

## Convencoes adicionais recomendadas

- Prefira slug curto orientado ao efeito da mudanca, nao ao ticket interno.
- Use titulos focados no comportamento alterado.
- Se a mudanca for retroativa, deixe isso explicito logo no contexto.
- Para tarefas amplas, priorize um review por entrega coerente, nao um review unico para alteracoes desconexas.
- Quando existirem revisao consolidada ou aprovacao final do Tech Lead, referencie o review tecnico nesses artefatos quando aplicavel.

## Saida esperada

O resultado desta skill deve ser um arquivo Markdown pronto para auditoria tecnica, com rastreabilidade clara entre alteracao, decisao, validacao, risco e proximo passo.