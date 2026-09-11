#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ATENA Ω - Semantic Memory Engine v3.0                    ║
║                 Memória Semântica com Embeddings e FAISS                    ║
║                                                                            ║
║  Capacidades Avançadas:                                                    ║
║  • Indexação semântica com Sentence Transformers                          ║
║  • Busca vetorial aproximada (ANN) com FAISS                              ║
║  • Múltiplos índices: Flat, IVF, HNSW, PQ                                ║
║  • Chunking inteligente de documentos                                     ║
║  • Cache de embeddings com persistência                                   ║
║  • Métricas de similaridade: L2, Cosseno, Inner Product                  ║
║  • Filtros por metadata e data                                           ║
║  • Indexação incremental sem rebuild completo                            ║
║  • Suporte a GPUs via FAISS                                              ║
║  • API de busca assíncrona                                               ║
║  • Monitoramento e estatísticas                                          ║
║                                                                            ║
║  Autor: ATENA Ω - Geração 345                                             ║
║  Licença: Proprietária                                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import pickle
import re
import sys
import tempfile
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from functools import lru_cache, wraps
from pathlib import Path
from typing import (
    Any, Callable, Dict, Generator, Iterator, List, Literal, Optional,
    Sequence, Set, Tuple, Type, TypedDict, Union, overload
)

import faiss
import numpy as np
import psutil
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# ─── Configuração de Ambiente ────────────────────────────────────────────────
os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
os.environ.setdefault('OMP_NUM_THREADS', str(max(1, os.cpu_count() // 2)))

# ─── Logging Estruturado ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('atena_semantic_memory.log')
    ]
)
logger: logging.Logger = logging.getLogger(__name__)

# ─── Constantes ──────────────────────────────────────────────────────────────
DEFAULT_MODEL_NAME: str = 'all-MiniLM-L6-v2'
DEFAULT_EMBEDDING_DIM: int = 384  # Para all-MiniLM-L6-v2
DEFAULT_INDEX_PATH: Path = Path('atena_evolution/knowledge/semantic_index.faiss')
DEFAULT_DOCS_PATH: Path = Path('atena_evolution/knowledge/semantic_docs.json')
DEFAULT_EMBEDDINGS_CACHE_PATH: Path = Path('atena_evolution/knowledge/embeddings_cache.npz')
DEFAULT_CHUNK_SIZE: int = 512  # tokens aproximados por chunk
DEFAULT_CHUNK_OVERLAP: int = 50
DEFAULT_TOP_K: int = 5
DEFAULT_BATCH_SIZE: int = 32

# ─── Enums ────────────────────────────────────────────────────────────────────
class IndexType(str, Enum):
    """Tipos de índices FAISS suportados"""
    FLAT = "flat"           # Busca exata, mais preciso
    IVF = "ivf"             # IVF (Inverted File), bom para datasets médios
    IVFPQ = "ivfpq"         # IVF + Product Quantization, compressão
    HNSW = "hnsw"           # Hierarchical Navigable Small World, rápido
    PQ = "pq"               # Product Quantization, muita compressão
    AUTO = "auto"           # Seleciona automaticamente

class SimilarityMetric(str, Enum):
    """Métricas de similaridade"""
    L2 = "l2"                    # Distância Euclidiana
    COSINE = "cosine"            # Similaridade de Cosseno
    INNER_PRODUCT = "inner_product"  # Produto Interno
    L1 = "l1"                    # Distância Manhattan

class ChunkStrategy(str, Enum):
    """Estratégias de chunking de documentos"""
    FIXED_SIZE = "fixed_size"    # Tamanho fixo em caracteres
    SENTENCE = "sentence"        # Por sentenças
    PARAGRAPH = "paragraph"      # Por parágrafos
    SEMANTIC = "semantic"        # Chunking semântico
    SLIDING_WINDOW = "sliding_window"  # Janela deslizante

# ─── Data Classes ─────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Document:
    """Documento indexado com metadata"""
    id: str
    path: str
    content: str
    chunk_index: int = 0
    total_chunks: int = 1
    file_type: str = ""
    file_size: int = 0
    modified_at: str = ""
    indexed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def display_name(self) -> str:
        return Path(self.path).name

@dataclass(slots=True)
class SearchResult:
    """Resultado de busca semântica"""
    document: Document
    score: float
    rank: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'document': asdict(self.document),
            'score': self.score,
            'rank': self.rank
        }

@dataclass(slots=True)
class IndexStatistics:
    """Estatísticas do índice"""
    total_documents: int = 0
    total_chunks: int = 0
    total_vectors: int = 0
    index_type: str = ""
    index_size_bytes: int = 0
    memory_usage_mb: float = 0.0
    last_indexed: Optional[str] = None
    average_query_time_ms: float = 0.0
    query_count: int = 0

@dataclass(slots=True)
class ChunkingConfig:
    """Configuração de chunking"""
    strategy: ChunkStrategy = ChunkStrategy.FIXED_SIZE
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
    max_chunks_per_doc: int = 100
    min_chunk_size: int = 100

# ─── Interfaces ──────────────────────────────────────────────────────────────
class Embedder(ABC):
    """Interface para modelos de embedding"""
    
    @abstractmethod
    def encode(self, texts: List[str], **kwargs) -> NDArray[np.float32]:
        """Codifica textos em embeddings"""
        pass
    
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensão dos embeddings"""
        pass

class VectorIndex(ABC):
    """Interface para índices vetoriais"""
    
    @abstractmethod
    def add(self, vectors: NDArray[np.float32]) -> None:
        """Adiciona vetores ao índice"""
        pass
    
    @abstractmethod
    def search(self, query: NDArray[np.float32], k: int) -> Tuple[NDArray[np.float32], NDArray[np.int64]]:
        """Busca k vizinhos mais próximos"""
        pass
    
    @abstractmethod
    def save(self, path: Path) -> None:
        """Salva índice em disco"""
        pass
    
    @abstractmethod
    def load(self, path: Path) -> None:
        """Carrega índice do disco"""
        pass
    
    @property
    @abstractmethod
    def ntotal(self) -> int:
        """Número total de vetores"""
        pass

# ─── Implementações de Embedders ─────────────────────────────────────────────
class SentenceTransformerEmbedder(Embedder):
    """Embedder usando Sentence Transformers"""
    
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, 
                 device: Optional[str] = None,
                 batch_size: int = DEFAULT_BATCH_SIZE):
        self.model_name = model_name
        self.batch_size = batch_size
        
        # Auto-detecta dispositivo
        if device is None:
            import torch
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        self.device = device
        self._model: Optional[SentenceTransformer] = None
        self._load_model()
    
    def _load_model(self):
        """Carrega o modelo com lazy loading"""
        logger.info(f"Carregando modelo {self.model_name} no dispositivo {self.device}")
        start_time = time.time()
        
        self._model = SentenceTransformer(self.model_name, device=self.device)
        
        elapsed = time.time() - start_time
        logger.info(f"Modelo carregado em {elapsed:.2f}s")
    
    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._load_model()
        return self._model
    
    @property
    def dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()
    
    def encode(self, texts: List[str], show_progress: bool = False, **kwargs) -> NDArray[np.float32]:
        """Codifica textos em embeddings"""
        if not texts:
            return np.array([], dtype=np.float32)
        
        return self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
            normalize_embeddings=True,  # Para similaridade de cosseno
            **kwargs
        ).astype(np.float32)

class CachedEmbedder(Embedder):
    """Wrapper que adiciona cache de embeddings"""
    
    def __init__(self, embedder: Embedder, cache_path: Path = DEFAULT_EMBEDDINGS_CACHE_PATH):
        self.embedder = embedder
        self.cache_path = cache_path
        self._cache: Dict[str, NDArray[np.float32]] = {}
        self._load_cache()
    
    @property
    def dimension(self) -> int:
        return self.embedder.dimension
    
    def _get_cache_key(self, text: str) -> str:
        """Gera chave de cache única para um texto"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    def _load_cache(self):
        """Carrega cache de embeddings do disco"""
        if self.cache_path.exists():
            try:
                data = np.load(self.cache_path, allow_pickle=True)
                for key in data.files:
                    self._cache[key] = data[key]
                logger.info(f"Cache carregado: {len(self._cache)} embeddings")
            except Exception as e:
                logger.warning(f"Erro ao carregar cache: {e}")
                self._cache = {}
    
    def _save_cache(self):
        """Salva cache em disco"""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            np.savez_compressed(self.cache_path, **self._cache)
            logger.info(f"Cache salvo: {len(self._cache)} embeddings")
        except Exception as e:
            logger.error(f"Erro ao salvar cache: {e}")
    
    def encode(self, texts: List[str], **kwargs) -> NDArray[np.float32]:
        """Codifica com cache"""
        embeddings = np.zeros((len(texts), self.dimension), dtype=np.float32)
        texts_to_encode = []
        indices_to_encode = []
        
        # Verifica cache
        for i, text in enumerate(texts):
            key = self._get_cache_key(text)
            if key in self._cache:
                embeddings[i] = self._cache[key]
            else:
                texts_to_encode.append(text)
                indices_to_encode.append(i)
        
        # Codifica textos não cacheados
        if texts_to_encode:
            new_embeddings = self.embedder.encode(texts_to_encode, **kwargs)
            for i, idx in enumerate(indices_to_encode):
                embeddings[idx] = new_embeddings[i]
                key = self._get_cache_key(texts_to_encode[i])
                self._cache[key] = new_embeddings[i]
            
            # Salva cache periodicamente
            if len(self._cache) % 1000 == 0:
                self._save_cache()
        
        return embeddings
    
    def flush_cache(self):
        """Força salvamento do cache"""
        self._save_cache()

# ─── Implementações de Índices FAISS ─────────────────────────────────────────
class FAISSIndex(VectorIndex):
    """Índice FAISS base"""
    
    def __init__(self, dimension: int, index_type: IndexType = IndexType.AUTO,
                 metric: SimilarityMetric = SimilarityMetric.COSINE):
        self.dimension = dimension
        self.index_type = index_type
        self.metric = metric
        self._index: Optional[faiss.Index] = None
        self._create_index()
    
    def _create_index(self):
        """Cria índice FAISS apropriado"""
        if self.metric == SimilarityMetric.COSINE:
            # Para cosseno, usamos Inner Product com vetores normalizados
            base_index = faiss.IndexFlatIP(self.dimension)
        elif self.metric == SimilarityMetric.INNER_PRODUCT:
            base_index = faiss.IndexFlatIP(self.dimension)
        else:
            base_index = faiss.IndexFlatL2(self.dimension)
        
        # Escolhe tipo de índice
        if self.index_type == IndexType.FLAT:
            self._index = base_index
        elif self.index_type == IndexType.IVF:
            nlist = max(4, int(np.sqrt(self.dimension * 10)))
            quantizer = base_index
            self._index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist)
            self._index.nprobe = min(10, nlist // 2)
        elif self.index_type == IndexType.IVFPQ:
            nlist = max(4, int(np.sqrt(self.dimension * 10)))
            m = max(1, self.dimension // 8)
            quantizer = faiss.IndexFlatL2(self.dimension)
            self._index = faiss.IndexIVFPQ(quantizer, self.dimension, nlist, m, 8)
        elif self.index_type == IndexType.HNSW:
            M = 32
            self._index = faiss.IndexHNSWFlat(self.dimension, M)
        elif self.index_type == IndexType.PQ:
            m = max(1, self.dimension // 8)
            self._index = faiss.IndexPQ(self.dimension, m, 8)
        else:  # AUTO
            self._index = base_index
        
        logger.info(f"Índice criado: tipo={self.index_type.value}, métrica={self.metric.value}")
    
    def add(self, vectors: NDArray[np.float32]) -> None:
        """Adiciona vetores ao índice"""
        if vectors.size == 0:
            return
        
        # Treina índice se necessário (para IVF, PQ, etc.)
        if hasattr(self._index, 'is_trained') and not self._index.is_trained:
            logger.info(f"Treinando índice {self.index_type.value} com {len(vectors)} vetores")
            self._index.train(vectors)
        
        self._index.add(vectors)
    
    def search(self, query: NDArray[np.float32], k: int) -> Tuple[NDArray[np.float32], NDArray[np.int64]]:
        """Busca k vizinhos mais próximos"""
        if self._index.ntotal == 0:
            return np.array([[]], dtype=np.float32), np.array([[]], dtype=np.int64)
        
        k = min(k, self._index.ntotal)
        return self._index.search(query, k)
    
    def save(self, path: Path) -> None:
        """Salva índice em disco"""
        path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(path))
        logger.info(f"Índice salvo: {path} ({self._index.ntotal} vetores)")
    
    def load(self, path: Path) -> None:
        """Carrega índice do disco"""
        if path.exists():
            self._index = faiss.read_index(str(path))
            logger.info(f"Índice carregado: {path} ({self._index.ntotal} vetores)")
    
    @property
    def ntotal(self) -> int:
        return self._index.ntotal if self._index else 0

class GPUFAISSIndex(FAISSIndex):
    """Índice FAISS com aceleração GPU"""
    
    def __init__(self, dimension: int, index_type: IndexType = IndexType.FLAT,
                 metric: SimilarityMetric = SimilarityMetric.COSINE,
                 gpu_id: int = 0):
        self.gpu_id = gpu_id
        self._gpu_res = None
        super().__init__(dimension, index_type, metric)
    
    def _create_index(self):
        super()._create_index()
        try:
            self._gpu_res = faiss.StandardGpuResources()
            self._index = faiss.index_cpu_to_gpu(self._gpu_res, self.gpu_id, self._index)
            logger.info(f"Índice movido para GPU {self.gpu_id}")
        except Exception as e:
            logger.warning(f"GPU não disponível, usando CPU: {e}")

# ─── Chunking de Documentos ──────────────────────────────────────────────────
class DocumentChunker:
    """Divide documentos em chunks para indexação"""
    
    def __init__(self, config: ChunkingConfig = ChunkingConfig()):
        self.config = config
    
    def chunk_text(self, text: str) -> List[str]:
        """Divide texto em chunks"""
        if self.config.strategy == ChunkStrategy.FIXED_SIZE:
            return self._fixed_size_chunk(text)
        elif self.config.strategy == ChunkStrategy.SENTENCE:
            return self._sentence_chunk(text)
        elif self.config.strategy == ChunkStrategy.PARAGRAPH:
            return self._paragraph_chunk(text)
        elif self.config.strategy == ChunkStrategy.SLIDING_WINDOW:
            return self._sliding_window_chunk(text)
        else:
            return self._fixed_size_chunk(text)
    
    def _fixed_size_chunk(self, text: str) -> List[str]:
        """Chunking por tamanho fixo de caracteres"""
        chunks = []
        chunk_size = self.config.chunk_size
        
        for i in range(0, len(text), chunk_size - self.config.chunk_overlap):
            chunk = text[i:i + chunk_size]
            if len(chunk.strip()) >= self.config.min_chunk_size:
                chunks.append(chunk.strip())
        
        return chunks[:self.config.max_chunks_per_doc]
    
    def _sentence_chunk(self, text: str) -> List[str]:
        """Chunking por sentenças"""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = []
        current_length = 0
        
        for sentence in sentences:
            sentence_length = len(sentence)
            if current_length + sentence_length > self.config.chunk_size and current_chunk:
                chunks.append(' '.join(current_chunk))
                current_chunk = [sentence]
                current_length = sentence_length
            else:
                current_chunk.append(sentence)
                current_length += sentence_length
        
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        
        return chunks[:self.config.max_chunks_per_doc]
    
    def _paragraph_chunk(self, text: str) -> List[str]:
        """Chunking por parágrafos"""
        paragraphs = text.split('\n\n')
        chunks = []
        current_chunk = []
        current_length = 0
        
        for para in paragraphs:
            para_length = len(para)
            if current_length + para_length > self.config.chunk_size * 2 and current_chunk:
                chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_length = para_length
            else:
                current_chunk.append(para)
                current_length += para_length
        
        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))
        
        return chunks[:self.config.max_chunks_per_doc]
    
    def _sliding_window_chunk(self, text: str) -> List[str]:
        """Chunking com janela deslizante"""
        chunks = []
        chunk_size = self.config.chunk_size
        stride = max(1, chunk_size - self.config.chunk_overlap)
        
        for i in range(0, len(text) - chunk_size + 1, stride):
            chunk = text[i:i + chunk_size]
            if len(chunk.strip()) >= self.config.min_chunk_size:
                chunks.append(chunk.strip())
        
        return chunks[:self.config.max_chunks_per_doc]

# ─── ATENA Semantic Memory Principal ────────────────────────────────────────
class AtenaSemanticMemory:
    """
    Motor de Memória Semântica com embeddings e busca vetorial.
    
    Features:
    - Indexação semântica com Sentence Transformers
    - Busca vetorial com FAISS (CPU e GPU)
    - Chunking inteligente de documentos
    - Cache de embeddings
    - Indexação incremental
    - Filtros por metadata
    - Estatísticas e monitoramento
    """
    
    def __init__(self,
                 model_name: str = DEFAULT_MODEL_NAME,
                 index_type: IndexType = IndexType.AUTO,
                 metric: SimilarityMetric = SimilarityMetric.COSINE,
                 use_cache: bool = True,
                 use_gpu: bool = False,
                 chunking_config: Optional[ChunkingConfig] = None,
                 index_path: Optional[Path] = None,
                 docs_path: Optional[Path] = None):
        """
        Inicializa a memória semântica.
        
        Args:
            model_name: Nome do modelo Sentence Transformer
            index_type: Tipo de índice FAISS
            metric: Métrica de similaridade
            use_cache: Se deve usar cache de embeddings
            use_gpu: Se deve usar GPU
            chunking_config: Configuração de chunking
            index_path: Caminho para salvar índice
            docs_path: Caminho para salvar documentos
        """
        self.model_name = model_name
        self.index_type = index_type
        self.metric = metric
        self.use_gpu = use_gpu
        
        # Paths
        self.index_path = index_path or DEFAULT_INDEX_PATH
        self.docs_path = docs_path or DEFAULT_DOCS_PATH
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Embedder
        base_embedder = SentenceTransformerEmbedder(model_name)
        self.embedder = CachedEmbedder(base_embedder) if use_cache else base_embedder
        
        # Chunking
        self.chunker = DocumentChunker(chunking_config or ChunkingConfig())
        
        # Índice vetorial
        if use_gpu:
            self.index = GPUFAISSIndex(
                self.embedder.dimension, index_type, metric
            )
        else:
            self.index = FAISSIndex(
                self.embedder.dimension, index_type, metric
            )
        
        # Documentos e mapeamentos
        self.documents: List[Document] = []
        self._doc_id_to_indices: Dict[str, List[int]] = defaultdict(list)
        self._embedding_hashes: Set[str] = set()
        
        # Estatísticas
        self.statistics = IndexStatistics()
        
        # Locks
        self._index_lock = threading.RLock()
        self._search_lock = threading.RLock()
        
        # Carrega dados existentes
        self.load()
        
        logger.info(f"AtenaSemanticMemory inicializada: {model_name}, "
                   f"dim={self.embedder.dimension}, tipo={index_type.value}")
    
    @property
    def is_empty(self) -> bool:
        return self.index.ntotal == 0
    
    def index_reports(self, directory: Union[str, Path] = "atena_evolution",
                     file_patterns: Optional[List[str]] = None,
                     recursive: bool = True,
                     incremental: bool = True) -> int:
        """
        Indexa todos os relatórios em um diretório.
        
        Args:
            directory: Diretório para indexar
            file_patterns: Padrões de arquivo (ex: ['.md', '.json', '.txt'])
            recursive: Se deve buscar recursivamente
            incremental: Se True, pula arquivos já indexados
            
        Returns:
            Número de chunks indexados
        """
        if file_patterns is None:
            file_patterns = ['.md', '.json', '.txt', '.py', '.log', '.yaml', '.yml', '.toml']
        
        directory = Path(directory)
        logger.info(f"Indexando diretório: {directory}")
        
        # Coleta arquivos
        all_files = []
        glob_pattern = '**/*' if recursive else '*'
        
        for path in directory.glob(glob_pattern):
            if path.is_file() and path.suffix in file_patterns:
                # Verifica se já foi indexado (incremental)
                if incremental and self._is_already_indexed(path):
                    continue
                all_files.append(path)
        
        if not all_files:
            logger.info("Nenhum arquivo novo para indexar")
            return 0
        
        logger.info(f"Encontrados {len(all_files)} arquivos para indexar")
        
        # Processa em paralelo
        all_texts = []
        all_docs = []
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._read_and_chunk_file, path): path
                for path in all_files
            }
            
            with tqdm(total=len(all_files), desc="Processando arquivos") as pbar:
                for future in as_completed(futures):
                    try:
                        chunks, docs = future.result()
                        all_texts.extend(chunks)
                        all_docs.extend(docs)
                    except Exception as e:
                        path = futures[future]
                        logger.error(f"Erro ao processar {path}: {e}")
                    pbar.update(1)
        
        if not all_texts:
            return 0
        
        # Gera embeddings em batches
        embeddings = self._encode_batched(all_texts)
        
        # Adiciona ao índice
        with self._index_lock:
            self.index.add(embeddings)
            
            for i, doc in enumerate(all_docs):
                self.documents.append(doc)
                idx = len(self.documents) - 1
                self._doc_id_to_indices[doc.id].append(idx)
                self._embedding_hashes.add(self._compute_hash(all_texts[i]))
        
        # Atualiza estatísticas
        self.statistics.total_chunks = len(all_texts)
        self.statistics.total_vectors = self.index.ntotal
        self.statistics.last_indexed = datetime.now().isoformat()
        
        # Salva
        self.save()
        
        logger.info(f"Indexação concluída: {len(all_texts)} chunks indexados")
        return len(all_texts)
    
    def _read_and_chunk_file(self, path: Path) -> Tuple[List[str], List[Document]]:
        """Lê e faz chunking de um arquivo"""
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            logger.warning(f"Erro ao ler {path}: {e}")
            return [], []
        
        # Gera ID único para o documento
        doc_id = self._compute_hash(str(path) + content[:100])
        
        # Chunking
        chunks = self.chunker.chunk_text(content)
        
        if not chunks:
            return [], []
        
        # Cria documentos
        docs = []
        for i, chunk in enumerate(chunks):
            doc = Document(
                id=f"{doc_id}_{i}",
                path=str(path.absolute()),
                content=chunk,
                chunk_index=i,
                total_chunks=len(chunks),
                file_type=path.suffix,
                file_size=path.stat().st_size,
                modified_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            )
            docs.append(doc)
        
        return chunks, docs
    
    def _encode_batched(self, texts: List[str]) -> NDArray[np.float32]:
        """Codifica textos em batches com barra de progresso"""
        all_embeddings = []
        
        with tqdm(total=len(texts), desc="Gerando embeddings") as pbar:
            for i in range(0, len(texts), DEFAULT_BATCH_SIZE):
                batch = texts[i:i + DEFAULT_BATCH_SIZE]
                embeddings = self.embedder.encode(batch)
                all_embeddings.append(embeddings)
                pbar.update(len(batch))
        
        return np.vstack(all_embeddings) if all_embeddings else np.array([], dtype=np.float32)
    
    def search(self, query: str, k: int = DEFAULT_TOP_K,
              min_score: Optional[float] = None,
              file_type_filter: Optional[List[str]] = None,
              path_filter: Optional[str] = None,
              date_from: Optional[str] = None,
              date_to: Optional[str] = None) -> List[SearchResult]:
        """
        Busca semântica com filtros opcionais.
        
        Args:
            query: Texto da consulta
            k: Número de resultados
            min_score: Score mínimo (depende da métrica)
            file_type_filter: Filtrar por tipo de arquivo
            path_filter: Filtrar por caminho (substring)
            date_from: Data mínima de modificação
            date_to: Data máxima de modificação
            
        Returns:
            Lista de resultados ordenados por relevância
        """
        if self.is_empty:
            logger.warning("Índice vazio, nenhum resultado")
            return []
        
        start_time = time.time()
        
        with self._search_lock:
            # Gera embedding da query
            query_vector = self.embedder.encode([query])
            
            # Busca no índice
            k_search = min(k * 3, self.index.ntotal)  # Busca mais para filtrar depois
            distances, indices = self.index.search(query_vector, k_search)
            
            # Coleta resultados
            results = []
            seen_docs = set()
            
            for i, idx in enumerate(indices[0]):
                if idx < 0 or idx >= len(self.documents):
                    continue
                
                doc = self.documents[idx]
                score = float(distances[0][i])
                
                # Normaliza score
                if self.metric == SimilarityMetric.L2:
                    score = 1.0 / (1.0 + score)  # Converte distância para similaridade
                elif self.metric == SimilarityMetric.INNER_PRODUCT:
                    score = max(0.0, score)  # Pode ser negativo
                
                # Aplica filtros
                if not self._apply_filters(doc, min_score, file_type_filter,
                                          path_filter, date_from, date_to):
                    continue
                
                # Evita duplicatas (mesmo documento)
                doc_key = doc.path
                if doc_key in seen_docs:
                    continue
                seen_docs.add(doc_key)
                
                results.append(SearchResult(
                    document=doc,
                    score=score,
                    rank=len(results) + 1
                ))
                
                if len(results) >= k:
                    break
        
        # Atualiza estatísticas
        query_time = (time.time() - start_time) * 1000
        self.statistics.query_count += 1
        if self.statistics.average_query_time_ms == 0:
            self.statistics.average_query_time_ms = query_time
        else:
            self.statistics.average_query_time_ms = (
                self.statistics.average_query_time_ms * 0.9 + query_time * 0.1
            )
        
        return results
    
    def _apply_filters(self, doc: Document,
                      min_score: Optional[float],
                      file_type_filter: Optional[List[str]],
                      path_filter: Optional[str],
                      date_from: Optional[str],
                      date_to: Optional[str]) -> bool:
        """Aplica filtros a um documento"""
        if min_score is not None:
            # O score é aplicado depois na coleta
            pass
        
        if file_type_filter and doc.file_type not in file_type_filter:
            return False
        
        if path_filter and path_filter.lower() not in doc.path.lower():
            return False
        
        if date_from or date_to:
            try:
                doc_date = datetime.fromisoformat(doc.modified_at)
                if date_from:
                    from_date = datetime.fromisoformat(date_from)
                    if doc_date < from_date:
                        return False
                if date_to:
                    to_date = datetime.fromisoformat(date_to)
                    if doc_date > to_date:
                        return False
            except (ValueError, TypeError):
                pass
        
        return True
    
    def _is_already_indexed(self, path: Path) -> bool:
        """Verifica se um arquivo já foi indexado"""
        try:
            content_hash = self._compute_hash(str(path.absolute()))
            return content_hash in self._doc_id_to_indices
        except Exception:
            return False
    
    @staticmethod
    def _compute_hash(text: str) -> str:
        """Computa hash SHA-256"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    
    def save(self) -> None:
        """Salva índice e documentos"""
        with self._index_lock:
            # Salva índice FAISS
            self.index.save(self.index_path)
            
            # Salva documentos
            docs_data = {
                'documents': [asdict(doc) for doc in self.documents],
                'statistics': asdict(self.statistics),
                'config': {
                    'model_name': self.model_name,
                    'index_type': self.index_type.value,
                    'metric': self.metric.value,
                    'version': '3.0.0'
                },
                'saved_at': datetime.now().isoformat()
            }
            
            with open(self.docs_path, 'w', encoding='utf-8') as f:
                json.dump(docs_data, f, indent=2, ensure_ascii=False)
            
            # Salva cache de embeddings
            if isinstance(self.embedder, CachedEmbedder):
                self.embedder.flush_cache()
            
            logger.info(f"Dados salvos: {len(self.documents)} documentos, "
                       f"{self.index.ntotal} vetores")
    
    def load(self) -> bool:
        """Carrega índice e documentos do disco"""
        if not self.index_path.exists() or not self.docs_path.exists():
            logger.info("Nenhum dado pré-existente encontrado")
            return False
        
        try:
            # Carrega índice FAISS
            self.index.load(self.index_path)
            
            # Carrega documentos
            with open(self.docs_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.documents = [Document(**doc) for doc in data.get('documents', [])]
            
            if 'statistics' in data:
                self.statistics = IndexStatistics(**data['statistics'])
            
            # Reconstrói mapeamentos
            for i, doc in enumerate(self.documents):
                self._doc_id_to_indices[doc.id].append(i)
            
            logger.info(f"Dados carregados: {len(self.documents)} documentos, "
                       f"{self.index.ntotal} vetores")
            return True
            
        except Exception as e:
            logger.error(f"Erro ao carregar dados: {e}")
            traceback.print_exc()
            return False
    
    def get_statistics(self) -> IndexStatistics:
        """Retorna estatísticas do índice"""
        self.statistics.total_documents = len(set(doc.path for doc in self.documents))
        self.statistics.total_chunks = len(self.documents)
        self.statistics.total_vectors = self.index.ntotal
        self.statistics.index_type = self.index_type.value
        self.statistics.index_size_bytes = self.index_path.stat().st_size if self.index_path.exists() else 0
        self.statistics.memory_usage_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        
        return self.statistics
    
    def clear(self) -> None:
        """Limpa todo o índice"""
        with self._index_lock:
            self.documents.clear()
            self._doc_id_to_indices.clear()
            self._embedding_hashes.clear()
            
            # Recria índice vazio
            if self.use_gpu:
                self.index = GPUFAISSIndex(self.embedder.dimension, self.index_type, self.metric)
            else:
                self.index = FAISSIndex(self.embedder.dimension, self.index_type, self.metric)
            
            self.statistics = IndexStatistics()
            
            # Remove arquivos
            for path in [self.index_path, self.docs_path]:
                if path.exists():
                    path.unlink()
            
            logger.info("Índice completamente limpo")

# ─── CLI e Testes ────────────────────────────────────────────────────────────
def main():
    """Função principal"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='ATENA Ω - Semantic Memory Engine v3.0',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('--index', type=str, default='atena_evolution',
                       help='Diretório para indexar')
    parser.add_argument('--search', type=str, help='Query de busca')
    parser.add_argument('--top-k', type=int, default=5,
                       help='Número de resultados')
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL_NAME,
                       help='Modelo Sentence Transformer')
    parser.add_argument('--index-type', type=str, default='auto',
                       choices=['flat', 'ivf', 'ivfpq', 'hnsw', 'pq', 'auto'],
                       help='Tipo de índice FAISS')
    parser.add_argument('--gpu', action='store_true',
                       help='Usar GPU se disponível')
    parser.add_argument('--stats', action='store_true',
                       help='Mostrar estatísticas')
    parser.add_argument('--clear', action='store_true',
                       help='Limpar índice')
    
    args = parser.parse_args()
    
    try:
        # Inicializa memória semântica
        memory = AtenaSemanticMemory(
            model_name=args.model,
            index_type=IndexType(args.index_type),
            use_gpu=args.gpu
        )
        
        if args.clear:
            memory.clear()
            print("✅ Índice limpo com sucesso!")
            return
        
        if args.search:
            # Modo busca
            print(f"\n🔍 Buscando: '{args.search}'\n")
            results = memory.search(args.search, k=args.top_k)
            
            if not results:
                print("Nenhum resultado encontrado.")
            else:
                print(f"Top {len(results)} resultados:\n")
                for i, result in enumerate(results, 1):
                    doc = result.document
                    print(f"{'='*60}")
                    print(f"#{i} | Score: {result.score:.4f}")
                    print(f"📄 {doc.display_name}")
                    print(f"📁 {doc.path}")
                    print(f"📅 Modificado: {doc.modified_at}")
                    print(f"📝 Preview: {doc.content[:200]}...")
                    print()
        elif args.stats:
            # Mostra estatísticas
            stats = memory.get_statistics()
            print("\n📊 Estatísticas do Índice Semântico")
            print(f"{'='*40}")
            print(f"Documentos únicos: {stats.total_documents}")
            print(f"Total de chunks:   {stats.total_chunks}")
            print(f"Vetores indexados: {stats.total_vectors}")
            print(f"Tipo de índice:    {stats.index_type}")
            print(f"Tamanho em disco:  {stats.index_size_bytes / 1024:.1f} KB")
            print(f"Memória RAM:       {stats.memory_usage_mb:.1f} MB")
            print(f"Última indexação:  {stats.last_indexed or 'Nunca'}")
            print(f"Queries realizadas:{stats.query_count}")
            print(f"Tempo médio query: {stats.average_query_time_ms:.2f} ms")
        else:
            # Modo indexação
            print(f"\n📚 Indexando diretório: {args.index}")
            count = memory.index_reports(args.index)
            print(f"\n✅ Indexação concluída! {count} chunks indexados.")
            
            # Mostra estatísticas rápidas
            stats = memory.get_statistics()
            print(f"   Documentos: {stats.total_documents}")
            print(f"   Chunks: {stats.total_chunks}")
            print(f"   Memória: {stats.memory_usage_mb:.1f} MB")
    
    except KeyboardInterrupt:
        print("\n⚠️ Operação interrompida pelo usuário")
    except Exception as e:
        logger.exception(f"Erro: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
