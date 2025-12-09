"""
Configuration parsing module with nginx-like syntax support.
"""

from .lexer import Lexer, Token, TokenType
from .loader import ConfigLoader
from .parser import ConfigParser
from .schema import Config

__all__ = [
    "Lexer",
    "Token",
    "TokenType",
    "ConfigParser",
    "Config",
    "ConfigLoader",
]
