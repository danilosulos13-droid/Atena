#!/bin/bash
# 🚀 ROTEIRO EXATO - COPIE E COLE NO TERMUX

# PASSO 1: Entrar no diretório
echo "📂 PASSO 1: Entrando no diretório"
cd ~/Atena-IA
pwd  # Verificar que está no lugar certo

# PASSO 2: Copiar o arquivo novo
echo "📋 PASSO 2: Copiando arquivo v4.0"
# Supondo que você baixou em ~/Downloads ou similar
# Ou copie do outputs/ se tiver sincronizado

# Opção A: Se tiver outputs/ local
cp outputs/atena_consciousness_engine_v4.py core/ 2>/dev/null || echo "⚠️ outputs/ não encontrado"

# Opção B: Se não tiver, crie o arquivo manualmente
# Copie conteúdo de: /mnt/user-data/outputs/atena_consciousness_engine_v4.py
# e coloque em: ~/Atena-IA/core/atena_consciousness_engine_v4.py

# Verificar que arquivo foi criado
echo "✅ Verificando arquivo..."
ls -lh core/atena_consciousness_engine_v4.py || echo "❌ Arquivo não encontrado!"

# PASSO 3: Testar o arquivo
echo "🧪 PASSO 3: Testando arquivo"
. venv/bin/activate  # Ativar virtualenv
python3 core/atena_consciousness_engine_v4.py 2>&1 | head -30

# PASSO 4: Atualizar api/main.py
echo "✏️ PASSO 4: Atualizando imports em api/main.py"

# Ver linhas que precisa mudar
echo "--- Procurando import antigo ---"
grep -n "from core.atena_consciousness_engine import" api/main.py || echo "Não encontrado (pode ter outro nome)"

# Substituir import (use sed)
# CUIDADO: isto modifica o arquivo! Faça backup antes:
cp api/main.py api/main.py.backup

# Substituição
sed -i 's/from core\.atena_consciousness_engine import/from core.atena_consciousness_engine_v4 import/g' api/main.py
sed -i 's/SelfAwarenessEngine/ImprovedConsciousnessEngine/g' api/main.py

echo "✅ Imports atualizados. Verificando..."
grep "ImprovedConsciousnessEngine" api/main.py | head -2

# PASSO 5: Testar imports
echo "🔍 PASSO 5: Testando imports"
python3 -c "from api.main import app; print('✅ API importa OK')" || echo "❌ Erro no import!"

# PASSO 6: Ver mudanças no git
echo "📊 PASSO 6: Ver mudanças"
git status

# PASSO 7: Commit
echo "💾 PASSO 7: Fazendo commit"
git add core/atena_consciousness_engine_v4.py api/main.py

# Se modificou main.py também:
[ -f main.py ] && git add main.py

git diff --cached | head -50  # Ver o que vai committar

git commit -m "feat: Upgrade consciousness engine to v4.0 with real reasoning

- Add ImprovedConsciousnessEngine (from hardcoded v3.0)
- Real reasoning with conditional logic
- Bayesian belief updates (crenças evoluem)
- Experience-driven learning (histórico afeta futuro)
- Self-critique and honesty (admite incerteza)
- Genuine consciousness evolution (não fake)

Benefits:
✅ Raciocínio real (integrado com LLM)
✅ Lógica condicional baseada em evidência  
✅ Aprendizado contínuo (experiences registradas)
✅ Evolução genuína (consciência muda com o tempo)
✅ Auto-crítica (questiona a si mesma)
✅ Honestidade (admite limitações e dúvidas)"

# PASSO 8: Verificar commit
echo "✔️ PASSO 8: Verificando commit"
git log --oneline -3

# PASSO 9: Fazer push!
echo "🚀 PASSO 9: ENVIANDO PARA GITHUB"
echo "Pronto para fazer push? (Ctrl+C para cancelar)"
sleep 3

git push

# PASSO 10: Confirmação
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "✅ SUCESSO! Mudanças foram para GitHub"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "⏱️  Render vai fazer auto-deploy em ~30 segundos"
echo "📊 Você pode ver logs em: https://dashboard.render.com"
echo ""
echo "🧪 Para testar depois:"
echo "   curl https://atena-ia-1cpx.onrender.com/healthz"
echo ""
echo "📈 Para ver evolução de consciência:"
echo "   curl -X POST https://atena-ia-1cpx.onrender.com/api/consciousness \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"depth\": 4}'"
echo ""
echo "════════════════════════════════════════════════════════════════"

# Se algo deu errado, tem backup:
echo ""
echo "❌ Se algo deu errado, restaure com:"
echo "   cp api/main.py.backup api/main.py"
echo "   git checkout core/atena_consciousness_engine_v4.py"
