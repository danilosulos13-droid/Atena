"""
Módulo de Conectores da Atena
Permite integração com serviços externos como WhatsApp, Discord, Telegram, etc.
"""

from .base_connector import BaseConnector, ConnectorConfig, Message
from .whatsapp_connector import WhatsAppConnector
from .discord_connector import DiscordConnector
from .telegram_connector import TelegramConnector
from .slack_connector import SlackConnector
from .teams_connector import TeamsConnector
from .instagram_connector import InstagramConnector
from .sms_connector import SMSConnector
from .email_connector import EmailConnector
from .connector_manager import ConnectorManager

__all__ = [
    'BaseConnector',
    'ConnectorConfig',
    'Message',
    'WhatsAppConnector',
    'DiscordConnector',
    'TelegramConnector',
    'SlackConnector',
    'TeamsConnector',
    'InstagramConnector',
    'SMSConnector',
    'EmailConnector',
    'ConnectorManager',
]
