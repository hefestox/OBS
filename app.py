#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PUMPS - Crypto Trading Bot com IA
WebSocket Binance em tempo real + OpenAI + Radar de Pumps
"""

import os
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import logging
from datetime import datetime
import json

# Importar módulos do projeto
from src.binance_client import BinanceClient
from src.openai_analyzer import OpenAIAnalyzer
from src.pump_detector import PumpDetector
from src.utils import setup_logger, validate_env

# Carregar variáveis de ambiente
load_dotenv()

# Configuração logging
logger = setup_logger(__name__)

# Inicializar Flask
app = Flask(__name__)
CORS(app)

# Configurações
app.config['JSON_SORT_KEYS'] = False
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = False

# Validar ambiente
validate_env()

# Inicializar clientes
try:
    binance = BinanceClient(
        api_key=os.getenv('BINANCE_API_KEY'),
        api_secret=os.getenv('BINANCE_API_SECRET')
    )
    logger.info("✅ Binance Client inicializado")
except Exception as e:
    logger.error(f"❌ Erro ao inicializar Binance: {e}")
    binance = None

try:
    analyzer = OpenAIAnalyzer(api_key=os.getenv('OPENAI_API_KEY'))
    logger.info("✅ OpenAI Analyzer inicializado")
except Exception as e:
    logger.error(f"❌ Erro ao inicializar OpenAI: {e}")
    analyzer = None

try:
    pump_detector = PumpDetector()
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
    })

@app.route('/api/prices')
def get_prices():
    """Obter preços em tempo real"""
    try:
        if not binance:
            return jsonify({'error': 'Binance client não disponível'}), 503
        
        symbol = request.args.get('symbol', 'BTCUSDT')
        prices = binance.get_current_price(symbol)
        
        return jsonify({
            'symbol': symbol,
            'data': prices,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Erro ao obter preços: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pumps')
def get_pumps():
    """Obter pumps detectados"""
    try:
        if not pump_detector:
            return jsonify({'error': 'Pump Detector não disponível'}), 503
        
        pumps = pump_detector.detect_pumps()
        
        return jsonify({
            'pumps': pumps,
            'count': len(pumps),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Erro ao detectar pumps: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_coin():
    """Analisar moeda com IA"""
    try:
        if not analyzer:
            return jsonify({'error': 'OpenAI Analyzer não disponível'}), 503
        
        data = request.get_json()
        symbol = data.get('symbol')
        
        if not symbol:
            return jsonify({'error': 'Symbol é obrigatório'}), 400
        
        analysis = analyzer.analyze_coin(symbol)
        
        return jsonify({
            'symbol': symbol,
            'analysis': analysis,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Erro ao analisar: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sentiment')
def get_sentiment():
    """Obter sentimento do mercado"""
    try:
        if not analyzer:
            return jsonify({'error': 'OpenAI Analyzer não disponível'}), 503
        
        sentiment = analyzer.get_market_sentiment()
        
        return jsonify({
            'sentiment': sentiment,
            'timestamp': datetime.now().isoformat()
        })
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
        })
    except Exception as e:
        logger.error(f"Erro ao obter alertas: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    """Rota não encontrada"""
    return jsonify({'error': 'Rota não encontrada'}), 404

@app.errorhandler(500)
def server_error(error):
    """Erro interno do servidor"""
    logger.error(f"Erro 500: {error}")
    return jsonify({'error': 'Erro interno do servidor'}), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_ENV', 'development') == 'development'
    port = int(os.getenv('PORT', 5000))
    
    logger.info(f"🚀 Iniciando PUMPS na porta {port}")
    logger.info(f"📊 Debug mode: {debug_mode}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        use_reloader=debug_mode
    )
