"""
Slack Connector - Integração com Slack via Bot API
Suporta envio e recebimento de mensagens em canais e DMs
"""
import aiohttp
import logging
from typing import Dict, Any, List, Optional
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class SlackConnector(BaseConnector):
    """Conector para Slack"""
    
    SLACK_API_URL = "https://slack.com/api"
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.bot_token = config.api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.bot_user_id = None
    
    async def connect(self) -> bool:
        """Conecta ao Slack"""
        try:
            if not self.validate_config():
                return False
            
            if not self.bot_token:
                logger.error("Slack Bot Token não configurado")
                return False
            
            # Criar sessão HTTP
            self.session = aiohttp.ClientSession()
            
            # Testar conexão e obter info do bot
            url = f"{self.SLACK_API_URL}/auth.test"
            headers = {"Authorization": f"Bearer {self.bot_token}"}
            
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('ok'):
                        self.bot_user_id = data.get('user_id')
                        logger.info(f"✓ Slack bot conectado: {data.get('user')}")
                        self.is_connected = True
                        return True
            
            logger.error("Erro ao conectar Slack")
            return False
        
        except Exception as e:
            logger.error(f"Erro ao conectar Slack: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta do Slack"""
        try:
            if self.session:
                await self.session.close()
            self.is_connected = False
            logger.info("Slack desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar Slack: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem via Slack"""
        try:
            if not self.is_connected or not self.session:
                logger.error("Slack não conectado")
                return False
            
            url = f"{self.SLACK_API_URL}/chat.postMessage"
            headers = {"Authorization": f"Bearer {self.bot_token}"}
            
            payload = {
                "channel": recipient_id,
                "text": content
            }
            
            # Adicionar thread_ts se fornecido
            if 'thread_ts' in kwargs:
                payload['thread_ts'] = kwargs['thread_ts']
            
            async with self.session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('ok'):
                        logger.info(f"✓ Mensagem Slack enviada para {recipient_id}")
                        return True
                
                error = await resp.text()
                logger.error(f"Erro ao enviar mensagem Slack: {error}")
                return False
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem Slack: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Retorna mensagens enfileiradas"""
        return await self.get_queued_messages()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """Processa webhook do Slack (Event API)"""
        try:
            # Verificar se é um desafio de URL (primeira verificação)
            if payload.get('type') == 'url_verification':
                return True
            
            # Processar evento
            if payload.get('type') != 'event_callback':
                return False
            
            event = payload.get('event', {})
            
            # Ignorar mensagens do próprio bot
            if event.get('user') == self.bot_user_id:
                return True
            
            # Processar apenas mensagens de texto
            if event.get('type') != 'message':
                return False
            
            # Ignorar edições e deletions
            if event.get('subtype') in ['message_deleted', 'message_changed']:
                return False
            
            # Extrair informações
            sender_id = event.get('user', 'unknown')
            channel_id = event.get('channel', '')
            content = event.get('text', '[Mensagem vazia]')
            message_type = "text"
            
            # Detectar tipo de mensagem
            if 'files' in event:
                message_type = "file"
                files = event['files']
                content = f"[{len(files)} arquivo(s) enviado(s)]"
            
            # Criar objeto Message
            message = Message(
                connector_name='slack',
                sender_id=sender_id,
                sender_name=event.get('username', f"Slack {sender_id}"),
                content=content,
                message_type=message_type,
                metadata={
                    'channel_id': channel_id,
                    'ts': event.get('ts'),
                    'thread_ts': event.get('thread_ts')
                }
            )
            
            await self.queue_message(message)
            logger.info(f"✓ Mensagem Slack recebida de {sender_id}")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao processar webhook Slack: {e}")
            return False
