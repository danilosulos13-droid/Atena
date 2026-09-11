"""
SMS Connector - Integração com SMS via Twilio
Suporta envio e recebimento de mensagens SMS
"""
import aiohttp
import logging
from typing import Dict, Any, List, Optional
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class SMSConnector(BaseConnector):
    """Conector para SMS via Twilio"""
    
    TWILIO_API_URL = "https://api.twilio.com/2010-04-01"
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.account_sid = config.custom_config.get('account_sid')
        self.auth_token = config.api_key
        self.from_number = config.custom_config.get('from_number')
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def connect(self) -> bool:
        """Conecta ao Twilio"""
        try:
            if not self.validate_config():
                return False
            
            if not self.account_sid or not self.auth_token or not self.from_number:
                logger.error("Twilio Account SID, Auth Token ou From Number não configurados")
                return False
            
            # Criar sessão HTTP
            self.session = aiohttp.ClientSession()
            
            # Testar conexão
            url = f"{self.TWILIO_API_URL}/Accounts/{self.account_sid}"
            auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
            
            async with self.session.get(url, auth=auth) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(f"✓ Twilio conectado: {data.get('friendly_name')}")
                    self.is_connected = True
                    return True
                else:
                    logger.error("Erro ao conectar Twilio")
                    return False
        
        except Exception as e:
            logger.error(f"Erro ao conectar Twilio: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta do Twilio"""
        try:
            if self.session:
                await self.session.close()
            self.is_connected = False
            logger.info("Twilio desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar Twilio: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem SMS via Twilio"""
        try:
            if not self.is_connected or not self.session:
                logger.error("Twilio não conectado")
                return False
            
            url = f"{self.TWILIO_API_URL}/Accounts/{self.account_sid}/Messages.json"
            auth = aiohttp.BasicAuth(self.account_sid, self.auth_token)
            
            # Limitar mensagem a 160 caracteres (SMS padrão)
            if len(content) > 160:
                logger.warning(f"Mensagem SMS truncada de {len(content)} para 160 caracteres")
                content = content[:160]
            
            data = {
                'From': self.from_number,
                'To': recipient_id,
                'Body': content
            }
            
            async with self.session.post(url, data=data, auth=auth) as resp:
                if resp.status in [200, 201]:
                    result = await resp.json()
                    if result.get('sid'):
                        logger.info(f"✓ SMS enviado para {recipient_id}")
                        return True
                
                error = await resp.text()
                logger.error(f"Erro ao enviar SMS: {error}")
                return False
        
        except Exception as e:
            logger.error(f"Erro ao enviar SMS: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Retorna mensagens enfileiradas"""
        return await self.get_queued_messages()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """Processa webhook do Twilio (SMS recebido)"""
        try:
            # Extrair informações do webhook
            sender_id = payload.get('From')
            content = payload.get('Body', '[Mensagem vazia]')
            message_type = "text"
            
            # Detectar se tem anexo
            num_media = int(payload.get('NumMedia', 0))
            if num_media > 0:
                message_type = "file"
                content = f"[{num_media} anexo(s) recebido(s)]"
            
            # Criar objeto Message
            message = Message(
                connector_name='sms',
                sender_id=sender_id,
                sender_name=f"SMS {sender_id}",
                content=content,
                message_type=message_type,
                metadata={
                    'message_sid': payload.get('MessageSid'),
                    'timestamp': payload.get('Timestamp'),
                    'num_media': num_media
                }
            )
            
            await self.queue_message(message)
            logger.info(f"✓ SMS recebido de {sender_id}")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao processar webhook SMS: {e}")
            return False
