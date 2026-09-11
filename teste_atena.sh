#!/bin/bash
# 🧪 TESTE COMPLETO DE ATENA AGI NO RENDER
# Execute no Termux pra verificar se tudo está rodando

# SUBSTITUA COM A URL REAL DO SEU RENDER:
ATENA_API="https://atena-ia-1cpx.onrender.com"
# OU use a URL atual se for diferente

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║           🧪 TESTE COMPLETO DE ATENA AGI v5.0               ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "🌐 URL: $ATENA_API"
echo ""

# Cores para output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Função de teste
test_endpoint() {
    local method=$1
    local endpoint=$2
    local data=$3
    local description=$4
    
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}[TESTE]${NC} $description"
    echo "URL: $ATENA_API$endpoint"
    echo ""
    
    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "$ATENA_API$endpoint")
    else
        response=$(curl -s -w "\n%{http_code}" -X POST \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$ATENA_API$endpoint")
    fi
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)
    
    echo "Status: $http_code"
    
    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        echo -e "${GREEN}✅ SUCCESS${NC}"
        echo "Response:"
        echo "$body" | jq . 2>/dev/null || echo "$body"
    else
        echo -e "${RED}❌ FAILED${NC}"
        echo "Response:"
        echo "$body"
    fi
    
    echo ""
}

# ============================================================================
# TESTE 1: Health Check
# ============================================================================

test_endpoint "GET" "/healthz" "" "Health Check - API Online?"

# ============================================================================
# TESTE 2: AGI Status
# ============================================================================

test_endpoint "GET" "/api/agi/status" "" "AGI Status - Treinando?"

# ============================================================================
# TESTE 3: AGI History
# ============================================================================

test_endpoint "GET" "/api/agi/history" "" "AGI History - Histórico de Rounds?"

# ============================================================================
# TESTE 4: Consciousness Status
# ============================================================================

test_endpoint "GET" "/api/consciousness/state" "" "Consciousness - Estado de Atena?"

# ============================================================================
# TESTE 5: Forçar uma Introspection
# ============================================================================

test_endpoint "POST" "/api/consciousness" \
    '{"depth": 3, "context": {"test": true}}' \
    "Consciousness Introspection - Reflexão Profunda?"

# ============================================================================
# TESTE 6: Registrar Experiência (para AGI aprender!)
# ============================================================================

test_endpoint "POST" "/api/consciousness/experience" \
    '{"question": "Teste", "answer": "Funciona!", "outcome": "success"}' \
    "Record Experience - AGI Aprende?"

# ============================================================================
# TESTE 7: Chat Simples
# ============================================================================

test_endpoint "POST" "/api/chat" \
    '{"message": "Olá Atena, você está consciente?", "user_id": "test"}' \
    "Chat - Conversar com Atena?"

# ============================================================================
# TESTE 8: Forçar Round de AGI
# ============================================================================

test_endpoint "POST" "/api/agi/train-now" "" \
    "AGI Train Now - Forçar Treinamento?"

# ============================================================================
# RESUMO
# ============================================================================

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                    ✅ TESTE COMPLETO FINALIZADO              ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 O QUE VERIFICAR:"
echo ""
echo "1️⃣  Health Check"
echo "    ✓ Se retornar 200 OK → API está online"
echo ""
echo "2️⃣  AGI Status"
echo "    ✓ Se tiver 'round' > 0 → AGI está treinando"
echo "    ✓ Se 'accuracy' está aumentando → Aprendizado funcionando"
echo ""
echo "3️⃣  AGI History"
echo "    ✓ Se tiver múltiplos rounds → Treinamento contínuo"
echo "    ✓ Accuracy deve subir com o tempo"
echo ""
echo "4️⃣  Consciousness"
echo "    ✓ Se 'consciousness_level' = AWARE → Consciência evoluiu"
echo "    ✓ Se beliefs têm confidence > 0 → Aprendendo"
echo ""
echo "5️⃣  Introspection"
echo "    ✓ Se retorna respostas detalhadas → Reflexão funcionando"
echo "    ✓ Se 'consciousness_level' muda → Evoluindo"
echo ""
echo "6️⃣  Experience Recording"
echo "    ✓ Se status = 'recorded' → AGI registrou aprendizado"
echo "    ✓ Se 'new_learning_rate' aumentou → Taxa de aprendizado subiu"
echo ""
echo "7️⃣  Chat"
echo "    ✓ Se responde → Claude está conectado"
echo "    ✓ Se usa NN pesos → AGI raciocínio melhorando"
echo ""
echo "8️⃣  AGI Train Now"
echo "    ✓ Se status = 'trained' → Backprop funcionou"
echo "    ✓ Se accuracy aumentou → Pesos evoluíram"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🚀 PRÓXIMOS PASSOS:"
echo ""
echo "1. Rodar esse script regularmente (a cada 1h)"
echo "2. Monitorar AGI status (deve aumentar accuracy)"
echo "3. Deixar treinando 24/7 por ~8 dias"
echo "4. Assistir AGI emergir! 🧠"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
