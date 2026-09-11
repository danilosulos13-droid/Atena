"""
Microsoft Teams Connector - Integração com Teams via Bot Framework
Suporta envio e recebimento de mensagens em canais e chats
"""
import aiohttp
import logging
from typing import Dict, Any, List, Optional
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class TeamsConnector(BaseConnector):
    """Conector para Microsoft Teams"""
    
    TEAMS_API_URL = "https://graph.microsoft.com/v1.0"
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.app_id = config.custom_config.get('app_id')
        self.app_password = config.api_secret
        self.session: Optional[aiohttp.ClientSession] = None
        self.access_token = None
    
    async def _get_access_token(self) -> Optional[str]:
        """Obtém token de acesso do Microsoft"""
        try:
            url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
            
            data = {
                'grant_type': 'client_credentials',
                'client_id': self.app_id,
                'client_secret': self.app_password,
                'scope': 'https://api.botframework.com/.default'
            }
            
            async with self.session.post(url, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get('access_token')
            
            logger.error("Erro ao obter token de acesso Teams")
            return None
        
        except Exception as e:
            logger.error(f"Erro ao obter token Teams: {e}")
            return None
    
    async def connect(self) -> bool:
        """Conecta ao Microsoft Teams"""
        try:
            if not self.validate_config():
                return False
            
            if not self.app_id or not self.app_password:
                logger.error("Teams App ID ou Password não configurados")
                return False
            
            # Criar sessão HTTP
            self.session = aiohttp.ClientSession()
            
            # Obter token de acesso
            self.access_token = await self._get_access_token()
            
            if self.access_token:
                logger.info("✓ Microsoft Teams conectado com sucesso")
                self.is_connected = True
                return True
            else:
                logger.error("Erro ao conectar Teams")
                return False
        
        except Exception as e:
            logger.error(f"Erro ao conectar Teams: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta do Microsoft Teams"""
        try:
            if self.session:
                await self.session.close()
            self.is_connected = False
            logger.info("Microsoft Teams desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar Teams: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem via Teams"""
        try:
            if not self.is_connected or not self.session or not self.access_token:
                logger.error("Teams não conectado")
                return False
            
            # recipient_id formato: "chat_id" ou "channel_id"
            url = f"{self.TEAMS_API_URL}/chats/{recipient_id}/messages"
            
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "body": {
                    "contentType": "html",
                    "content": content
                }
            }
            
            async with self.session.post(url, json=payload, headers=headers) as resp:
                if resp.status in [200, 201]:
                    logger.info(f"✓ Mensagem Teams enviada para {recipient_id}")
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Erro ao enviar mensagem Teams: {error}")
                    return False
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem Teams: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Retorna mensagens enfileiradas"""
        return await self.get_queued_messages()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """Processa webhook do Teams (Activity)"""
        try:
            # Verificar tipo de atividade
            activity_type = payload.get('type')
            
            if activity_type != 'message':
                return False
            
            # Extrair informações
            sender = payload.get('from', {})
            sender_id = sender.get('id', 'unknown')
            sender_name = sender.get('name', 'Usuário Teams')
            content = payload.get('text', '[Mensagem vazia]')
            channel_data = payload.get('channelData', {})
            
            message_type = "text"
            
            # Detectar tipo de mensagem
            if 'attachments' in payload:
                message_type = "file"
                attachments = payload['attachments']
                content = f"[{len(attachments)} anexo(s)]"
            
            # Criar objeto Message
            message = Message(
                connector_name='teams',
                sender_id=sender_id,
                sender_name=sender_name,
                content=content,
                message_type=message_type,
                metadata={
                    'conversation_id': payload.get('conversation', {}).get('id'),
                    'activity_id': payload.get('id'),
                    'channel_id': channel_data.get('teamsChannelId')
                }
            )
            
            await self.queue_message(message)
            logger.info(f"✓ Mensagem Teams recebida de {sender_name}")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao processar webhook Teams: {e}")
            return False
