#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analisador OpenAI - Análise inteligente de moedas com GPT-4
"""

import logging
from typing import Dict, Optional
from datetime import datetime
import openai

logger = logging.getLogger(__name__)


class OpenAIAnalyzer:
    """Analisador de moedas com OpenAI GPT"""
    
    def __init__(self, api_key: str, model: str = "gpt-4"):
        """Inicializar analisador
        
        Args:
            api_key: API Key da OpenAI
            model: Modelo a usar (gpt-4, gpt-3.5-turbo, etc)
        """
        self.api_key = api_key
        self.model = model
        openai.api_key = api_key
        
        logger.info(f"✅ OpenAIAnalyzer inicializado (modelo: {model})")
    
    def analyze_coin(self, symbol: str, market_data: Optional[Dict] = None) -> Dict:
        """Analisar uma moeda específica
        
        Args:
            symbol: Símbolo da moeda (ex: BTCUSDT)
            market_data: Dados de mercado opcionais
            
        Returns:
            Análise da moeda
        """
        try:
            # Prompt para análise
            prompt = f"""
            Você é um especialista em análise técnica e fundamental de criptomoedas.
            Analise a moeda {symbol} com base em:
            
            - Tendências de preço recentes
            - Volume de negociação
            - Suporte e resistência
            - Sentimento do mercado
            - Notícias relevantes
            
            Forneça uma análise concisa com:
            1. Tendência (ALTA, NEUTRAL, BAIXA)
            2. Força da tendência (1-10)
            3. Principais suportes e resistências
            4. Recomendação (BUY, HOLD, SELL)
            5. Nível de risco (1-10)
            6. Justificativa breve
            
            Responda em formato JSON estruturado.
            """
            
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é um especialista em trading de criptomoedas."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            analysis_text = response['choices'][0]['message']['content']
            
            return {
                'symbol': symbol,
                'analysis': analysis_text,
                'model': self.model,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erro ao analisar {symbol}: {e}")
            return {'error': str(e)}
    
    def get_market_sentiment(self, coins: Optional[list] = None) -> Dict:
        """Obter sentimento geral do mercado
        
        Args:
            coins: Lista de moedas para análise
            
        Returns:
            Sentimento do mercado
        """
        try:
            coins_str = ", ".join(coins) if coins else "Bitcoin, Ethereum, e principais altcoins"
            
            prompt = f"""
            Analise o sentimento atual do mercado de criptomoedas para: {coins_str}
            
            Considere:
            - Tendência geral de mercado
            - Notícias recentes (últimas 24h)
            - Volume de negociação
            - Movimento de preços
            - Comportamento institucional
            
            Forneça:
            1. Sentimento geral (BULLISH, NEUTRAL, BEARISH)
            2. Confiança (1-10)
            3. Principais drivers
            4. Previsão 24h (ALTA, NEUTRAL, BAIXA)
            5. Resumo executivo
            
            Responda em JSON estruturado.
            """
            
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é um analista de mercado cripto."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=400
            )
            
            sentiment_text = response['choices'][0]['message']['content']
            
            return {
                'sentiment': sentiment_text,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter sentimento: {e}")
            return {'error': str(e)}
    
    def predict_pump(self, symbol: str, indicators: Optional[Dict] = None) -> Dict:
        """Prever possível pump em uma moeda
        
        Args:
            symbol: Símbolo da moeda
            indicators: Indicadores técnicos
            
        Returns:
            Predição de pump
        """
        try:
            indicators_str = str(indicators) if indicators else "indicadores técnicos padrão"
            
            prompt = f"""
            Baseado em análise técnica e padrões de pump-and-dump,
            qual é a probabilidade de {symbol} sofrer pump nos próximos:
            - 1 hora
            - 4 horas
            - 24 horas
            
            Indicadores: {indicators_str}
            
            Responda com:
            1. Probabilidade de pump (0-100%) para cada período
            2. Sinais de alerta detectados
            3. Nível de risco
            4. Recomendação
            5. Padrões observados
            
            Responda em JSON.
            """
            
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Você é especialista em detectar padrões de pump."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_tokens=350
            )
            
            prediction_text = response['choices'][0]['message']['content']
            
            return {
                'symbol': symbol,
                'prediction': prediction_text,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erro ao prever pump: {e}")
            return {'error': str(e)}
