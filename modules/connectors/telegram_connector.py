"""
Telegram Connector - Integração com Telegram Bot API
Suporta envio e recebimento de mensagens via Telegram
"""
import aiohttp
import logging
from typing import Dict, Any, List, Optional
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class TelegramConnector(BaseConnector):
    """Conector para Telegram"""
    
    TELEGRAM_API_URL = "https://api.telegram.org"
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.bot_token = config.api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_update_id = 0
    
    async def connect(self) -> bool:
        """Conecta ao Telegram"""
        try:
            if not self.validate_config():
                return False
            
            if not self.bot_token:
                logger.error("Telegram Bot Token não configurado")
                return False
            
            # Criar sessão HTTP
            self.session = aiohttp.ClientSession()
            
            # Testar conexão
            url = f"{self.TELEGRAM_API_URL}/bot{self.bot_token}/getMe"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('ok'):
                        bot_info = data.get('result', {})
                        logger.info(f"✓ Telegram bot conectado: @{bot_info.get('username')}")
                        self.is_connected = True
                        return True
            
            logger.error("Erro ao conectar Telegram")
            return False
        
        except Exception as e:
            logger.error(f"Erro ao conectar Telegram: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta do Telegram"""
        try:
            if self.session:
                await self.session.close()
            self.is_connected = False
            logger.info("Telegram desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar Telegram: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem via Telegram"""
        try:
            if not self.is_connected or not self.session:
                logger.error("Telegram não conectado")
                return False
            
            url = f"{self.TELEGRAM_API_URL}/bot{self.bot_token}/sendMessage"
            
            payload = {
                "chat_id": recipient_id,
                "text": content,
                "parse_mode": kwargs.get('parse_mode', 'HTML')
            }
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('ok'):
                        logger.info(f"✓ Mensagem Telegram enviada para {recipient_id}")
                        return True
                
                error = await resp.text()
                logger.error(f"Erro ao enviar mensagem Telegram: {error}")
                return False
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem Telegram: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Recebe mensagens do Telegram via polling"""
        try:
            if not self.is_connected or not self.session:
                return []
            
            url = f"{self.TELEGRAM_API_URL}/bot{self.bot_token}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": 30
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                
                data = await resp.json()
                if not data.get('ok'):
                    return []
                
                messages = []
                for update in data.get('result', []):
                    self.last_update_id = update.get('update_id', self.last_update_id)
                    
                    if 'message' not in update:
                        continue
                    
                    msg_data = update['message']
                    
                    # Extrair informações
                    sender_id = str(msg_data['from']['id'])
                    sender_name = msg_data['from'].get('first_name', 'Usuário Telegram')
                    content = msg_data.get('text', '[Mensagem não-texto]')
                    message_type = "text"
                    
                    # Detectar tipo de mensagem
                    if 'photo' in msg_data:
                        message_type = "image"
                        content = msg_data.get('caption', '[Foto recebida]')
                    elif 'document' in msg_data:
                        message_type = "file"
                        content = f"[Arquivo: {msg_data['document'].get('file_name', 'desconhecido')}]"
                    elif 'voice' in msg_data:
                        message_type = "audio"
                        content = "[Mensagem de voz recebida]"
                    
                    # Criar objeto Message
                    message = Message(
                        connector_name='telegram',
                        sender_id=sender_id,
                        sender_name=sender_name,
                        content=content,
                        message_type=message_type,
                        metadata={
                            'chat_id': str(msg_data['chat']['id']),
                            'message_id': str(msg_data['message_id'])
                        }
                    )
                    
                    messages.append(message)
                    logger.info(f"✓ Mensagem Telegram recebida de {sender_name}")
                
                return messages
        
        except Exception as e:
            logger.error(f"Erro ao receber mensagens Telegram: {e}")
            return []
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """Processa webhook do Telegram"""
        try:
            if 'message' not in payload:
                return False
            
            msg_data = payload['message']
            
            # Extrair informações
            sender_id = str(msg_data['from']['id'])
            sender_name = msg_data['from'].get('first_name', 'Usuário Telegram')
            content = msg_data.get('text', '[Mensagem não-texto]')
            message_type = "text"
            
            # Detectar tipo de mensagem
            if 'photo' in msg_data:
                message_type = "image"
                content = msg_data.get('caption', '[Foto recebida]')
            elif 'document' in msg_data:
                message_type = "file"
                content = f"[Arquivo: {msg_data['document'].get('file_name', 'desconhecido')}]"
            
            # Criar objeto Message
            message = Message(
                connector_name='telegram',
                sender_id=sender_id,
                sender_name=sender_name,
                content=content,
                message_type=message_type,
                metadata={
                    'chat_id': str(msg_data['chat']['id']),
                    'message_id': str(msg_data['message_id'])
                }
            )
            
            await self.queue_message(message)
            logger.info(f"✓ Webhook Telegram processado de {sender_name}")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao processar webhook Telegram: {e}")
            return False
