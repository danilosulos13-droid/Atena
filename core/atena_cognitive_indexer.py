# -*- coding: utf-8 -*-
"""
ATENA Ω — MÓDULO DE INDEXAÇÃO DE ATIVOS COGNITIVOS (MELHORIA M13)
Este módulo permite que a ATENA Ω realize a ingestão de capacidades do ambiente local.
- Varredura de bibliotecas Python instaladas
- Mapeamento de 'Skills' disponíveis no sistema
- Integração de ferramentas de sistema (CLI)
- Validação de ativos para expansão de inteligência
"""

import os
import sys
import subprocess
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

# Configuração de caminhos
ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = Path("/home/ubuntu/skills")
LOG_DIR = ROOT / "atena_evolution" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [🧠 ATENA-COGNITIVE] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("AtenaCognitive")

class CognitiveIndexer:
    def __init__(self):
        self.assets = {
            "libraries": [],
            "skills": [],
            "system_tools": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def scan_libraries(self):
        """Varredura de bibliotecas Python instaladas."""
        logger.info("Escaneando bibliotecas instaladas...")
        try:
            result = subprocess.run([sys.executable, "-m", "pip", "list", "--format=json"], 
                                    capture_output=True, text=True)
            if result.returncode == 0:
                self.assets["libraries"] = json.loads(result.stdout)
                logger.info(f"✅ {len(self.assets['libraries'])} bibliotecas indexadas.")
        except Exception as e:
            logger.error(f"Erro ao escanear bibliotecas: {e}")

    def scan_skills(self):
        """Mapeamento de skills disponíveis no ambiente Manus."""
        logger.info("Mapeando skills do sistema...")
        if SKILLS_DIR.exists():
            skills = [d.name for d in SKILLS_DIR.iterdir() if d.is_dir()]
            self.assets["skills"] = skills
            logger.info(f"✅ {len(skills)} skills detectadas.")
        else:
            logger.warning("Diretório de skills não encontrado.")

    def scan_system_tools(self):
        """Verifica ferramentas de sistema essenciais."""
        tools = ["git", "gh", "curl", "wget", "ffmpeg", "playwright", "manus-md-to-pdf"]
        logger.info("Verificando ferramentas de sistema...")
        for tool in tools:
            path = subprocess.run(["which", tool], capture_output=True, text=True).stdout.strip()
            if path:
                self.assets["system_tools"].append({"name": tool, "path": path})
        logger.info(f"✅ {len(self.assets['system_tools'])} ferramentas de sistema validadas.")

    def generate_intelligence_uplift_report(self):
        """Gera um relatório sobre como esses ativos melhoram a inteligência da Atena."""
        report_path = ROOT / "docs" / "INTELLIGENCE_UPLIFT_REPORT.md"
        
        # Análise de impacto
        impact_analysis = []
        if any(lib['name'] == 'scikit-learn' for lib in self.assets['libraries']):
            impact_analysis.append("- **Capacidade Analítica:** Presença de `scikit-learn` e `scipy` permite modelagem preditiva avançada.")
        if "imagegen" in self.assets["skills"]:
            impact_analysis.append("- **Criatividade Visual:** Skill `imagegen` disponível para geração de ativos multimodais.")
        if any(tool['name'] == 'playwright' for tool in self.assets["system_tools"]):
            impact_analysis.append("- **Autonomia Web:** `playwright` validado para navegação complexa e extração de dados.")

        report_md = f"""# Relatório de Uplift de Inteligência: ATENA Ω
**Data da Varredura:** {self.assets['timestamp']}

## 1. Ativos Cognitivos Ingeridos
Foram detectados e validados os seguintes ativos no ambiente local:
- **Bibliotecas Python:** {len(self.assets['libraries'])}
- **Skills Manus:** {len(self.assets['skills'])}
- **Ferramentas CLI:** {len(self.assets['system_tools'])}

## 2. Análise de Impacto na Inteligência
{chr(10).join(impact_analysis)}

## 3. Conclusão da Ingestão
A ATENA Ω agora possui um índice completo de ferramentas disponíveis, permitindo que o roteador de missões escolha o melhor ativo para cada tarefa complexa.

---
*Índice gerado automaticamente pelo Módulo M13.*
"""
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_md, encoding="utf-8")
        logger.info(f"✅ Relatório de Uplift gerado em: {report_path}")

    def run(self):
        self.scan_libraries()
        self.scan_skills()
        self.scan_system_tools()
        self.generate_intelligence_uplift_report()
        
        # Salva o índice para uso futuro pelo núcleo
        index_path = ROOT / "atena_evolution" / "cognitive_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(self.assets, f, indent=2)
        logger.info(f"✅ Índice cognitivo salvo em: {index_path}")

if __name__ == "__main__":
    indexer = CognitiveIndexer()
    indexer.run()
