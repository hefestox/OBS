#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cliente Binance WebSocket - Conecta em tempo real
"""

import logging
import json
import asyncio
from typing import Dict, List, Optional, Callable
from datetime import datetime
from binance.spot import Spot
from binance.websocket.spot.websocket_client import SpotWebsocketClient
import pandas as pd

logger = logging.getLogger(__name__)


class BinanceClient:
    """Cliente Binance com suporte a WebSocket e REST API"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        """Inicializar cliente Binance
        
        Args:
            api_key: Chave de API Binance
            api_secret: Secret de API Binance
            testnet: Usar testnet (True) ou mainnet (False)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.prices_cache = {}
        self.volume_cache = {}
        self.callbacks = []
        
        # Inicializar cliente REST
        self.client = Spot(
            api_key=api_key,
            api_secret=api_secret,
            base_url="https://testnet.binance.vision" if testnet else "https://api.binance.com"
        )
        
        # Inicializar WebSocket
        self.ws_client = SpotWebsocketClient(
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        
        logger.info(f"✅ BinanceClient inicializado ({'testnet' if testnet else 'mainnet'})")
    
    def get_current_price(self, symbol: str) -> Dict:
        """Obter preço atual de um símbolo
        
        Args:
            symbol: Ex: BTCUSDT
            
        Returns:
            Dicionário com informações de preço
        """
        try:
            ticker = self.client.ticker_price(symbol)
            
            price_data = {
                'symbol': symbol,
                'price': float(ticker['price']),
                'timestamp': datetime.now().isoformat(),
                'bid': float(ticker['price']) * 0.99,  # Aproximado
                'ask': float(ticker['price']) * 1.01   # Aproximado
            }
            
            self.prices_cache[symbol] = price_data
            return price_data
            
        except Exception as e:
            logger.error(f"Erro ao obter preço de {symbol}: {e}")
            return {}
    
    def get_24h_ticker(self, symbol: str) -> Dict:
        """Obter dados de 24 horas
        
        Args:
            symbol: Ex: BTCUSDT
            
        Returns:
            Dicionário com dados de 24h
        """
        try:
            ticker = self.client.ticker_24hr(symbol)
            
            return {
                'symbol': symbol,
                'price': float(ticker['lastPrice']),
                'high': float(ticker['highPrice']),
                'low': float(ticker['lowPrice']),
                'volume': float(ticker['volume']),
                'change': float(ticker['priceChangePercent']),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter 24h ticker de {symbol}: {e}")
            return {}
    
    def get_klines(self, symbol: str, interval: str = '1m', limit: int = 100) -> List[Dict]:
        """Obter velas (candlesticks)
        
        Args:
            symbol: Ex: BTCUSDT
            interval: 1m, 5m, 15m, 1h, etc
            limit: Número de velas
            
        Returns:
            Lista de velas
        """
        try:
            klines = self.client.klines(symbol, interval, limit=limit)
            
            data = []
            for kline in klines:
                data.append({
                    'open_time': datetime.fromtimestamp(kline[0] / 1000).isoformat(),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[7]),
                    'timestamp': datetime.now().isoformat()
                })
            
            return data
            
        except Exception as e:
            logger.error(f"Erro ao obter klines de {symbol}: {e}")
            return []
    
    def subscribe_price(self, symbols: List[str], callback: Optional[Callable] = None):
        """Inscrever em atualizações de preço via WebSocket
        
        Args:
            symbols: Lista de símbolos (ex: ['BTCUSDT', 'ETHUSDT'])
            callback: Função callback para processar dados
        """
        try:
            for symbol in symbols:
                stream = f"{symbol.lower()}@trade"
                self.ws_client.trade(stream)
                logger.info(f"📡 Inscrito em {stream}")
            
            if callback:
                self.callbacks.append(callback)
                
        except Exception as e:
            logger.error(f"Erro ao inscrever em preços: {e}")
    
    def subscribe_klines(self, symbols: List[str], interval: str = '1m'):
        """Inscrever em atualizações de velas
        
        Args:
            symbols: Lista de símbolos
            interval: Intervalo de tempo (1m, 5m, 15m, etc)
        """
        try:
            for symbol in symbols:
                stream = f"{symbol.lower()}@kline_{interval}"
                self.ws_client.kline(stream)
                logger.info(f"📡 Inscrito em {stream}")
                
        except Exception as e:
            logger.error(f"Erro ao inscrever em klines: {e}")
    
    def _on_message(self, message):
        """Callback para mensagens WebSocket"""
        try:
            data = json.loads(message)
            logger.debug(f"📥 Mensagem recebida: {data.get('s', 'N/A')}")
            
            # Processar callbacks
            for callback in self.callbacks:
                callback(data)
                
        except Exception as e:
            logger.error(f"Erro ao processar mensagem: {e}")
    
    def _on_error(self, message):
        """Callback para erros WebSocket"""
        logger.error(f"❌ Erro WebSocket: {message}")
    
    def _on_close(self, message):
        """Callback para fechamento WebSocket"""
        logger.warning(f"⚠️ WebSocket fechado: {message}")
    
    def get_top_gainers(self, limit: int = 10) -> List[Dict]:
        """Obter top moedas em alta (24h)
        
        Args:
            limit: Número de moedas
            
        Returns:
            Lista de moedas em alta
        """
        try:
            # Obter lista de símbolos USDT
            exchange_info = self.client.exchange_info()
            symbols = [s['symbol'] for s in exchange_info['symbols'] if s['symbol'].endswith('USDT')]
            
            gainers = []
            for symbol in symbols[:50]:  # Verificar top 50 por performance
                ticker = self.client.ticker_24hr(symbol)
                change = float(ticker['priceChangePercent'])
                
                if change > 0:
                    gainers.append({
                        'symbol': symbol,
                        'change': change,
                        'price': float(ticker['lastPrice']),
                        'volume': float(ticker['volume'])
                    })
            
            # Ordenar por maior mudança
            gainers.sort(key=lambda x: x['change'], reverse=True)
            return gainers[:limit]
            
        except Exception as e:
            logger.error(f"Erro ao obter top gainers: {e}")
            return []
