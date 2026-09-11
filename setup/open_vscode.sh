#!/bin/bash
# =============================================================================
# 🔱 ATENA - Abrir VS Code
# =============================================================================
# Script para abrir VS Code com a pasta do projeto ATENA

set -e

# Detectar diretório raiz
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}🔱 ATENA - Abrindo VS Code...${NC}\n"

# Verificar se VS Code está instalado
if ! command -v code &> /dev/null; then
    echo -e "${RED}❌ ERRO: VS Code não está instalado ou não está no PATH${NC}"
    echo -e "${YELLOW}Instale em: https://code.visualstudio.com${NC}"
    exit 1
fi

# Verificar se o diretório existe
if [[ ! -d "$ROOT_DIR" ]]; then
    echo -e "${RED}❌ ERRO: Diretório do projeto não encontrado: $ROOT_DIR${NC}"
    exit 1
fi

# Abrir VS Code
echo -e "${GREEN}✅ Abrindo VS Code em: $ROOT_DIR${NC}"
code "$ROOT_DIR" &

# Dar feedback
sleep 1
echo -e "${GREEN}✅ VS Code iniciado com sucesso!${NC}"
echo -e "${CYAN}Extensões recomendadas para ATENA:${NC}"
echo "  • Python"
echo "  • Pylance"
echo "  • Black Formatter"
echo "  • Pylint"
echo "  • Better Comments"
echo "  • GitLens"
