import argparse
import logging
import os
from pathlib import Path

# Configuração do Logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] ATENA Setup — %(message)s")
logger = logging.getLogger("ModelDownloader")

ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = os.getenv("ATENA_MODEL_NAME", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B")
SAVE_PATH = Path(os.getenv("ATENA_MODEL_DIR", str(ROOT / "models" / "deepseek-r1-1.5b")))

def download_model() -> None:
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch
    except ImportError as exc:
        raise SystemExit(
            "Dependências do modelo ausentes. Instale setup/requirements-ultimate.txt "
            f"antes do download ({exc})."
        ) from exc

    logger.info(f"🚀 Iniciando download do modelo: {MODEL_NAME}")
    logger.info(f"📂 Destino: {SAVE_PATH}")
    
    try:
        # Baixar Tokenizer
        logger.info("📥 Baixando Tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
        SAVE_PATH.mkdir(parents=True, exist_ok=True)
        tokenizer.save_pretrained(str(SAVE_PATH))
        logger.info("✅ Tokenizer salvo com sucesso.")
        
        # Baixar Modelo (usando float16 para economizar espaço e memória)
        logger.info("📥 Baixando Modelo (isso pode levar alguns minutos)...")
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
            torch_dtype=torch.float16,
            device_map="cpu", # Forçamos CPU para o download inicial
            low_cpu_mem_usage=True
        )
        model.save_pretrained(str(SAVE_PATH))
        logger.info("✅ Modelo salvo com sucesso.")
        
        logger.info(f"✨ Download concluído! O modelo está pronto em: {SAVE_PATH}")
        
    except Exception as e:
        logger.error(f"❌ Erro durante o download: {e}")
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baixa o modelo local da ATENA.")
    parser.add_argument("--check", action="store_true", help="Só verifica se o diretório do modelo existe.")
    args = parser.parse_args()
    if args.check:
        print(f"{'ok' if SAVE_PATH.exists() else 'missing'}: {SAVE_PATH}")
    else:
        download_model()
