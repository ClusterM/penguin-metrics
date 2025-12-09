"""
Recursive descent parser for nginx-like configuration syntax.

Parses tokens from the lexer into a hierarchical configuration structure.
Supports nested blocks, directives with values, and include statements.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import glob as glob_module

from .lexer import Lexer, Token, TokenType, LexerError


class ParseError(Exception):
    """Exception raised for parser errors."""
    
    def __init__(self, message: str, token: Token | None = None):
        self.token = token
        if token:
            super().__init__(f"Line {token.line}, column {token.column}: {message}")
        else:
            super().__init__(message)


@dataclass
class Directive:
    """
    A configuration directive with a name and values.
    
    Examples:
        host "localhost";     -> Directive(name="host", values=["localhost"])
        port 1883;            -> Directive(name="port", values=[1883])
        cpu on;               -> Directive(name="cpu", values=[True])
        match name "nginx";   -> Directive(name="match", values=["name", "nginx"])
    """
    name: str
    values: list[Any] = field(default_factory=list)
    line: int = 0
    column: int = 0
    
    def __repr__(self) -> str:
        return f"Directive({self.name}, {self.values})"
    
    @property
    def value(self) -> Any:
        """Get single value (first) or None."""
        return self.values[0] if self.values else None
    
    def get(self, index: int = 0, default: Any = None) -> Any:
        """Get value at index with default."""
        if index < len(self.values):
            return self.values[index]
        return default


@dataclass
class Block:
    """
    A configuration block with a type, optional name, and contents.
    
    Examples:
        mqtt { ... }              -> Block(type="mqtt", name=None, ...)
        system "my-server" { ... } -> Block(type="system", name="my-server", ...)
    """
    type: str
    name: str | None = None
    directives: list[Directive] = field(default_factory=list)
    blocks: list["Block"] = field(default_factory=list)
    line: int = 0
    column: int = 0
    
    def __repr__(self) -> str:
        return f"Block({self.type}, {self.name!r}, directives={len(self.directives)}, blocks={len(self.blocks)})"
    
    def get_directive(self, name: str) -> Directive | None:
        """Get first directive with given name."""
        for d in self.directives:
            if d.name == name:
                return d
        return None
    
    def get_directives(self, name: str) -> list[Directive]:
        """Get all directives with given name."""
        return [d for d in self.directives if d.name == name]
    
    def get_value(self, name: str, default: Any = None) -> Any:
        """Get single value from directive."""
        directive = self.get_directive(name)
        if directive:
            return directive.value
        return default
    
    def get_all_values(self, name: str) -> list[Any]:
        """
        Get all values from all directives with given name.
        
        Useful for directives that can be repeated:
            filter "nvme_*";
            filter "soc_*";
        Returns: ["nvme_*", "soc_*"]
        """
        values = []
        for d in self.directives:
            if d.name == name and d.value is not None:
                values.append(d.value)
        return values
    
    def get_block(self, type_name: str) -> "Block | None":
        """Get first nested block with given type."""
        for b in self.blocks:
            if b.type == type_name:
                return b
        return None
    
    def get_blocks(self, type_name: str) -> list["Block"]:
        """Get all nested blocks with given type."""
        return [b for b in self.blocks if b.type == type_name]


@dataclass
class ConfigDocument:
    """
    Root document containing all top-level blocks and directives.
    """
    blocks: list[Block] = field(default_factory=list)
    directives: list[Directive] = field(default_factory=list)
    filename: str = "<string>"
    
    def get_block(self, type_name: str) -> Block | None:
        """Get first block with given type."""
        for b in self.blocks:
            if b.type == type_name:
                return b
        return None
    
    def get_blocks(self, type_name: str) -> list[Block]:
        """Get all blocks with given type."""
        return [b for b in self.blocks if b.type == type_name]
    
    def get_directive(self, name: str) -> Directive | None:
        """Get first directive with given name."""
        for d in self.directives:
            if d.name == name:
                return d
        return None
    
    def get_value(self, name: str, default: Any = None) -> Any:
        """Get value of first directive with given name."""
        directive = self.get_directive(name)
        if directive and directive.values:
            return directive.values[0]
        return default
    
    def merge(self, other: "ConfigDocument") -> None:
        """Merge another document into this one (for includes)."""
        self.blocks.extend(other.blocks)
        self.directives.extend(other.directives)


class ConfigParser:
    """
    Recursive descent parser for nginx-like configuration.
    
    Grammar:
        document    := (block | directive | include)*
        block       := IDENTIFIER [STRING] '{' (block | directive)* '}'
        directive   := IDENTIFIER value* ';'
        value       := STRING | NUMBER | DURATION | BOOLEAN | IDENTIFIER
        include     := 'include' STRING ';'
    """
    
    def __init__(
        self,
        source: str,
        filename: str = "<string>",
        base_path: Path | None = None,
        included_files: set[str] | None = None,
    ):
        self.lexer = Lexer(source, filename)
        self.filename = filename
        self.base_path = base_path or Path.cwd()
        self.included_files = included_files or set()
        
        self.current_token: Token | None = None
        self.peek_token: Token | None = None
        
        # Prime the parser with first two tokens
        self._advance()
        self._advance()
    
    def _advance(self) -> Token | None:
        """Advance to next token and return previous."""
        previous = self.current_token
        self.current_token = self.peek_token
        self.peek_token = self.lexer.next_token()
        return previous
    
    def _expect(self, token_type: TokenType, message: str = "") -> Token:
        """Expect current token to be of given type, advance and return it."""
        if self.current_token is None:
            raise ParseError("Unexpected end of input")
        
        if self.current_token.type != token_type:
            msg = message or f"Expected {token_type.name}, got {self.current_token.type.name}"
            raise ParseError(msg, self.current_token)
        
        return self._advance()  # type: ignore
    
    def _check(self, token_type: TokenType) -> bool:
        """Check if current token is of given type."""
        return self.current_token is not None and self.current_token.type == token_type
    
    def _check_value(self) -> bool:
        """Check if current token can be a value."""
        if self.current_token is None:
            return False
        return self.current_token.type in (
            TokenType.STRING,
            TokenType.NUMBER,
            TokenType.DURATION,
            TokenType.BOOLEAN,
            TokenType.IDENTIFIER,
        )
    
    def parse(self) -> ConfigDocument:
        """Parse the entire configuration document."""
        doc = ConfigDocument(filename=self.filename)
        
        while not self._check(TokenType.EOF):
            if self._check(TokenType.INCLUDE):
                # Handle include directive
                included = self._parse_include()
                doc.merge(included)
            elif self._check(TokenType.IDENTIFIER):
                # Could be a block or a top-level directive
                result = self._parse_block_or_directive()
                if isinstance(result, Block):
                    doc.blocks.append(result)
                else:
                    doc.directives.append(result)
            else:
                raise ParseError(
                    f"Expected block, directive, or include; got {self.current_token.type.name}",
                    self.current_token,
                )
        
        return doc
    
    def _parse_include(self) -> ConfigDocument:
        """Parse an include directive and load the included file(s)."""
        include_token = self._expect(TokenType.INCLUDE)
        path_token = self._expect(TokenType.STRING, "Expected file path after 'include'")
        self._expect(TokenType.SEMICOLON, "Expected ';' after include path")
        
        pattern = str(path_token.value)
        
        # Resolve relative paths
        if not Path(pattern).is_absolute():
            pattern = str(self.base_path / pattern)
        
        # Expand glob pattern
        paths = sorted(glob_module.glob(pattern))
        
        if not paths:
            # Not an error, just no files matched
            return ConfigDocument()
        
        merged = ConfigDocument()
        
        for path in paths:
            path_obj = Path(path)
            resolved = str(path_obj.resolve())
            
            # Prevent circular includes
            if resolved in self.included_files:
                raise ParseError(
                    f"Circular include detected: {path}",
                    include_token,
                )
            
            if not path_obj.exists():
                raise ParseError(
                    f"Include file not found: {path}",
                    path_token,
                )
            
            # Parse included file
            source = path_obj.read_text()
            new_included = self.included_files | {resolved}
            
            parser = ConfigParser(
                source=source,
                filename=path,
                base_path=path_obj.parent,
                included_files=new_included,
            )
            
            included_doc = parser.parse()
            merged.merge(included_doc)
        
        return merged
    
    def _parse_block_or_directive(self) -> Block | Directive:
        """Parse either a block or a directive."""
        name_token = self._expect(TokenType.IDENTIFIER)
        name = str(name_token.value)
        line = name_token.line
        column = name_token.column
        
        # Collect values until we hit { or ;
        values: list[Any] = []
        block_name: str | None = None
        
        while self._check_value():
            value_token = self._advance()
            if value_token:
                values.append(value_token.value)
        
        if self._check(TokenType.LBRACE):
            # This is a block
            # If there's exactly one string value, it's the block name
            if len(values) == 1 and isinstance(values[0], str):
                block_name = values[0]
            elif len(values) > 1:
                raise ParseError(
                    f"Block '{name}' has too many arguments before '{{'; expected 0 or 1",
                    self.current_token,
                )
            
            return self._parse_block_body(name, block_name, line, column)
        
        elif self._check(TokenType.SEMICOLON):
            # This is a directive
            self._advance()  # consume ;
            return Directive(name=name, values=values, line=line, column=column)
        
        else:
            raise ParseError(
                f"Expected '{{' or ';' after directive '{name}'",
                self.current_token,
            )
    
    def _parse_block_body(
        self, 
        type_name: str, 
        name: str | None, 
        line: int, 
        column: int
    ) -> Block:
        """Parse the body of a block (after the opening brace)."""
        self._expect(TokenType.LBRACE)
        
        block = Block(type=type_name, name=name, line=line, column=column)
        
        while not self._check(TokenType.RBRACE) and not self._check(TokenType.EOF):
            if self._check(TokenType.INCLUDE):
                # Include inside block - merge into current document context
                # but the blocks/directives still go into parent
                included = self._parse_include()
                block.directives.extend(included.directives)
                block.blocks.extend(included.blocks)
            elif self._check(TokenType.IDENTIFIER):
                result = self._parse_block_or_directive()
                if isinstance(result, Block):
                    block.blocks.append(result)
                else:
                    block.directives.append(result)
            else:
                raise ParseError(
                    f"Expected directive or nested block in '{type_name}' block",
                    self.current_token,
                )
        
        self._expect(TokenType.RBRACE, f"Expected '}}' to close '{type_name}' block")
        
        return block


def parse_config(source: str, filename: str = "<string>", base_path: Path | None = None) -> ConfigDocument:
    """
    Convenience function to parse a configuration string.
    
    Args:
        source: Configuration source code
        filename: Filename for error messages
        base_path: Base path for resolving include statements
    
    Returns:
        Parsed ConfigDocument
    """
    parser = ConfigParser(source, filename, base_path)
    return parser.parse()


def parse_config_file(path: str | Path) -> ConfigDocument:
    """
    Parse a configuration file.
    
    Args:
        path: Path to the configuration file
    
    Returns:
        Parsed ConfigDocument
    """
    path = Path(path)
    source = path.read_text()
    return parse_config(source, str(path), path.parent)

