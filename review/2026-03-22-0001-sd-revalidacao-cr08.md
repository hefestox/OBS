# SD Revalidacao CR-08 — Hardening Core Readiness

## 1) Contexto

- Branch: `feature/p0-hardening-core`
- Escopo desta revalidacao: autenticacao, sessao, transacoes financeiras, testes e CI.
- Base de referencia tecnica: `dashboard.py`, `tests/test_p0_hardening.py`, `.github/workflows/main.yml`.
- Regra operacional aplicada: validacao local executada em **container**.

## 2) Registro cronologico da revalidacao

### 2026-03-22 00:01 — Inspecao de implementacao

Arquivos revisados:
- `dashboard.py`
- `tests/test_p0_hardening.py`
- `.github/workflows/main.yml`

Pontos confirmados:
1. **Autenticacao (CR-03)**
   - Hash de senha com `bcrypt` (`hash_password`).
   - Compatibilidade legada SHA-256 com migracao automatica no login (`auth` + `verify_password` + `is_bcrypt_hash`).
   - Cria usuario com hash forte por padrao (`create_user`).
2. **Sessao (CR-03)**
   - Token nao deterministico com `secrets.token_urlsafe(48)` (`create_session`).
   - Invalidacao de sessoes anteriores por usuario (`DELETE FROM sessions WHERE user_id=?`).
   - Validacao de expiracao e rejeicao de token invalido/malformado (`get_session_user`).
3. **Transacoes financeiras (CR-04)**
   - Revisoes de deposito/saque sob transacao explicita (`BEGIN IMMEDIATE`) com rollback em falha.
   - Escrita em ledger encapsulada em `_add_ledger_tx` dentro da mesma transacao.
   - Saque validado em secao critica considerando saldo e pendencias (`create_withdrawal`).
4. **Testes (CR-05)**
   - Suite de hardening com 11 testes cobrindo migracao de hash, sessao, atomicidade, caminhos de sucesso e concorrencia.
5. **CI (CR-05)**
   - Workflow com `py_compile`, gate P0 com cobertura minima (`--cov-fail-under=20`) e suite completa (`pytest -q`).

### 2026-03-22 00:01–00:02 — Validacao local em container (docker-compose.yml)

Comandos executados:

```bash
docker compose -f docker-compose.yml run --rm -v "$PWD":/app --entrypoint sh web -lc 'cd /app && python -m pip install --no-cache-dir -q -r requirements.txt && python -m py_compile dashboard.py CookieManager.py && python -m pytest -q tests/test_p0_hardening.py --cov=dashboard --cov-fail-under=20 && python -m pytest -q'
```

Resultados:
- Inicializacao de servico via `docker-compose.yml`: **sucesso**.
- Compilacao Python no container (`py_compile`): **sucesso**.
- Gate P0 com cobertura: **11 passed**, cobertura `dashboard.py` **24.14%** (threshold 20%).
- Suite completa: **11 passed**.

## 3) Parecer SD (gate)

**Status final do gate SD: APROVADO COM RESSALVAS.**

Justificativa:
- Requisitos tecnicos P0 de hardening no core permanecem implementados e validados em execucao containerizada.
- Nao foi identificada inconsistencia bloqueante para CR-08 no escopo SD desta rodada.

## 4) Divergencias residuais (nao bloqueantes)

1. **Cobertura ainda limitada para modulo monolitico**
   - Evidencia: cobertura total de `dashboard.py` em 24.14% (acima do gate minimo, mas baixa para risco estrutural do arquivo).
   - Impacto: risco de regressao fora dos fluxos P0 cobertos.
2. **Acoplamento elevado em `dashboard.py`**
   - Evidencia: concentracao de responsabilidades (UI, auth, persistencia e regras de negocio no mesmo modulo).
   - Impacto: manutencao e evolucao com maior risco de efeitos colaterais.
3. **Ausencia de cenarios adicionais de carga/concorrrencia alem do minimo atual**
   - Evidencia: teste concorrente cobre caso de 2 threads para saque.
   - Impacto: comportamento sob disputa mais ampla permanece com risco residual.

## 5) Recomendacoes SD

1. Evoluir cobertura focada em fluxos financeiros e fronteiras de erro prioritarias (P1).
2. Planejar extracao incremental por camadas (servicos/repositorios) para reduzir acoplamento do modulo unico.
3. Expandir testes de concorrencia para cenarios com maior paralelismo e repeticoes.

## 6) Arquivos alterados nesta rodada

- `review/2026-03-22-0001-sd-revalidacao-cr08.md` (novo parecer SD)

## 7) Encaminhamento

- Encaminhar este parecer para consolidacao do Tech Lead no CR-08.
- Manter recomendacoes acima como backlog tecnico pos-fechamento P0.
