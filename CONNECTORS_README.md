# 🔗 Módulo de Conectores da ATENA Ω

Sistema modular e extensível que permite a ATENA se conectar a qualquer serviço externo (WhatsApp, Discord, Telegram, etc).

## 📋 Arquitetura

```
modules/connectors/
├── base_connector.py          # Classe abstrata base
├── whatsapp_connector.py       # Conector WhatsApp
├── discord_connector.py        # Conector Discord
├── telegram_connector.py       # Conector Telegram
├── connector_manager.py        # Gerenciador central
└── __init__.py                # Exports

api/
├── connectors_api.py          # API REST para gerenciar conectores
└── main.py                    # Integração na API principal

config/
└── connectors.json            # Configurações de conectores
```

## 🚀 Conectores Disponíveis

### WhatsApp Business API
- **Tipo**: `whatsapp`
- **Recursos**: Enviar/receber mensagens, suporte a mídia
- **Configuração**:
  ```json
  {
    "name": "whatsapp_business",
    "connector_type": "whatsapp",
    "api_key": "YOUR_WHATSAPP_API_KEY",
    "custom_config": {
      "phone_number_id": "YOUR_PHONE_NUMBER_ID",
      "business_account_id": "YOUR_BUSINESS_ACCOUNT_ID"
    }
  }
  ```

### Discord Bot
- **Tipo**: `discord`
- **Recursos**: Enviar/receber mensagens em servidores, suporte a canais
- **Configuração**:
  ```json
  {
    "name": "discord_bot",
    "connector_type": "discord",
    "api_key": "YOUR_DISCORD_BOT_TOKEN"
  }
  ```

### Telegram Bot
- **Tipo**: `telegram`
- **Recursos**: Enviar/receber mensagens, polling ou webhooks
- **Configuração**:
  ```json
  {
    "name": "telegram_bot",
    "connector_type": "telegram",
    "api_key": "YOUR_TELEGRAM_BOT_TOKEN",
    "webhook_url": "https://seu-dominio.com/webhooks/telegram"
  }
  ```

## 📡 API REST

### Endpoints Disponíveis

#### 1. Listar tipos disponíveis
```bash
GET /api/connectors/available-types
```

Resposta:
```json
{
  "available_types": ["whatsapp", "discord", "telegram"],
  "description": {
    "whatsapp": "WhatsApp Business API - Enviar/receber mensagens via WhatsApp",
    "discord": "Discord Bot - Integração com servidores Discord",
    "telegram": "Telegram Bot API - Enviar/receber mensagens via Telegram"
  }
}
```

#### 2. Registrar novo conector
```bash
POST /api/connectors/register
Content-Type: application/json

{
  "name": "whatsapp_business",
  "connector_type": "whatsapp",
  "api_key": "YOUR_API_KEY",
  "custom_config": {
    "phone_number_id": "123456789"
  },
  "enabled": true
}
```

#### 3. Conectar um conector
```bash
POST /api/connectors/connect/{connector_name}
```

#### 4. Desconectar um conector
```bash
POST /api/connectors/disconnect/{connector_name}
```

#### 5. Conectar todos
```bash
POST /api/connectors/connect-all
```

#### 6. Enviar mensagem
```bash
POST /api/connectors/send-message
Content-Type: application/json

{
  "connector_name": "whatsapp_business",
  "recipient_id": "5511999999999",
  "content": "Olá! Sou a ATENA Ω",
  "message_type": "text"
}
```

#### 7. Receber mensagens
```bash
GET /api/connectors/messages
```

#### 8. Status de todos
```bash
GET /api/connectors/status
```

#### 9. Status de um conector
```bash
GET /api/connectors/{connector_name}/status
```

#### 10. Processar webhook
```bash
POST /api/connectors/webhooks/{connector_name}
Content-Type: application/json

{payload do webhook}
```

## 💻 Uso Programático

### Exemplo: Registrar e usar WhatsApp

```python
from modules.connectors import ConnectorManager, ConnectorConfig

# Criar gerenciador
manager = ConnectorManager()

# Criar configuração
config = ConnectorConfig(
    name="whatsapp_business",
    service_type="messaging",
    api_key="YOUR_API_KEY",
    custom_config={
        "phone_number_id": "123456789",
        "business_account_id": "987654321"
    }
)

# Registrar conector
manager.register_connector('whatsapp', config)

# Conectar
await manager.connect_all()

# Enviar mensagem
await manager.send_message_to_connector(
    "whatsapp_business",
    "5511999999999",
    "Olá! Sou a ATENA Ω"
)

# Receber mensagens
messages = await manager.receive_all_messages()
for msg in messages:
    print(f"{msg.sender_name}: {msg.content}")
```

### Exemplo: Criar conector customizado

```python
from modules.connectors import BaseConnector, ConnectorConfig, Message
from typing import Dict, Any, List

class SlackConnector(BaseConnector):
    """Conector customizado para Slack"""
    
    async def connect(self) -> bool:
        # Implementar lógica de conexão
        self.is_connected = True
        return True
    
    async def disconnect(self) -> bool:
        self.is_connected = False
        return True
    
    async def send_message(self, recipient_id: str, content: str, **kwargs) -> bool:
        # Implementar envio de mensagem
        return True
    
    async def receive_messages(self) -> List[Message]:
        # Implementar recebimento de mensagens
        return []
    
    async def handle_webhook(self, payload: Dict[str, Any]) -> bool:
        # Implementar processamento de webhook
        return True

# Registrar conector customizado
manager.CONNECTOR_TYPES['slack'] = SlackConnector
```

## 🔄 Fluxo de Mensagens

```
Serviço Externo (WhatsApp/Discord/Telegram)
            ↓
    Webhook ou Polling
            ↓
    Conector (recebe)
            ↓
    Fila de Mensagens
            ↓
    ATENA Ω (processa)
            ↓
    Resposta da ATENA
            ↓
    Conector (envia)
            ↓
Serviço Externo (entrega)
```

## 🛠️ Configuração

### Arquivo `config/connectors.json`

```json
{
  "whatsapp_business": {
    "type": "whatsapp",
    "config": {
      "name": "whatsapp_business",
      "service_type": "messaging",
      "api_key": "YOUR_WHATSAPP_API_KEY",
      "webhook_url": "https://seu-dominio.com/webhooks/whatsapp",
      "custom_config": {
        "phone_number_id": "YOUR_PHONE_NUMBER_ID",
        "business_account_id": "YOUR_BUSINESS_ACCOUNT_ID"
      },
      "enabled": false
    }
  }
}
```

## 📝 Estrutura de Mensagem

```python
@dataclass
class Message:
    connector_name: str          # Nome do conector
    sender_id: str              # ID do remetente
    sender_name: str            # Nome do remetente
    content: str                # Conteúdo da mensagem
    message_type: str           # text, image, audio, file
    timestamp: str              # ISO format timestamp
    metadata: Dict[str, Any]    # Dados adicionais
```

## 🔐 Segurança

- **API Keys**: Armazenadas em `config/connectors.json` (não commitadas em git)
- **Webhooks**: Validação de assinatura (implementar por conector)
- **CORS**: Habilitado para todos os domínios (ajustar em produção)
- **Logs**: Todas as operações são registradas

## 🚨 Tratamento de Erros

Todos os conectores implementam tratamento robusto de erros:
- Reconexão automática
- Fila de mensagens em caso de falha
- Logs detalhados
- Fallback gracioso

## 📚 Próximas Integrações

- [ ] Slack
- [ ] Microsoft Teams
- [ ] Instagram DM
- [ ] SMS (Twilio)
- [ ] Email
- [ ] Webhook genérico

## 🤝 Contribuindo

Para adicionar um novo conector:

1. Criar classe que herda de `BaseConnector`
2. Implementar métodos abstratos
3. Adicionar ao dicionário `CONNECTOR_TYPES` em `ConnectorManager`
4. Adicionar testes
5. Documentar no README

## 📞 Suporte

Para dúvidas ou problemas, consulte os logs em:
```
/home/ubuntu/Atena-IA/logs/connectors.log
```
