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

## Publicacao de imagem via GitHub Actions + GHCR

O workflow `.github/workflows/main.yml` e disparado em push na branch `main` e executa:

1. **build_and_push**
   - `docker/setup-buildx-action`
   - `docker/login-action` no `ghcr.io`
   - `docker/build-push-action` publicando:
      - `ghcr.io/<owner>/<repo>:latest`
      - `ghcr.io/<owner>/<repo>:<sha>`

O deploy da stack nao e feito pelo GitHub Actions. A atualizacao da aplicacao deve ser feita pelo Portainer, consumindo a imagem publicada no GHCR.

### Secrets necessários no GitHub

- nenhum secret adicional e necessario para o push no GHCR alem do `GITHUB_TOKEN` fornecido pelo proprio GitHub Actions

### Pré-requisitos no Portainer / Swarm

- registry `ghcr.io` configurado no Portainer, se a imagem for privada
- stack configurada a partir de `docker-stack.yml`, usando `ghcr.io/<owner>/<repo>:latest` ou uma tag SHA especifica
- variaveis obrigatorias da aplicacao preenchidas no Portainer

### Arquivo recomendado para stack

Use `docker-stack.yml` para deploy no Docker Swarm via Portainer.

Variaveis esperadas pela stack:

- `SWARM_NODE_HOSTNAME`
- `SESSION_SECRET`
- `DEFAULT_ADMIN_USER`
- `DEFAULT_ADMIN_PASS`
- `IMAGE_TAG` opcional, com padrao `latest`
- `OBS_IMAGE` opcional, com padrao `ghcr.io/hefestox/obs`
