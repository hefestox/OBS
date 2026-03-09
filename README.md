# OBS PRO BOT

## Rodar com Docker Compose (local)

O projeto sobe em dois serviços:
- `web`: interface Streamlit
- `bot`: loop do bot (`python dashboard.py --bot`)

### 1) Configurar variáveis

```bash
cp .env.example .env
# edite a .env com valores fortes
```

### 2) Subir serviços com imagem publicada

```bash
docker compose pull
docker compose up -d
```

### 3) Acessar interface

- Abra: `http://localhost:8501`

### 4) Ver logs do bot

```bash
docker compose logs -f bot
```

### 5) Parar serviços

```bash
docker compose down
```

## Persistência de dados

Banco SQLite (`mvp_funds.db`) e log (`bot.log`) ficam no volume nomeado `obs_data` em `/app/data`.

## Deploy em VPS via GitHub Actions + GHCR

O workflow `.github/workflows/main.yml` é disparado em push na branch `Test` e executa:

1. **build_and_push**
   - `docker/setup-buildx-action`
   - `docker/login-action` no `ghcr.io`
   - `docker/build-push-action` publicando:
      - `ghcr.io/<owner>/<repo>:latest`
      - `ghcr.io/<owner>/<repo>:<sha>`
2. **deploy** (com `needs: [build_and_push]`)
   - Acesso SSH na VPS
   - `docker login ghcr.io`
   - `docker compose pull`
   - `docker compose up -d`

### Secrets necessários no GitHub

- `SSH_HOST`
- `SSH_USER`
- `SSH_PRIVATE_KEY`
- `GHCR_USERNAME`
- `GHCR_TOKEN`

### Pré-requisitos na VPS

- Repositório disponível em `/app/OBS` com `docker-compose.yml`
- Docker e Docker Compose instalados
- Arquivo `.env` presente com as variáveis obrigatórias
