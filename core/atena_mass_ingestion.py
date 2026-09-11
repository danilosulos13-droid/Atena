#!/usr/bin/env python3
"""
ATENA Ω - MÓDULO M38: Motor de Ingestão Massiva de Dados Reais
Utiliza a API de Eventos Públicos do GitHub para ingestão real e síntese de tendências.
"""

import sys
import os
import time
import json
import requests
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class GitHubIngestionEngine:
    def __init__(self):
        self.url = "https://api.github.com/events"
        self.total_bytes = 0
        self.event_count = 0
        self.knowledge_base = []

    def ingest(self, pages=5):
        print(f"[M38] Iniciando ingestão massiva via GitHub Events API...")
        start_time = time.time()
        
        for p in range(1, pages + 1):
            try:
                # GitHub permite até 100 eventos por página, 300 eventos totais na API pública
                response = requests.get(f"{self.url}?page={p}&per_page=100", timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    self.total_bytes += len(response.content)
                    self.event_count += len(data)
                    
                    for event in data:
                        repo_name = event.get('repo', {}).get('name')
                        event_type = event.get('type')
                        if repo_name and event_type:
                            self.knowledge_base.append({
                                "repo": repo_name,
                                "type": event_type,
                                "created_at": event.get('created_at')
                            })
                time.sleep(0.5) # Respeitar rate limit
            except Exception as e:
                print(f"[!] Erro na página {p}: {e}")

        duration = time.time() - start_time
        throughput_kb_s = (self.total_bytes / 1024.0) / duration
        
        # Sintetizar Conhecimento: Top Repos e Tipos de Eventos
        repos = [k['repo'] for k in self.knowledge_base]
        event_types = [k['type'] for k in self.knowledge_base]
        
        report = {
            "protocol": "Mass Ingestion M38",
            "timestamp": datetime.now().isoformat(),
            "source": "GitHub Events API",
            "duration_seconds": round(duration, 2),
            "total_events_processed": self.event_count,
            "total_data_absorbed_kb": round(self.total_bytes / 1024.0, 2),
            "real_throughput_kb_s": round(throughput_kb_s, 2),
            "unique_repos_extracted": len(set(repos)),
            "top_event_types": list(set(event_types))[:10],
            "status": "INGESTION_COMPLETE"
        }

        output_path = "/home/ubuntu/Atena-IA/docs/MASS_INGESTION_REPORT.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
        
        print(f"\n[OK] Ingestão concluída. Throughput: {round(throughput_kb_s, 2)} KB/s.")
        print(f"[OK] Conhecimento extraído de {len(set(repos))} repositórios reais.")
        return report

if __name__ == "__main__":
    engine = GitHubIngestionEngine()
    engine.ingest(pages=3)
