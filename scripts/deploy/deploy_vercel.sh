#!/usr/bin/env bash
# =============================================================================
# 🔱 ATENA Ω - Vercel Automation Deploy Script
# =============================================================================
# Este script automatiza o deploy da Atena no Vercel, configurando
# as variáveis de ambiente necessárias e realizando o push.
#
# Uso: bash scripts/deploy_vercel.sh
# =============================================================================

set -e

# Cores para output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🔱 Iniciando automação de deploy da ATENA Ω no Vercel...${NC}"

# 1. Verificar Vercel CLI
if ! command -v vercel &> /dev/null; then
    echo -e "${YELLOW}Vercel CLI não encontrada. Instalando...${NC}"
    npm install -g vercel
fi

# 2. Verificar Login
echo -e "${BLUE}Verificando autenticação...${NC}"
vercel whoami || (echo -e "${YELLOW}Por favor, faça login no Vercel primeiro:${NC}" && vercel login)

# 3. Configurar Variáveis de Ambiente (Interativo se não existirem)
echo -e "${BLUE}Configurando ambiente de produção...${NC}"

# Função para adicionar segredo se não existir
add_env() {
    local key=$1
    local val=$2
    echo -n "Configurando $key... "
    echo "$val" | vercel env add "$key" production --force &> /dev/null || echo -e "${YELLOW}Já configurado${NC}"
    echo -e "${GREEN}OK${NC}"
}

# Variáveis críticas para a Atena
# Nota: O usuário deve ter essas variáveis no seu shell ou o script pedirá
read -p "Digite sua GEMINI_API_KEY: " GEMINI_API_KEY
read -p "Digite sua ATENA_API_KEY (para segurança da API): " ATENA_API_KEY
read -p "Digite sua REDIS_URL (recomendado para persistência): " REDIS_URL

add_env "GEMINI_API_KEY" "$GEMINI_API_KEY"
add_env "ATENA_API_KEY" "$ATENA_API_KEY"
add_env "REDIS_URL" "$REDIS_URL"
add_env "ATENA_ENV" "production"
add_env "ENABLE_RATE_LIMIT" "true"
add_env "ENABLE_CACHE" "true"

# 4. Executar Deploy
echo -e "${BLUE}Realizando deploy para produção...${NC}"
vercel --prod --yes

echo -e "${GREEN}✅ Deploy da ATENA Ω concluído com sucesso!${NC}"
echo -e "${BLUE}Acesse o painel do Vercel para monitorar os logs.${NC}"
