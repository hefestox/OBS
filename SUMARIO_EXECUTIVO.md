# SUMÁRIO EXECUTIVO - ANÁLISE AS-IS OBS PRO BOT

## 📊 COBERTURA GERAL

| Métrica | Resultado |
|---|---|
| **User Stories Mapeadas** | 17/17 (100%) ✅ |
| **Use Cases Documentados** | 17/17 (100%) ✅ |
| **Código-Docs Sincronizados** | 17/17 (100%) ✅ |
| **Funcionalidades Não Documentadas** | 5 (CRÍTICAS) |
| **Exceções Identificadas** | 23 |
| **Erros Lógicos Encontrados** | 5 |

---

## ⚠️ ACHADOS CRÍTICOS

### 1. **Lacunas de Documentação (5 UCs Faltando)**

| UC Proposto | Prioridade | Evidência no Código |
|---|---|---|
| **UC-060**: Cooldown pós-SL | MUST | `dashboard.py:700-713` |
| **UC-061**: Contador de losses | SHOULD | `dashboard.py:675-680, 820-824` |
| **UC-062**: Testar conectividade API | SHOULD | `dashboard.py:646, 650-665` |
| **UC-063**: Retry de exchange | SHOULD | `dashboard.py:619-626` |
| **UC-064**: Sync de relógio | COULD | `dashboard.py:609-617` |

**Ação**: Criar 5 novos arquivos em `docs/cases/` com numeração UC-060 a UC-064

---

### 2. **Erros Lógicos em Movimentações Financeiras**

#### L1: **Taxa de Saque Não Refletida no Ledger** 🔴 CRÍTICO
- **Problema**: Saque de 100 USDT com taxa 5% = usuário perde 105 USDT, ledger debita apenas 100
- **Código**: `dashboard.py` linhas 360-373 vs 338-340
- **Impacto**: Saldo inconsistente com realidade
- **Solução**: Debitar `amount_request + fee_usdt` OR criar lançamento ADJUST separado para fee

#### L2: **Fees de Trading Não Refletidos no Saldo** 🔴 CRÍTICO
- **Problema**: 10 trades com 0.5 USDT fee cada = 5 USDT perdidos, mas ledger não registra
- **Código**: `dashboard.py` linhas 751, 819 (insere em bot_trades) vs falta lançamento ledger
- **Impacto**: Saldo em UI diverge de realidade operacional
- **Solução**: Adicionar lançamento `ledger` (kind='ADJUST', amount=-fee_usdt) para cada trade

#### L3: **Conflito Saldo: Ledger vs Bot State** 🟡 IMPORTANTE
- **Problema**: Validação de saque usa `ledger` (100 USDT) mas bot pode ter apenas 5 USDT em caixa (95 BTC em aberto)
- **Código**: `dashboard.py` linhas 331-334 vs 288-294
- **Impacto**: Aprovação de saque sem caixa disponível
- **Solução**: Validar contra `min(user_balance, bot_state.usdt)` OR bloquear saques com bot operando

---

### 3. **Vulnerabilidades de Segurança**

| Tipo | Severidade | Evidência | Recomendação |
|---|---|---|---|
| Credenciais plain-text | 🔴 CRÍTICA | `user_keys` table sem criptografia | Implementar AES/Fernet em repouso |
| Admin pass default | 🔴 CRÍTICA | `DEFAULT_ADMIN_PASS = "LU87347748"` (linha 54) | Forçar senha forte na primeira execução |
| SESSION_SECRET fraco | 🔴 CRÍTICA | `SESSION_SECRET = "obspro-mude-essa-chave-2024"` (linha 86) | Gerar UUID aleatório em primeira execução |
| Sem timeout DB | 🟡 IMPORTANTE | `_DB_LOCK` sem timeout explícito | Adicionar timeout em context manager |
| Atomicidade comprometida | 🟡 IMPORTANTE | Admin review separa UPDATE + INSERT | Envolver em transação explícita |

---

## 📋 FLUXOS ALTERNATIVOS FALTANDO

| UC | Fluxo Alternativo Faltando | Linha Código |
|---|---|---|
| **UC-021** | FA4: Cooldown pós-SL bloqueia entrada | 700-713 |
| **UC-021** | FA5: Quantidade zerada após precision | 748 |
| **UC-022** | FA3: Falha ao vender (API/saldo zerado) | 833, 792-799 |
| **UC-022** | FA4: MIN_HOLD_SECONDS atrasa saída | 774-778 |
| **UC-030** | FA3: TXID vazio | 297 |
| **UC-031/033** | FA1: Já revisado (segunda tentativa) | 322, 367 |

**Ação**: Atualizar 6 arquivos UC em `docs/cases/` com fluxos alternativos

---

## 🔧 PARÂMETROS CRÍTICOS (Hardcoded)

| Parâmetro | Valor | Linha | Recomendação |
|---|---|---|---|
| `TAKE_PROFIT` | 0.010 (1.0%) | 60 | Tornar configurável via UI admin |
| `STOP_LOSS` | 0.005 (0.5%) | 61 | Tornar configurável via UI admin |
| `COOLDOWN_AFTER_SL` | 300s (5 min) | 79 | Tornar configurável |
| `WITHDRAW_FEE_RATE` | 0.05 (5%) | 57 | Será configurável via env? |
| `BOT_SYMBOL` | "BTC/USDT" | 59 | Adicionar suporte multi-par (UC-065+) |
| `MIN_HOLD_SECONDS` | 300s | 68 | Documentar em UC-022 |

---

## 📊 MATRIZ RASTREABILIDADE FINAL

```
✅ COBERTURA COMPLETA (17 UCs):
  - UC-001 a UC-010: Autenticação, chaves, bot base
  - UC-020 a UC-023: Estratégia trading
  - UC-030 a UC-035: Movimentações financeiras
  - UC-040: Admin
  - UC-050, UC-051: Operação

⚠️ LACUNAS OPERACIONAIS (5 novos UCs):
  - UC-060: Cooldown pós-SL (MUST)
  - UC-061: Contador losses (SHOULD)
  - UC-062: Teste API (SHOULD)
  - UC-063: Retry exchange (SHOULD)
  - UC-064: Sync relógio (COULD)

🔴 RISCOS NÃO DOCUMENTADOS:
  - Erros lógicos em financeiro (L1, L2, L3)
  - Vulnerabilidades de segurança (5 tipos)
  - Fluxos alternativos faltando em 6 UCs
```

---

## 🎯 AÇÕES RECOMENDADAS (Prioridade)

### P0 - CRÍTICO (Corrigir Imediatamente)
1. Criar UC-060 (cooldown pós-SL) - regra de negócio em produção
2. Corrigir L1 (taxa saque em ledger) - inconsistência financeira
3. Corrigir L2 (fees trading em ledger) - auditoria impossível

### P1 - IMPORTANTE (Sprint Próxima)
1. Criar UC-061, UC-062, UC-063 (operacionalidade)
2. Atualizar UC-021, UC-022 com fluxos alternativos faltando
3. Implementar criptografia credenciais (user_keys)
4. Tornar TP/SL configuráveis via UI

### P2 - DESEJÁVEL (Backlog)
1. Criar UC-064 (sync relógio)
2. Atomicidade explícita em admin_review_*
3. Timeout em _DB_LOCK
4. Suporte multi-par trading

---

## 📁 ARQUIVOS ANALISADOS

✅ **Obrigatórios (7)**
- dashboard.py (1239 linhas)
- README.md
- Dockerfile
- docker-compose.yml
- docs/declaracao-escopo-aplicacao.md
- docs/user-stories.md
- docs/cases/*.md (17 arquivos)

✅ **Derivados**
- requirements.txt
- CookieManager.py (não usado)
- paper_trades.csv (não usado)

---

## 📞 PRÓXIMOS PASSOS

1. **Validar com stakeholder**: Confirmar prioridades L1, L2, L3
2. **Criar novos UCs**: UC-060 até UC-064 em `docs/cases/`
3. **Atualizar existentes**: Adicionar fluxos alternativos em UC-021, UC-022, UC-030, UC-031, UC-033
4. **Bug fixes**: Implementar correcções L1, L2, L3 em dashboard.py
5. **Segurança**: Encriptar credenciais, forçar sessão secret aleatória

---

**Data da Análise:** 2024-03-08  
**Escopo:** Funcionalidades observáveis em código + documentação AS-IS  
**Cobertura:** 100% dos 17 UCs documentados + 5 novos identificados  
