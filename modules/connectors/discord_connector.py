"""
Discord Connector - Integração com Discord via Bot
Suporta envio e recebimento de mensagens em servidores Discord
"""
import discord
from discord.ext import commands
import logging
from typing import Dict, Any, List, Optional
from .base_connector import BaseConnector, ConnectorConfig, Message

logger = logging.getLogger(__name__)


class DiscordConnector(BaseConnector):
    """Conector para Discord"""
    
    def __init__(self, config: ConnectorConfig):
        super().__init__(config)
        self.bot: Optional[commands.Bot] = None
        self.intents = discord.Intents.default()
        self.intents.message_content = True
        self.intents.direct_messages = True
    
    async def connect(self) -> bool:
        """Conecta ao Discord"""
        try:
            if not self.validate_config():
                return False
            
            if not self.config.api_key:
                logger.error("Discord Token não configurado")
                return False
            
            # Criar bot Discord
            self.bot = commands.Bot(command_prefix='!', intents=self.intents)
            
            # Registrar eventos
            @self.bot.event
            async def on_ready():
                logger.info(f"✓ Discord bot conectado como {self.bot.user}")
                self.is_connected = True
            
            @self.bot.event
            async def on_message(message: discord.Message):
                # Ignorar mensagens do próprio bot
                if message.author == self.bot.user:
                    return
                
                # Criar objeto Message
                msg = Message(
                    connector_name='discord',
                    sender_id=str(message.author.id),
                    sender_name=str(message.author),
                    content=message.content,
                    message_type="text",
                    metadata={
                        'channel_id': str(message.channel.id),
                        'guild_id': str(message.guild.id) if message.guild else None,
                        'message_id': str(message.id)
                    }
                )
                
                await self.queue_message(msg)
                logger.info(f"✓ Mensagem Discord recebida de {message.author}")
            
            # Conectar ao Discord
            await self.bot.start(self.config.api_key)
            return True
        
        except Exception as e:
            logger.error(f"Erro ao conectar Discord: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Desconecta do Discord"""
        try:
            if self.bot:
                await self.bot.close()
            self.is_connected = False
            logger.info("Discord desconectado")
            return True
        except Exception as e:
            logger.error(f"Erro ao desconectar Discord: {e}")
            return False
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        """Envia mensagem via Discord"""
        try:
            if not self.is_connected or not self.bot:
                logger.error("Discord não conectado")
                return False
            
            # recipient_id pode ser user_id ou channel_id
            channel_or_user = await self.bot.fetch_channel(int(recipient_id)) or \
                             await self.bot.fetch_user(int(recipient_id))
            
            if not channel_or_user:
                logger.error(f"Destinatário Discord não encontrado: {recipient_id}")
                return False
            
            # Dividir mensagens longas em chunks (limite Discord: 2000 caracteres)
            max_length = 2000
            for i in range(0, len(content), max_length):
                chunk = content[i:i+max_length]
                await channel_or_user.send(chunk)
            
            logger.info(f"✓ Mensagem Discord enviada para {recipient_id}")
            return True
        
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem Discord: {e}")
            return False
    
    async def receive_messages(self) -> List[Message]:
        """Retorna mensagens enfileiradas"""
        return await self.get_queued_messages()
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        """Discord usa eventos em tempo real, não webhooks"""
        logger.warning("Discord não usa webhooks, use eventos em tempo real")
        return False
