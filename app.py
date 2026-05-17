#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PUMPS - Crypto Trading Bot com IA
WebSocket Binance em tempo real + OpenAI + Radar de Pumps
Pronto para Railway!
"""

import os
import sys
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import logging
from datetime import datetime
import json

# Carregar variáveis de ambiente
load_dotenv()

# Configuração logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Importar módulos do projeto
try:
    from src.binance_client import BinanceClient
    from src.openai_analyzer import OpenAIAnalyzer
    from src.pump_detector import PumpDetector
    from src.utils import setup_logger, validate_env
    logger.info("✅ Módulos importados com sucesso")
except ImportError as e:
    logger.warning(f"⚠️ Aviso ao importar módulos: {e}")
    # Continue mesmo sem alguns módulos
    BinanceClient = None
    OpenAIAnalyzer = None
    PumpDetector = None

# Inicializar Flask
app = Flask(__name__)
CORS(app)

# Configurações
app.config['JSON_SORT_KEYS'] = False
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False

# Inicializar clientes
binance = None
analyzer = None
pump_detector = None

def init_clients():
    """Inicializar clientes com tratamento de erro"""
    global binance, analyzer, pump_detector
    
    # Binance
    if os.getenv('BINANCE_API_KEY') and os.getenv('BINANCE_API_SECRET'):
        try:
            binance = BinanceClient(
                api_key=os.getenv('BINANCE_API_KEY'),
                api_secret=os.getenv('BINANCE_API_SECRET'),
                testnet=os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'
            )
            logger.info("✅ Binance Client inicializado")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar Binance: {e}")
            binance = None
    else:
        logger.warning("⚠️ BINANCE_API_KEY ou BINANCE_API_SECRET não configurados")
        binance = None
    
    # OpenAI
    if os.getenv('OPENAI_API_KEY'):
        try:
            analyzer = OpenAIAnalyzer(api_key=os.getenv('OPENAI_API_KEY'))
            logger.info("✅ OpenAI Analyzer inicializado")
        except Exception as e:
            logger.error(f"❌ Erro ao inicializar OpenAI: {e}")
            analyzer = None
    else:
        logger.warning("⚠️ OPENAI_API_KEY não configurada")
        analyzer = None
    
    # Pump Detector
    try:
        pump_detector = PumpDetector(
            threshold=float(os.getenv('PUMP_THRESHOLD', '5.0')),
            time_window=int(os.getenv('PUMP_TIME_WINDOW', '60')),
            min_volume=float(os.getenv('MIN_VOLUME', '10000'))
        )
        logger.info("✅ Pump Detector inicializado")
    except Exception as e:
        logger.error(f"❌ Erro ao inicializar Pump Detector: {e}")
        pump_detector = None

# ==================== ROTAS ====================

@app.route('/')
def index():
    """Dashboard principal"""
    return render_template('index.html')

@app.route('/api/health')
def health():
    """Health check da API"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0',
        'components': {
            'binance': binance is not None,
            'openai': analyzer is not None,
            'pump_detector': pump_detector is not None
        }
    }), 200

@app.route('/api/prices')
def get_prices():
    """Obter preços em tempo real"""
    try:
        if not binance:
            return jsonify({
                'status': 'demo',
                'message': 'Modo demo - Binance não configurado',
                'symbol': 'BTCUSDT',
                'data': {
                    'price': 45000.00,
                    'bid': 44955.00,
                    'ask': 45045.00
                }
            }), 200
        
        symbol = request.args.get('symbol', 'BTCUSDT')
        prices = binance.get_current_price(symbol)
        
        return jsonify({
            'symbol': symbol,
            'data': prices,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Erro ao obter preços: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pumps')
def get_pumps():
    """Obter pumps detectados"""
    try:
        if not pump_detector:
            return jsonify({
                'status': 'demo',
                'pumps': [
                    {
                        'symbol': 'DOGE',
                        'change_percent': 12.45,
                        'volume': 125000.00,
                        'risk_level': 'MEDIUM',
                        'status': 'SMALL'
                    }
                ],
                'count': 1
            }), 200
        
        pumps = pump_detector.detect_pumps()
        
        return jsonify({
            'pumps': pumps,
            'count': len(pumps),
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Erro ao detectar pumps: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_coin():
    """Analisar moeda com IA"""
    try:
        data = request.get_json()
        symbol = data.get('symbol', 'BTCUSDT') if data else 'BTCUSDT'
        
        if not analyzer:
            return jsonify({
                'status': 'demo',
                'symbol': symbol,
                'analysis': '''{
                    "tendencia": "ALTA",
                    "forca": 7,
                    "suporte": 44000,
                    "resistencia": 46000,
                    "recomendacao": "BUY",
                    "risco": 5,
                    "justificativa": "Modo demo - Análise simulada"
                }'''
            }), 200
        
        analysis = analyzer.analyze_coin(symbol)
        
        return jsonify({
            'symbol': symbol,
            'analysis': analysis,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Erro ao analisar: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sentiment')
def get_sentiment():
    """Obter sentimento do mercado"""
    try:
        if not analyzer:
            return jsonify({
                'status': 'demo',
                'sentiment': {
                    'status': 'NEUTRAL',
                    'confianca': 5,
                    'drivers': ['Bitcoin estável', 'Mercado em consolidação'],
                    'previsao_24h': 'NEUTRAL'
                }
            }), 200
        
        sentiment = analyzer.get_market_sentiment()
        
        return jsonify({
            'sentiment': sentiment,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Erro ao obter sentimento: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts')
def get_alerts():
    """Obter alertas ativos"""
    try:
        alerts = {
            'high_volatility': [],
            'pump_detected': [],
            'price_threshold': []
        }
        
        return jsonify({
            'alerts': alerts,
            'total': 0,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        logger.error(f"Erro ao obter alertas: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    """Rota não encontrada"""
    return jsonify({'error': 'Rota não encontrada', 'status': 404}), 404

@app.errorhandler(500)
def server_error(error):
    """Erro interno do servidor"""
    logger.error(f"Erro 500: {error}")
    return jsonify({'error': 'Erro interno do servidor', 'status': 500}), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    # Inicializar clientes
    init_clients()
    
    # Configurações
    debug_mode = os.getenv('FLASK_ENV', 'production') == 'development'
    port = int(os.getenv('PORT', 5000))
    
    logger.info(f"🚀 PUMPS iniciando na porta {port}")
    logger.info(f"📡 Debug mode: {debug_mode}")
    logger.info(f"🌍 Ambiente: {os.getenv('FLASK_ENV', 'production')}")
    
    # Rodar app
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        use_reloader=debug_mode
    )
