# OBS Pro Bot — plano de hardening de dados P0/P1 para gate DBA

## Contexto

- Demanda de destravamento de fechamento tecnico com foco em riscos de persistencia.
- Artefatos-base: `review/2026-03-22-0328-revisao-consolidada-tech-lead.md`, `review/2026-03-22-0331-aprovacao-final-tech-lead.md`, `dashboard.py`, `docs/system-design.md`.

## Decisoes DBA

1. **P0 Atomicidade financeira obrigatoria**:
   - aprovacoes de deposito e saque devem executar `UPDATE status` + `INSERT ledger` em **transacao unica**;
   - criacao de saque deve validar saldo e inserir solicitacao no mesmo boundary critico.
2. **P0 Trilha de auditoria financeira**:
   - eventos de aprovacao/rejeicao/pagamento e lancamentos em ledger com `actor`, `timestamp`, `entidade`, `antes/depois`, `motivo`, `correlation_id`;
   - estrutura append-only para investigacao e conformidade.
3. **P0 Backup/restore testavel**:
   - politica com RPO/RTO explicitos, rotina automatizada e teste de restauracao periodico com reconciliacao de ledger.
4. **P1 Capacidade e expansao**:
   - baseline de crescimento (usuarios, lancamentos, trades), monitoramento de tamanho/latencia/conteccao e gatilhos de migracao para PostgreSQL.
5. **Gate DBA so aprova com evidencia executavel**:
   - sem evidencia objetiva de transacao atomica, auditoria e restore validado, o gate permanece reprovado.

## Divergencias registradas

- `docs/system-design.md` descreve robustez de concorrencia, mas `dashboard.py` ainda separa status financeiro e ledger em transacoes distintas.
- Requisito de governanca financeira exige trilha de auditoria mais forte do que o estado atual (campos de nota e reviewed_at sao insuficientes para auditoria completa).
- Plano de expansao citado de forma generica no design, sem runbook de capacidade e sem metas de RPO/RTO testadas.

## Handoff ao Business Analyst

- Consolidar no System Design:
  - fluxo transacional atomico de deposito/saque;
  - contrato de auditoria financeira e conciliacao;
  - politica de backup/restore com frequencia, RPO/RTO e ritual de teste;
  - plano de capacidade com gatilhos de expansao e marco de migracao para PostgreSQL.
