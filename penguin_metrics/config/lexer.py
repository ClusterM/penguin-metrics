"""
Lexer (tokenizer) for nginx-like configuration syntax.

Supports:
- Identifiers (keywords, directive names)
- Quoted strings (double quotes with escape sequences)
- Numbers (integers and floats with optional units like 10s, 5m, 1h)
- Braces, semicolons, and special characters
- Single-line (#) and multi-line (/* */) comments
- Include directives with glob patterns
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator
import re


class TokenType(Enum):
    """Token types for the nginx-like config syntax."""
    
    # Literals
    IDENTIFIER = auto()    # keyword, directive name
    STRING = auto()        # "quoted string"
    NUMBER = auto()        # 123, 45.67
    DURATION = auto()      # 10s, 5m, 1h, 30ms
    BOOLEAN = auto()       # on, off, true, false
    
    # Delimiters
    LBRACE = auto()        # {
    RBRACE = auto()        # }
    SEMICOLON = auto()     # ;
    
    # Special
    INCLUDE = auto()       # include directive
    NEWLINE = auto()       # for error reporting
    EOF = auto()           # end of file
    
    # Error
    ERROR = auto()         # lexer error token


@dataclass
class Token:
    """A single token from the lexer."""
    
    type: TokenType
    value: str | int | float | bool
    line: int
    column: int
    raw: str = ""  # Original text representation
    
    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.column})"


class LexerError(Exception):
    """Exception raised for lexer errors."""
    
    def __init__(self, message: str, line: int, column: int):
        self.line = line
        self.column = column
        super().__init__(f"Line {line}, column {column}: {message}")


class Lexer:
    """
    Tokenizer for nginx-like configuration syntax.
    
    Example config:
        mqtt {
            host "localhost";
            port 1883;
        }
        
        system "my-server" {
            cpu on;
            update_interval 10s;
        }
    """
    
    # Keywords that map to specific token types
    BOOLEAN_KEYWORDS = {"on": True, "off": False, "true": True, "false": False}
    
    # Duration units in seconds
    DURATION_UNITS = {
        "ms": 0.001,
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }
    
    def __init__(self, source: str, filename: str = "<string>"):
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.column = 1
        self.line_start = 0
    
    def _current(self) -> str:
        """Get current character or empty string if at end."""
        if self.pos >= len(self.source):
            return ""
        return self.source[self.pos]
    
    def _peek(self, offset: int = 1) -> str:
        """Peek at character at offset from current position."""
        pos = self.pos + offset
        if pos >= len(self.source):
            return ""
        return self.source[pos]
    
    def _advance(self) -> str:
        """Advance position and return current character."""
        if self.pos >= len(self.source):
            return ""
        
        char = self.source[self.pos]
        self.pos += 1
        
        if char == "\n":
            self.line += 1
            self.column = 1
            self.line_start = self.pos
        else:
            self.column += 1
        
        return char
    
    def _skip_whitespace(self) -> None:
        """Skip whitespace characters (but not newlines for error tracking)."""
        char = self._current()
        while char and char in " \t\r\n":
            self._advance()
            char = self._current()
    
    def _skip_comment(self) -> bool:
        """Skip single-line or multi-line comment. Returns True if skipped."""
        if self._current() == "#":
            # Single-line comment
            while self._current() and self._current() != "\n":
                self._advance()
            return True
        
        if self._current() == "/" and self._peek() == "*":
            # Multi-line comment
            start_line = self.line
            start_col = self.column
            self._advance()  # skip /
            self._advance()  # skip *
            
            while self.pos < len(self.source):
                if self._current() == "*" and self._peek() == "/":
                    self._advance()  # skip *
                    self._advance()  # skip /
                    return True
                self._advance()
            
            raise LexerError("Unterminated multi-line comment", start_line, start_col)
        
        return False
    
    def _skip_whitespace_and_comments(self) -> None:
        """Skip all whitespace and comments."""
        while True:
            self._skip_whitespace()
            if not self._skip_comment():
                break
    
    def _read_string(self) -> Token:
        """Read a quoted string literal."""
        start_line = self.line
        start_col = self.column
        quote_char = self._current()
        self._advance()  # skip opening quote
        
        result = []
        raw = [quote_char]
        
        while self._current() and self._current() != quote_char:
            char = self._current()
            raw.append(char)
            
            if char == "\\":
                self._advance()
                escape_char = self._current()
                raw.append(escape_char)
                
                if escape_char == "n":
                    result.append("\n")
                elif escape_char == "t":
                    result.append("\t")
                elif escape_char == "r":
                    result.append("\r")
                elif escape_char == "\\":
                    result.append("\\")
                elif escape_char == quote_char:
                    result.append(quote_char)
                elif escape_char == "":
                    raise LexerError("Unexpected end of string", self.line, self.column)
                else:
                    result.append(escape_char)
                
                self._advance()
            elif char == "\n":
                raise LexerError("Unterminated string literal", start_line, start_col)
            else:
                result.append(char)
                self._advance()
        
        if not self._current():
            raise LexerError("Unterminated string literal", start_line, start_col)
        
        raw.append(self._current())
        self._advance()  # skip closing quote
        
        return Token(
            type=TokenType.STRING,
            value="".join(result),
            line=start_line,
            column=start_col,
            raw="".join(raw),
        )
    
    def _read_number_or_duration(self) -> Token:
        """Read a number literal, optionally with duration unit."""
        start_line = self.line
        start_col = self.column
        start_pos = self.pos
        
        # Read the numeric part
        has_dot = False
        while self._current() and (self._current().isdigit() or self._current() == "."):
            if self._current() == ".":
                if has_dot:
                    break
                has_dot = True
            self._advance()
        
        # Check for duration unit
        unit_start = self.pos
        while self._current() and self._current().isalpha():
            self._advance()
        
        raw = self.source[start_pos:self.pos]
        unit = self.source[unit_start:self.pos].lower()
        num_str = self.source[start_pos:unit_start]
        
        if unit:
            # Duration with unit
            if unit not in self.DURATION_UNITS:
                raise LexerError(f"Unknown duration unit: {unit}", start_line, start_col)
            
            try:
                num_value = float(num_str) if has_dot else int(num_str)
                seconds = num_value * self.DURATION_UNITS[unit]
            except ValueError:
                raise LexerError(f"Invalid number: {num_str}", start_line, start_col)
            
            return Token(
                type=TokenType.DURATION,
                value=seconds,
                line=start_line,
                column=start_col,
                raw=raw,
            )
        else:
            # Plain number
            try:
                value = float(num_str) if has_dot else int(num_str)
            except ValueError:
                raise LexerError(f"Invalid number: {num_str}", start_line, start_col)
            
            return Token(
                type=TokenType.NUMBER,
                value=value,
                line=start_line,
                column=start_col,
                raw=raw,
            )
    
    def _read_identifier(self) -> Token:
        """Read an identifier or keyword."""
        start_line = self.line
        start_col = self.column
        start_pos = self.pos
        
        # First character already validated as letter or underscore
        while self._current() and (self._current().isalnum() or self._current() in "_-"):
            self._advance()
        
        raw = self.source[start_pos:self.pos]
        value = raw.lower()
        
        # Check for boolean keywords
        if value in self.BOOLEAN_KEYWORDS:
            return Token(
                type=TokenType.BOOLEAN,
                value=self.BOOLEAN_KEYWORDS[value],
                line=start_line,
                column=start_col,
                raw=raw,
            )
        
        # Check for include directive
        if value == "include":
            return Token(
                type=TokenType.INCLUDE,
                value=raw,
                line=start_line,
                column=start_col,
                raw=raw,
            )
        
        return Token(
            type=TokenType.IDENTIFIER,
            value=raw,
            line=start_line,
            column=start_col,
            raw=raw,
        )
    
    def next_token(self) -> Token:
        """Get the next token from the source."""
        self._skip_whitespace_and_comments()
        
        if self.pos >= len(self.source):
            return Token(
                type=TokenType.EOF,
                value="",
                line=self.line,
                column=self.column,
            )
        
        char = self._current()
        start_line = self.line
        start_col = self.column
        
        # Single character tokens
        if char == "{":
            self._advance()
            return Token(TokenType.LBRACE, "{", start_line, start_col, "{")
        
        if char == "}":
            self._advance()
            return Token(TokenType.RBRACE, "}", start_line, start_col, "}")
        
        if char == ";":
            self._advance()
            return Token(TokenType.SEMICOLON, ";", start_line, start_col, ";")
        
        # String literals
        if char == '"' or char == "'":
            return self._read_string()
        
        # Numbers and durations
        if char.isdigit():
            return self._read_number_or_duration()
        
        # Identifiers and keywords
        if char.isalpha() or char == "_":
            return self._read_identifier()
        
        # Unknown character
        raise LexerError(f"Unexpected character: {char!r}", start_line, start_col)
    
    def tokenize(self) -> Iterator[Token]:
        """Generate all tokens from the source."""
        while True:
            token = self.next_token()
            yield token
            if token.type == TokenType.EOF:
                break
    
    def __iter__(self) -> Iterator[Token]:
        """Allow iteration over tokens."""
        return self.tokenize()


def tokenize(source: str, filename: str = "<string>") -> list[Token]:
    """Convenience function to tokenize a source string."""
    return list(Lexer(source, filename))

