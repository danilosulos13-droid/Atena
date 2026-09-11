"""
Base Connector - Classe abstrata para todos os conectores da Atena
Define a interface padrão que todos os conectores devem implementar
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConnectorConfig:
    """Configuração de um conector"""
    name: str  # Nome único do conector (ex: 'whatsapp', 'discord')
    service_type: str  # Tipo de serviço (ex: 'messaging', 'social')
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    webhook_url: Optional[str] = None
    custom_config: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário (sem dados sensíveis)"""
        return {
            'name': self.name,
            'service_type': self.service_type,
            'webhook_url': self.webhook_url,
            'enabled': self.enabled,
            'created_at': self.created_at,
            'custom_config': self.custom_config
        }


@dataclass
class Message:
    """Mensagem padrão entre Atena e serviços externos"""
    connector_name: str
    sender_id: str
    sender_name: str
    content: str
    message_type: str = "text"  # text, image, audio, file, etc
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'connector_name': self.connector_name,
            'sender_id': self.sender_id,
            'sender_name': self.sender_name,
            'content': self.content,
            'message_type': self.message_type,
            'timestamp': self.timestamp,
            'metadata': self.metadata
        }


class BaseConnector(ABC):
    """
    Classe base abstrata para todos os conectores.
    Define a interface que cada conector deve implementar.
    """
    
    def __init__(self, config: ConnectorConfig):
        self.config = config
        self.is_connected = False
        self.message_queue: List[Message] = []
        logger.info(f"Inicializando conector: {config.name}")
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Conecta ao serviço externo
        Retorna True se bem-sucedido, False caso contrário
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """
        Desconecta do serviço externo
        """
        pass
    
    @abstractmethod
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """
        Envia uma mensagem para um destinatário
        """
        pass
    
    @abstractmethod
    async def receive_messages(self) -> List[Message]:
        """
        Recebe mensagens do serviço externo
        Retorna lista de mensagens recebidas
        """
        pass
    
    @abstractmethod
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """
        Processa webhook recebido do serviço externo
        """
        pass
    
    async def get_status(self) -> Dict[str, Any]:
        """Retorna status do conector"""
        return {
            'name': self.config.name,
            'service_type': self.config.service_type,
            'is_connected': self.is_connected,
            'enabled': self.config.enabled,
            'pending_messages': len(self.message_queue),
            'created_at': self.config.created_at
        }
    
    async def queue_message(self, message: Message) -> None:
        """Adiciona mensagem à fila"""
        self.message_queue.append(message)
        logger.debug(f"Mensagem enfileirada em {self.config.name}: {message.sender_name}")
    
    async def get_queued_messages(self) -> List[Message]:
        """Retorna e limpa fila de mensagens"""
        messages = self.message_queue.copy()
        self.message_queue.clear()
        return messages
    
    def validate_config(self) -> bool:
        """Valida se a configuração é válida"""
        if not self.config.name or not self.config.service_type:
            logger.error(f"Configuração inválida: nome ou tipo de serviço faltando")
            return False
        return True
    
    async def __aenter__(self):
        """Context manager support"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager support"""
        await self.disconnect()
