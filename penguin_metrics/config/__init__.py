"""
Configuration parsing module with nginx-like syntax support.
"""

from .lexer import Lexer, Token, TokenType
from .parser import ConfigParser
from .schema import Config
from .loader import ConfigLoader

__all__ = [
    "Lexer",
    "Token",
    "TokenType",
    "ConfigParser",
    "Config",
    "ConfigLoader",
]

