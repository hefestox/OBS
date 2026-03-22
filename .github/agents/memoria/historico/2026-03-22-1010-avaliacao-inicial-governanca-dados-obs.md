# OBS Pro Bot v5.0.1 — avaliacao inicial de governanca de dados (DBA)

## Escopo avaliado

- `docs/system-design.md`
- `docs/declaracao-escopo-aplicacao.md`
- `dashboard.py`
- Sem alteracao de schema.

## Sintese de decisao

- Gate DBA: **Aprovado com ressalvas**.
- Base de persistencia coerente para fase atual (SQLite + WAL + `busy_timeout` + lock global), mas com riscos relevantes de seguranca, atomicidade financeira e recuperacao operacional.

## Evidencias-chave observadas

- Concorrencia declarada e implementada: `PRAGMA journal_mode = WAL`, `PRAGMA busy_timeout = 30000`, lock de processo `_DB_LOCK` (`dashboard.py`).
- Modelo financeiro orientado a ledger e uso de `deposits/withdrawals` como workflow com aprovacao administrativa.
- Lacuna de atomicidade: update de `deposits/withdrawals` e lancamento no `ledger` ocorrem em transacoes separadas (risco de inconsistencias parciais em falha).
- Seguranca: `DEFAULT_ADMIN_PASS`, `SESSION_SECRET` e `DEPOSIT_ADDRESS_FIXED` hardcoded; hash de senha com SHA-256 puro; API key/secret em texto no SQLite.
- Ausencia de trilha de auditoria imutavel para eventos administrativos (before/after, actor, motivo, correlacao).

## Riscos e recomendacoes consolidadas

1. Envolver cada aprovacao/rejeicao/pagamento financeiro em transacao unica (BEGIN/COMMIT/ROLLBACK) com ledger no mesmo boundary.
2. Introduzir trilha de auditoria append-only para eventos financeiros e administrativos.
3. Remover segredos hardcoded e migrar credenciais sensiveis para env/secrets manager.
4. Migrar senha para KDF forte (argon2/bcrypt) com estrategia de migracao progressiva.
5. Formalizar plano de backup/restore (RPO/RTO), teste de restauracao e reconciliacao financeira.
6. Preparar plano de expansao para PostgreSQL conforme crescimento de usuarios/escritas.

## Handoff esperado

- Business Analyst deve consolidar no System Design o plano de dimensionamento/expansao e os gates de governanca de dados (atomicidade, auditoria, recuperacao e seguranca).
