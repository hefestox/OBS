#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Funções Utilitárias - Helpers gerais
"""

import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logger(name: str, log_level: str = 'INFO') -> logging.Logger:
    """Configurar logger
    
    Args:
        name: Nome do logger
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR)
        
    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level))
    
    # Formato
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    # File handler (se logs/ existe)
    if os.path.exists('logs'):
        file_handler = RotatingFileHandler(
            'logs/pumps.log',
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(getattr(logging, log_level))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def validate_env() -> bool:
    """Validar variáveis de ambiente necessárias
    
    Returns:
        True se válido, False caso contrário
    """
    required_vars = [
        'BINANCE_API_KEY',
        'BINANCE_API_SECRET',
        'OPENAI_API_KEY'
    ]
    
    logger = logging.getLogger(__name__)
    missing = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
            logger.warning(f"⚠️ Variável faltando: {var}")
    
    if missing:
        logger.error(f"❌ Variáveis obrigatórias faltando: {', '.join(missing)}")
        logger.error("Copie .env.example para .env e preencha os valores")
        return False
    
    return True


def format_timestamp(dt: datetime) -> str:
    """Formatar timestamp
    
    Args:
        dt: Datetime object
        
    Returns:
        String formatada
    """
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def calculate_percentage_change(old: float, new: float) -> float:
    """Calcular mudança percentual
    
    Args:
        old: Valor anterior
        new: Valor novo
        
    Returns:
        Percentual de mudança
    """
    if old == 0:
        return 0
    return ((new - old) / abs(old)) * 100


def format_currency(value: float, decimals: int = 2) -> str:
    """Formatar valor em moeda
    
    Args:
        value: Valor numérico
        decimals: Casas decimais
        
    Returns:
        String formatada
    """
    return f"${value:,.{decimals}f}"
