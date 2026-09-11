"""
Email Connector - Integração com Email via SMTP e IMAP
Suporta envio e recebimento de emails
"""
import aiosmtplib
import logging
from typing import Dict, Any, List, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class EmailConnector(BaseConnector):
    """Conector para Email"""
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.smtp_host = config.custom_config.get('smtp_host', 'smtp.gmail.com')
        self.smtp_port = config.custom_config.get('smtp_port', 587)
        self.email_address = config.custom_config.get('email_address')
        self.email_password = config.api_key
        self.smtp_client: Optional[aiosmtplib.SMTP] = None
    
    async def connect(self) -> bool:
        """Conecta ao servidor SMTP"""
        try:
            if not self.validate_config():
                return False
            
            if not self.email_address or not self.email_password:
                logger.error("Email address ou password não configurados")
                return False
            
            # Conectar ao servidor SMTP
            self.smtp_client = aiosmtplib.SMTP(hostname=self.smtp_host, port=self.smtp_port)
            await self.smtp_client.connect()
            await self.smtp_client.starttls()
            await self.smtp_client.login(self.email_address, self.email_password)
            
            logger.info(f"✓ Email conectado: {self.email_address}")
            self.is_connected = True
            return True
        
        except Exception as e:
            logger.error(f"Erro ao conectar Email: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta do servidor SMTP"""
        try:
            if self.smtp_client:
                await self.smtp_client.quit()
            self.is_connected = False
            logger.info("Email desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar Email: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia email"""
        try:
            if not self.is_connected or not self.smtp_client:
                logger.error("Email não conectado")
                return False
            
            # Extrair assunto (padrão: "Mensagem da ATENA Ω")
            subject = kwargs.get('subject', 'Mensagem da ATENA Ω')
            
            # Criar mensagem
            message = MIMEMultipart('alternative')
            message['Subject'] = subject
            message['From'] = self.email_address
            message['To'] = recipient_id
            
            # Adicionar corpo em HTML
            html_part = MIMEText(content, 'html')
            message.attach(html_part)
            
            # Enviar email
            await self.smtp_client.send_message(message)
            
            logger.info(f"✓ Email enviado para {recipient_id}")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao enviar email: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Retorna mensagens enfileiradas"""
        return await self.get_queued_messages()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """
        Processa webhook de email
        Esperado formato: {
            'from': 'sender@example.com',
            'to': 'recipient@example.com',
            'subject': 'Assunto',
            'body': 'Corpo do email',
            'html': 'Corpo em HTML (opcional)'
        }
        """
        try:
            sender_email = payload.get('from')
            subject = payload.get('subject', '[Sem assunto]')
            body = payload.get('body', '')
            html_body = payload.get('html', '')
            
            # Usar HTML se disponível, senão usar texto
            content = html_body if html_body else body
            
            # Combinar assunto e corpo
            full_content = f"**{subject}**\n\n{content}"
            
            # Criar objeto Message
            message = Message(
                connector_name='email',
                sender_id=sender_email,
                sender_name=payload.get('sender_name', sender_email),
                content=full_content,
                message_type="text",
                metadata={
                    'subject': subject,
                    'message_id': payload.get('message_id'),
                    'timestamp': payload.get('timestamp')
                }
            )
            
            await self.queue_message(message)
            logger.info(f"✓ Email recebido de {sender_email}")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao processar webhook Email: {e}")
            return False
    
    async def send_html_email(self, recipient_id: str, subject: str, html_content: str) -> bool:
        """Envia email com conteúdo HTML"""
        return await self.send_message(
            recipient_id,
            html_content,
            subject=subject
        )
