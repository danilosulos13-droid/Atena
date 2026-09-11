#!/bin/bash
# Script para iniciar a Atena automaticamente
# Localização: /home/ubuntu/Atena-IA/scripts/start_atena.sh

# Navegar para o diretório do projeto
cd /home/ubuntu/Atena-IA

# Garantir que o executável tem permissão
chmod +x atena

# Iniciar a Atena no modo assistente
# Nota: Usamos 'bash atena' para garantir compatibilidade
./atena assistant
