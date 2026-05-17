#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Detector de Pumps - Identifica pump and dump automático
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PumpDetector:
    """Detector automático de pump and dump"""
    
    def __init__(self, threshold: float = 5.0, time_window: int = 60, min_volume: float = 10000):
        """Inicializar detector
        
        Args:
            threshold: Percentual mínimo de aumento para considerar pump (%)
            time_window: Janela de tempo para análise (minutos)
            min_volume: Volume mínimo em USDT
        """
        self.threshold = threshold
        self.time_window = time_window
        self.min_volume = min_volume
        self.pump_history = {}
        
        logger.info(f"✅ PumpDetector inicializado (threshold: {threshold}%, window: {time_window}min)")
    
    def detect_pumps(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        """Detectar pumps ativos
        
        Args:
            symbols: Lista de símbolos para verificar
            
        Returns:
            Lista de pumps detectados
        """
        pumps = []
        
        # Exemplo com símbolos simulados
        test_symbols = symbols or [
            'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'XRPUSDT',
            'DOGEUSDT', 'MATICUSDT', 'SOLANAUSDT', 'LTCUSDT', 'UNIUSDT'
        ]
        
        for symbol in test_symbols:
            pump_data = self._analyze_symbol(symbol)
            if pump_data:
                pumps.append(pump_data)
        
        return pumps
    
    def _analyze_symbol(self, symbol: str) -> Optional[Dict]:
        """Analisar símbolo individual
        
        Args:
            symbol: Símbolo a analisar
            
        Returns:
            Dados do pump ou None
        """
        try:
            # Simulação de dados (em produção, seriam dados reais)
            change = np.random.uniform(-2, 15)
            volume = np.random.uniform(50000, 500000)
            
            if change >= self.threshold and volume >= self.min_volume:
                pump = {
                    'symbol': symbol,
                    'change_percent': round(change, 2),
                    'volume': round(volume, 2),
                    'risk_level': self._calculate_risk(change, volume),
                    'detected_time': datetime.now().isoformat(),
                    'status': self._classify_pump(change)
                }
                
                self.pump_history[symbol] = pump
                logger.warning(f"⚡ PUMP DETECTADO: {symbol} ({change:.2f}%)")
                
                return pump
                
        except Exception as e:
            logger.error(f"Erro ao analisar {symbol}: {e}")
        
        return None
    
    def _calculate_risk(self, change: float, volume: float) -> str:
        """Calcular nível de risco
        
        Args:
            change: Mudança percentual
            volume: Volume em USDT
            
        Returns:
            Nível de risco (LOW, MEDIUM, HIGH)
        """
        risk_score = 0
        
        # Mudança muito alta = risco alto
        if change > 20:
            risk_score += 3
        elif change > 10:
            risk_score += 2
        else:
            risk_score += 1
        
        # Volume baixo = risco alto
        if volume < 50000:
            risk_score += 3
        elif volume < 100000:
            risk_score += 1
        
        if risk_score >= 5:
            return 'HIGH'
        elif risk_score >= 3:
            return 'MEDIUM'
        else:
            return 'LOW'
    
    def _classify_pump(self, change: float) -> str:
        """Classificar tipo de pump
        
        Args:
            change: Mudança percentual
            
        Returns:
            Classificação (MICRO, SMALL, MEDIUM, LARGE)
        """
        if change > 50:
            return 'LARGE'
        elif change > 20:
            return 'MEDIUM'
        elif change > 10:
            return 'SMALL'
        else:
            return 'MICRO'
    
    def get_pump_history(self, limit: int = 10) -> List[Dict]:
        """Obter histórico de pumps
        
        Args:
            limit: Número máximo de registros
            
        Returns:
            Lista de pumps históricos
        """
        history = list(self.pump_history.values())
        return sorted(history, key=lambda x: x['change_percent'], reverse=True)[:limit]
    
    def detect_reversal(self, symbol: str, price_history: List[float]) -> Dict:
        """Detectar reversão de preço (dump after pump)
        
        Args:
            symbol: Símbolo
            price_history: Histórico de preços
            
        Returns:
            Dados de reversão
        """
        try:
            if len(price_history) < 2:
                return {}
            
            # Calcular mudança
            change_percent = ((price_history[-1] - price_history[0]) / price_history[0]) * 100
            
            # Detectar máximo local
            max_price = max(price_history)
            current_drop = ((max_price - price_history[-1]) / max_price) * 100
            
            if current_drop > 5:  # Drop de mais de 5%
                return {
                    'symbol': symbol,
                    'reversal_detected': True,
                    'drop_percent': round(current_drop, 2),
                    'max_price': max_price,
                    'current_price': price_history[-1],
                    'severity': 'HIGH' if current_drop > 15 else 'MEDIUM' if current_drop > 10 else 'LOW'
                }
            
        except Exception as e:
            logger.error(f"Erro ao detectar reversão: {e}")
        
        return {}
