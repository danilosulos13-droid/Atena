"""
Instagram Connector - Integração com Instagram via Graph API
Suporta envio e recebimento de mensagens diretas (DM)
"""
import aiohttp
import logging
from typing import Dict, Any, List, Optional
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class InstagramConnector(BaseConnector):
    """Conector para Instagram"""
    
    INSTAGRAM_API_URL = "https://graph.instagram.com/v18.0"
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.access_token = config.api_key
        self.business_account_id = config.custom_config.get('business_account_id')
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self) -> bool:
        """Conecta ao Instagram"""
        try:
            if not self.validate_config():
                return False
            
            if not self.access_token or not self.business_account_id:
                logger.error("Instagram Access Token ou Business Account ID não configurados")
                return False
            
            # Criar sessão HTTP
            self.session = aiohttp.ClientSession()
            
            # Testar conexão
            url = f"{self.INSTAGRAM_API_URL}/{self.business_account_id}"
            params = {"access_token": self.access_token}
            
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"✓ Instagram conectado: {data.get('name')}")
                    self.is_connected = True
                    return True
                else:
                    logger.error("Erro ao conectar Instagram")
                    return False
        
        except Exception as e:
            logger.error(f"Erro ao conectar Instagram: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta do Instagram"""
        try:
            if self.session:
                await self.session.close()
            self.is_connected = False
            logger.info("Instagram desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar Instagram: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem via Instagram DM"""
        try:
            if not self.is_connected or not self.session:
                logger.error("Instagram não conectado")
                return False
            
            url = f"{self.INSTAGRAM_API_URL}/{self.business_account_id}/messages"
            
            payload = {
                "recipient": {"id": recipient_id},
                "message": {"text": content}
            }
            
            params = {"access_token": self.access_token}
            
            async with self.session.post(url, json=payload, params=params) as resp:
                if resp.status in [200, 201]:
                    data = await resp.json()
                    if data.get('message_id'):
                        logger.info(f"✓ Mensagem Instagram enviada para {recipient_id}")
                        return True
                
                error = await resp.text()
                logger.error(f"Erro ao enviar mensagem Instagram: {error}")
                return False
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem Instagram: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Retorna mensagens enfileiradas"""
        return await self.get_queued_messages()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """Processa webhook do Instagram"""
        try:
            # Verificar se é um evento de mensagem
            if 'entry' not in payload:
                return False
            
            for entry in payload['entry']:
                for change in entry.get('changes', []):
                    if change['field'] != 'messages':
                        continue
                    
                    messages = change['value'].get('messages', [])
                    for msg in messages:
                        # Extrair informações
                        sender_id = msg['from']['id']
                        sender_name = msg['from'].get('name', f"Instagram {sender_id}")
                        content = msg.get('text', '[Mensagem vazia]')
                        message_type = "text"
                        
                        # Detectar tipo de mensagem
                        if 'image' in msg:
                            message_type = "image"
                            content = "[Imagem recebida]"
                        elif 'video' in msg:
                            message_type = "video"
                            content = "[Vídeo recebido]"
                        elif 'file' in msg:
                            message_type = "file"
                            content = "[Arquivo recebido]"
                        
                        # Criar objeto Message
                        message = Message(
                            connector_name='instagram',
                            sender_id=sender_id,
                            sender_name=sender_name,
                            content=content,
                            message_type=message_type,
                            metadata={
                                'message_id': msg.get('id'),
                                'timestamp': msg.get('timestamp')
                            }
                        )
                        
                        await self.queue_message(message)
                        logger.info(f"✓ Mensagem Instagram recebida de {sender_name}")
            
            return True
        
        except Exception as e:
            logger.error(f"Erro ao processar webhook Instagram: {e}")
            return False
