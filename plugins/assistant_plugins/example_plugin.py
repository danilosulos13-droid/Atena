
#!/usr/bin/env python3
"""Plugin de exemplo para ATENA Ω."""

def register_plugin():
    """Registra o plugin no sistema."""
    return {
        "name": "example",
        "description": "Plugin de exemplo com comandos úteis",
        "commands": ["/example", "/exemplo", "/demo"],
        "handler": handle_example
    }

def handle_example(args: str) -> str:
    """Handler do plugin example."""
    return f"Plugin example executado com argumentos: {args}\nComandos disponíveis: /example, /exemplo, /demo"
