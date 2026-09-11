"""
WhatsApp Connector - Integração com WhatsApp Business API
Suporta envio e recebimento de mensagens via WhatsApp
"""
import aiohttp
import logging
from typing import Dict, Any, List
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class WhatsAppConnector(BaseConnector):
    """Conector para WhatsApp Business API"""
    
    WHATSAPP_API_URL = "https://graph.instagram.com/v18.0"
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.phone_number_id = config.custom_config.get('phone_number_id')
        self.business_account_id = config.custom_config.get('business_account_id')
        self.session: aiohttp.ClientSession = None
    
    async def connect(self) -> bool:
        """Conecta à API do WhatsApp"""
        try:
            if not self.validate_config():
                return False
            
            if not self.config.api_key:
                logger.error("WhatsApp API Key não configurada")
                return False
            
            # Criar sessão HTTP
            self.session = aiohttp.ClientSession()
            
            # Testar conexão
            url = f"{self.WHATSAPP_API_URL}/{self.phone_number_id}"
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    self.is_connected = True
                    logger.info(f"✓ WhatsApp conectado com sucesso")
                    return True
                else:
                    logger.error(f"Erro ao conectar WhatsApp: {resp.status}")
                    return False
        
        except Exception as e:
            logger.error(f"Erro ao conectar WhatsApp: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta da API do WhatsApp"""
        try:
            if self.session:
                await self.session.close()
            self.is_connected = False
            logger.info("WhatsApp desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar WhatsApp: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem via WhatsApp"""
        try:
            if not self.is_connected:
                logger.error("WhatsApp não conectado")
                return False
            
            url = f"{self.WHATSAPP_API_URL}/{self.phone_number_id}/messages"
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient_id,
                "type": "text",
                "text": {"body": content}
            }
            
            async with self.session.post(url, json=payload, headers=headers) as resp:
                if resp.status in [200, 201]:
                    logger.info(f"✓ Mensagem WhatsApp enviada para {recipient_id}")
                    return True
                else:
                    error = await resp.text()
                    logger.error(f"Erro ao enviar mensagem WhatsApp: {error}")
                    return False
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem WhatsApp: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Retorna mensagens enfileiradas"""
        return await self.get_queued_messages()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """Processa webhook do WhatsApp"""
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
                        # Extrair informações da mensagem
                        sender_id = msg['from']
                        message_id = msg['id']
                        timestamp = msg.get('timestamp', '')
                        
                        # Extrair conteúdo baseado no tipo
                        content = ""
                        message_type = "text"
                        
                        if 'text' in msg:
                            content = msg['text']['body']
                        elif 'image' in msg:
                            message_type = "image"
                            content = msg['image'].get('caption', '[Imagem recebida]')
                        elif 'document' in msg:
                            message_type = "file"
                            content = f"[Arquivo: {msg['document'].get('filename', 'desconhecido')}]"
                        
                        # Criar objeto Message
                        message = Message(
                            connector_name='whatsapp',
                            sender_id=sender_id,
                            sender_name=f"WhatsApp {sender_id}",
                            content=content,
                            message_type=message_type,
                            timestamp=timestamp,
                            metadata={'message_id': message_id}
                        )
                        
                        await self.queue_message(message)
                        logger.info(f"✓ Mensagem WhatsApp recebida de {sender_id}")
            
            return True
        
        except Exception as e:
            logger.error(f"Erro ao processar webhook WhatsApp: {e}")
            return False
    
    async def verify_webhook(self, token: str, challenge: str) -> str:
        """Verifica webhook do WhatsApp (GET request)"""
        # Retornar o challenge para verificação
        return challenge
