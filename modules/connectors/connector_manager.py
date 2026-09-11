"""
Connector Manager - Gerencia todos os conectores da Atena
Responsável por inicializar, configurar e orquestrar conectores
"""
import json
import logging
from typing import Dict, Any, List, Optional, Type
from pathlib import Path
from .base_connector import BaseConnector, ConnectorConfig, Message
from .whatsapp_connector import WhatsAppConnector
from .discord_connector import DiscordConnector
from .telegram_connector import TelegramConnector
from .slack_connector import SlackConnector
from .teams_connector import TeamsConnector
from .instagram_connector import InstagramConnector
from .sms_connector import SMSConnector
from .email_connector import EmailConnector

logger = logging.getLogger(__name__)


class ConnectorManager:
    """Gerencia todos os conectores da Atena"""
    
    # Mapa de tipos de conectores disponíveis
    CONNECTOR_TYPES: Dict[str, Type[BaseConnector]] = {
        'whatsapp': WhatsAppConnector,
        'discord': DiscordConnector,
        'telegram': TelegramConnector,
        'slack': SlackConnector,
        'teams': TeamsConnector,
        'instagram': InstagramConnector,
        'sms': SMSConnector,
        'email': EmailConnector,
    }
    
    def __init__(self, config_path: str = "/home/ubuntu/Atena-IA/config/connectors.json"):
        self.config_path = Path(config_path)
        self.connectors: Dict[str, BaseConnector] = {}
        self.config_data: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self) -> bool:
        """Carrega configurações de conectores do arquivo"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    self.config_data = json.load(f)
                logger.info(f"✓ Configurações de conectores carregadas de {self.config_path}")
                return True
            else:
                logger.warning(f"Arquivo de configuração não encontrado: {self.config_path}")
                self.config_data = {}
                return False
        except Exception as e:
            logger.error(f"Erro ao carregar configurações: {e}")
            return False
    
    def save_config(self) -> bool:
        """Salva configurações de conectores em arquivo"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump(self.config_data, f, indent=2)
            logger.info(f"✓ Configurações salvas em {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar configurações: {e}")
            return False
    
    def register_connector(self, connector_type: str, config: ConnectorConfig) -> bool:
        """Registra um novo conector"""
        try:
            if connector_type not in self.CONNECTOR_TYPES:
                logger.error(f"Tipo de conector desconhecido: {connector_type}")
                return False
            
            # Criar instância do conector
            connector_class = self.CONNECTOR_TYPES[connector_type]
            connector = connector_class(config)
            
            # Armazenar conector
            self.connectors[config.name] = connector
            
            # Salvar configuração
            self.config_data[config.name] = {
                'type': connector_type,
                'config': config.to_dict()
            }
            self.save_config()
            
            logger.info(f"✓ Conector registrado: {config.name} ({connector_type})")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao registrar conector: {e}")
            return False
    
    async def connect_all(self) -> Dict[str, bool]:
        """Conecta todos os conectores registrados"""
        results = {}
        for name, connector in self.connectors.items():
            try:
                success = await connector.connect()
                results[name] = success
                logger.info(f"{'✓' if success else '✗'} {name}: {'conectado' if success else 'falha na conexão'}")
            except Exception as e:
                logger.error(f"Erro ao conectar {name}: {e}")
                results[name] = False
        
        return results
    
    async def disconnect_all(self) -> Dict[str, bool]:
        """Desconecta todos os conectores"""
        results = {}
        for name, connector in self.connectors.items():
            try:
                success = await connector.disconnect()
                results[name] = success
                logger.info(f"{'✓' if success else '✗'} {name}: {'desconectado' if success else 'falha ao desconectar'}")
            except Exception as e:
                logger.error(f"Erro ao desconectar {name}: {e}")
                results[name] = False
        
        return results
    
    async def send_message_to_connector(self, connector_name: str, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem através de um conector específico"""
        if connector_name not in self.connectors:
            logger.error(f"Conector não encontrado: {connector_name}")
            return False
        
        connector = self.connectors[connector_name]
        if not connector.is_connected:
            logger.error(f"Conector não conectado: {connector_name}")
            return False
        
        return await connector.send_message(recipient_id, content, **kwargs)
    
    async def receive_all_messages(self) -> List[Message]:
        """Recebe mensagens de todos os conectores"""
        all_messages = []
        for name, connector in self.connectors.items():
            try:
                if connector.is_connected:
                    messages = await connector.receive_messages()
                    all_messages.extend(messages)
            except Exception as e:
                logger.error(f"Erro ao receber mensagens de {name}: {e}")
        
        return all_messages
    
    async def handle_webhook(self, connector_name: str, payload: Dict[str, Any]) -> bool:
        """Processa webhook de um conector"""
        if connector_name not in self.connectors:
            logger.error(f"Conector não encontrado: {connector_name}")
            return False
        
        return await self.connectors[connector_name].handle_webhook(payload)
    
    async def get_status(self) -> Dict[str, Any]:
        """Retorna status de todos os conectores"""
        status = {}
        for name, connector in self.connectors.items():
            status[name] = await connector.get_status()
        
        return {
            'total_connectors': len(self.connectors),
            'connected': sum(1 for c in self.connectors.values() if c.is_connected),
            'connectors': status
        }
    
    def get_connector(self, name: str) -> Optional[BaseConnector]:
        """Retorna um conector específico"""
        return self.connectors.get(name)
    
    def list_connectors(self) -> List[str]:
        """Lista todos os conectores registrados"""
        return list(self.connectors.keys())
    
    def list_available_types(self) -> List[str]:
        """Lista tipos de conectores disponíveis"""
        return list(self.CONNECTOR_TYPES.keys())
