# 🚀 PUMPS - Crypto Trading Bot com IA

**WebSocket Binance em tempo real + OpenAI GPT + Radar de Pumps + Dashboard Profissional**

> 🎯 **Pronto para rodar no Railway com um clique!**

## ✨ Features

- 🔴 **WebSocket Binance** - Conecta em tempo real com Binance API
- 🤖 **IA OpenAI** - Análise inteligente de moedas com GPT (gpt-3.5-turbo / gpt-4)
- ⚡ **Radar de Pumps** - Detecta pump and dump automático
- 📊 **Dashboard Web** - Interface responsiva e profissional
- 🌐 **API REST** - 6+ endpoints prontos
- 🐳 **Docker** - Containerizado e otimizado
- 🚂 **Railway Ready** - Deploy em 1 clique
- 📈 **Modo Demo** - Funciona sem credenciais (para testes)

## 🎯 Deploy Rápido no Railway

### Opção 1: Botão Deploy (Mais Fácil)

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new?template=https://github.com/hefestox/OBS)

### Opção 2: Manual

1. **Criar conta em [Railway.app](https://railway.app)**
2. **Conectar GitHub** (autorizar Railway acessar seus repos)
3. **Selecionar repositório** `hefestox/OBS`
4. **Adicionar variáveis de ambiente**:
   ```
   FLASK_ENV=production
   BINANCE_API_KEY=sua_key
   BINANCE_API_SECRET=seu_secret
   OPENAI_API_KEY=sk-xxx
   ```
5. **Deploy automático!** ✅

## 🏃 Rodar Localmente

### Pré-requisitos
- Python 3.11+
- Git

### Instalação

```bash
# Clonar
git clone https://github.com/hefestox/OBS.git
cd OBS

# Ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate  # Windows

# Dependências
pip install -r requirements.txt

# Configurar
cp .env.example .env
# Editar .env com suas credenciais

# Rodar
python app.py

# Acessar
# http://localhost:5000
```

## 🔑 Obter Credenciais

### Binance API
1. Ir em [API Management](https://www.binance.com/en/account/api-management)
2. Criar nova chave (testnet recomendado para testes)
3. Copiar `API Key` e `Secret Key`

### OpenAI API
1. Ir em [Platform OpenAI](https://platform.openai.com/api-keys)
2. Criar nova chave
3. Copiar chave (começa com `sk-`)

## 📊 API Endpoints

### Health Check
```bash
GET /api/health
```
Response: `{"status": "healthy", "components": {...}}`

### Preços em Tempo Real
```bash
GET /api/prices?symbol=BTCUSDT
```
Response: `{"symbol": "BTCUSDT", "data": {"price": 45000.00, ...}}`

### Pumps Detectados
```bash
GET /api/pumps
```
Response: `{"pumps": [...], "count": 5}`

### Análise com IA
```bash
POST /api/analyze
Body: {"symbol": "ETHUSDT"}
```

### Sentimento de Mercado
```bash
GET /api/sentiment
```

### Alertas
```bash
GET /api/alerts
```

## 📁 Estrutura

```
.
├── app.py                    # Aplicação principal (PRONTO PARA RAILWAY)
├── Dockerfile                # Build Docker otimizado
├── railway.json              # Configuração Railway
├── requirements.txt          # Dependências
├── .env.example              # Template de variáveis
│
├── src/                      # Módulos Python
│   ├── binance_client.py     # WebSocket Binance
│   ├── openai_analyzer.py    # IA OpenAI
│   ├── pump_detector.py      # Detector de pumps
│   └── utils.py              # Funções auxiliares
│
├── templates/                # HTML
│   └── index.html            # Dashboard
│
└── static/                   # CSS/JS
    ├── css/style.css         # Estilos
    └── js/dashboard.js       # JavaScript
```

## 🔧 Modo Demo

A aplicação funciona em **modo demo** mesmo sem credenciais:
- Retorna dados simulados realistas
- Perfeito para testes e desenvolvimento
- Nenhum erro ao acessar os endpoints

## 🚀 Customizações Comuns

### Adicionar Discord Webhook
```python
# Em app.py, adicionar:
import requests

def send_alert(message):
    webhook = os.getenv('DISCORD_WEBHOOK')
    if webhook:
        requests.post(webhook, json={"content": message})
```

### Integrar Banco de Dados
```bash
pip install flask-sqlalchemy
```

### Adicionar Autenticação
```bash
pip install flask-jwt-extended
```

## 📊 Variáveis de Ambiente

| Variável | Descrição | Obrigatório |
|----------|-----------|-------------|
| `FLASK_ENV` | development/production | ✅ |
| `PORT` | Porta (padrão 5000) | ❌ |
| `BINANCE_API_KEY` | Chave Binance | ❌ |
| `BINANCE_API_SECRET` | Secret Binance | ❌ |
| `BINANCE_TESTNET` | true/false | ❌ |
| `OPENAI_API_KEY` | Chave OpenAI | ❌ |
| `OPENAI_MODEL` | gpt-3.5-turbo/gpt-4 | ❌ |
| `PUMP_THRESHOLD` | % aumento para pump | ❌ |
| `PUMP_TIME_WINDOW` | Minutos para análise | ❌ |
| `MIN_VOLUME` | Volume mínimo USDT | ❌ |

## 🐳 Docker Local

```bash
# Build
docker build -t pumps:latest .

# Run
docker run -p 5000:5000 --env-file .env pumps:latest

# Acessar
# http://localhost:5000
```

## 📈 Performance no Railway

- **RAM**: 512MB (suficiente)
- **CPU**: 50m (suficiente)
- **Replicas**: 1
- **Timeout**: 120s
- **Health Check**: Automático

## 🆘 Troubleshooting

### Erro "ModuleNotFoundError"
```bash
pip install -r requirements.txt
```

### Erro "Connection refused"
- Verificar se `BINANCE_API_KEY` está correto
- Ou deixar em branco para modo demo

### Erro "Invalid API Key"
- Regenerar chave em Binance/OpenAI
- Copiar valor correto em Railway (sem espaços)

## 📚 Documentação Adicional

- [Binance API Docs](https://binance-docs.github.io/apidocs/)
- [OpenAI API Docs](https://platform.openai.com/docs/api-reference)
- [Railway Docs](https://railway.app/docs)
- [Flask Docs](https://flask.palletsprojects.com/)

## 📝 Licença

MIT - Use livremente em seus projetos

## 💡 Suporte

- 📧 Issues no GitHub
- 🐛 Reporte bugs
- 💬 Sugestões são bem-vindas

## ⭐ Se foi útil, deixe uma star!

---

**Desenvolvido com ❤️ para traders de cripto**

**Pronto para Railway! 🚀**
