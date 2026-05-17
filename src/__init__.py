"""PUMPS - Crypto Trading Bot com IA"""

__version__ = "1.0.0"
__author__ = "hefestox"
__email__ = "dev@pumps.bot"

from .binance_client import BinanceClient
from .openai_analyzer import OpenAIAnalyzer
from .pump_detector import PumpDetector
from .utils import setup_logger, validate_env

__all__ = [
    'BinanceClient',
    'OpenAIAnalyzer',
    'PumpDetector',
    'setup_logger',
    'validate_env'
]
