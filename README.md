# 🚀 PUMPS - Crypto Trading Bot com IA

**WebSocket Binance em tempo real + OpenAI + Radar de Pumps + Dashboard Profissional**

## ✨ Features

- 🔴 **WebSocket Binance** - Conecta em tempo real com Binance API
- 🤖 **IA OpenAI** - Análise inteligente de moedas com GPT-4
- ⚡ **Radar de Pumps** - Detecta pump and dump automático
- 📊 **TradingView** - Gráficos integrados
- 🌐 **API REST** - 10+ endpoints prontos
- 🎨 **Dashboard** - Interface web responsiva e profissional
- 🐳 **Docker** - Containerizado pronto para produção
- 🚂 **Railway Ready** - Deploy em 1 clique

## 📋 Requisitos

- Python 3.11+
- API Key Binance (testnet ou real)
- API Key OpenAI
- Docker (opcional)

## 🚀 Quick Start (Local)

### 1. Clonar repositório
```bash
git clone https://github.com/hefestox/OBS.git
cd OBS
```

### 2. Criar ambiente virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\\Scripts\\activate  # Windows
```

### 3. Instalar dependências
```bash
pip install -r requirements.txt
```

### 4. Configurar variáveis
```bash
cp .env.example .env
# Editar .env com suas credenciais
```

### 5. Rodar aplicação
```bash
python app.py
# Acessar: http://localhost:5000
```

## 🐳 Deploy com Docker

### Local
```bash
docker build -t pumps:latest .
docker run -p 5000:5000 --env-file .env pumps:latest
```

### Railway
1. Conectar repositório no [Railway](https://railway.app)
2. Adicionar variáveis de ambiente
3. Deploy automático! 🎉

## 📚 API Endpoints

### Health Check
```bash
GET /api/health
```

### Preços em Tempo Real
```bash
GET /api/prices?symbol=BTCUSDT
```

### Pumps Detectados
```bash
GET /api/pumps
```

### Análise IA
```bash
POST /api/analyze
Body: {"symbol": "ETHUSDT"}
```

### Sentimento de Mercado
```bash
GET /api/sentiment
```

### Alertas Ativos
```bash
GET /api/alerts
```

## 📁 Estrutura do Projeto

```
.
├── app.py                 # Aplicação Flask principal
├── requirements.txt       # Dependências
├── .env.example          # Template de config
├── Dockerfile            # Container
├── railway.json          # Config Railway
│
├── src/                  # Módulos principais
│   ├── binance_client.py    # WebSocket Binance
│   ├── openai_analyzer.py   # IA OpenAI
│   ├── pump_detector.py     # Detector de pumps
│   └── utils.py             # Funções auxiliares
│
├── api/                  # Rotas da API
│   ├── routes.py           # Endpoints
│   └── websocket.py        # WebSocket (opcional)
│
├── templates/            # HTML
│   ├── index.html          # Dashboard
│   ├── chart.html          # Gráficos
│   └── alerts.html         # Alertas
│
└── static/               # CSS/JS/Imagens
    ├── css/
    │   └── style.css
    ├── js/
    │   ├── dashboard.js
    │   ├── websocket.js
    │   └── chart.js
    └── img/
```

## 🔧 Configuração

### Binance API
1. Ir em [Binance API](https://www.binance.com/en/account/api-management)
2. Criar nova key (testnet recomendado)
3. Copiar API Key e Secret para `.env`

### OpenAI API
1. Ir em [OpenAI](https://platform.openai.com)
2. Criar API Key
3. Adicionar em `.env`

## 📊 Dashboard

Acesse em `http://localhost:5000` após iniciar:

- **Home**: Visão geral de mercado
- **Gráficos**: Preços em tempo real
- **Pumps**: Moedas em pump
- **Alertas**: Notificações ativas
- **Análise IA**: Recomendações do GPT-4

## 🚨 Alertas Suportados

- 📈 Pump detectado
- 💥 Alta volatilidade
- 💰 Limiar de preço atingido
- 📉 Queda significativa
- 🔊 Volume anormal

## ⚙️ Variáveis de Ambiente

```env
# Flask
FLASK_ENV=development
PORT=5000

# Binance
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
BINANCE_TESTNET=true

# OpenAI
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4

# Pump Detection
PUMP_THRESHOLD=5.0
PUMP_TIME_WINDOW=60
MIN_VOLUME=10000
```

## 🤝 Contribuição

Contribuições são bem-vindas! Por favor:

1. Fork o projeto
2. Crie uma branch (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add AmazingFeature'`)
4. Push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

## 📝 Licença

MIT - veja [LICENSE](LICENSE) para detalhes

## 📧 Suporte

Encontre um bug ou tem uma sugestão? Abra uma [Issue](https://github.com/hefestox/OBS/issues)

## 🙌 Créditos

Desenvolvido com ❤️ para traders de crypto

---

**⭐ Se foi útil, deixe uma star!**
