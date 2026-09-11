"""
API de Conectores - Endpoints para gerenciar conectores da Atena
Permite adicionar, configurar e monitorar conectores
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

# Importar o gerenciador de conectores
from modules.connectors import ConnectorManager, ConnectorConfig

# Criar router
router = APIRouter(prefix="/api/connectors", tags=["connectors"])

# Instância global do gerenciador
connector_manager: Optional[ConnectorManager] = None


def get_connector_manager() -> ConnectorManager:
    """Obtém instância do gerenciador de conectores"""
    global connector_manager
    if connector_manager is None:
        connector_manager = ConnectorManager()
    return connector_manager


# --- MODELOS PYDANTIC ---

class ConnectorConfigRequest(BaseModel):
    """Requisição para criar/atualizar conector"""
    name: str
    connector_type: str  # whatsapp, discord, telegram, etc
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    webhook_url: Optional[str] = None
    custom_config: Dict[str, Any] = {}
    enabled: bool = True


class MessageRequest(BaseModel):
    """Requisição para enviar mensagem"""
    connector_name: str
    recipient_id: str
    content: str
    message_type: str = "text"


# --- ENDPOINTS ---

@router.get("/available-types")
async def get_available_connector_types() -> Dict[str, Any]:
    """Retorna tipos de conectores disponíveis"""
    manager = get_connector_manager()
    return {
        "available_types": manager.list_available_types(),
        "description": {
            "whatsapp": "WhatsApp Business API - Enviar/receber mensagens via WhatsApp",
            "discord": "Discord Bot - Integração com servidores Discord",
            "telegram": "Telegram Bot API - Enviar/receber mensagens via Telegram"
        }
    }


@router.get("/status")
async def get_connectors_status() -> Dict[str, Any]:
    """Retorna status de todos os conectores"""
    manager = get_connector_manager()
    return await manager.get_status()


@router.get("/list")
async def list_connectors() -> Dict[str, Any]:
    """Lista todos os conectores registrados"""
    manager = get_connector_manager()
    return {
        "connectors": manager.list_connectors(),
        "total": len(manager.list_connectors())
    }


@router.post("/register")
async def register_connector(request: ConnectorConfigRequest) -> Dict[str, Any]:
    """Registra um novo conector"""
    try:
        manager = get_connector_manager()
        
        # Criar configuração
        config = ConnectorConfig(
            name=request.name,
            service_type=request.connector_type,
            api_key=request.api_key,
            api_secret=request.api_secret,
            webhook_url=request.webhook_url,
            custom_config=request.custom_config,
            enabled=request.enabled
        )
        
        # Registrar conector
        success = manager.register_connector(request.connector_type, config)
        
        if success:
            return {
                "success": True,
                "message": f"Conector '{request.name}' registrado com sucesso",
                "connector_name": request.name
            }
        else:
            raise HTTPException(status_code=400, detail="Erro ao registrar conector")
    
    except Exception as e:
        logger.error(f"Erro ao registrar conector: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect/{connector_name}")
async def connect_connector(connector_name: str) -> Dict[str, Any]:
    """Conecta um conector específico"""
    try:
        manager = get_connector_manager()
        connector = manager.get_connector(connector_name)
        
        if not connector:
            raise HTTPException(status_code=404, detail=f"Conector não encontrado: {connector_name}")
        
        success = await connector.connect()
        
        return {
            "success": success,
            "connector": connector_name,
            "message": "Conectado com sucesso" if success else "Falha na conexão"
        }
    
    except Exception as e:
        logger.error(f"Erro ao conectar: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect/{connector_name}")
async def disconnect_connector(connector_name: str) -> Dict[str, Any]:
    """Desconecta um conector específico"""
    try:
        manager = get_connector_manager()
        connector = manager.get_connector(connector_name)
        
        if not connector:
            raise HTTPException(status_code=404, detail=f"Conector não encontrado: {connector_name}")
        
        success = await connector.disconnect()
        
        return {
            "success": success,
            "connector": connector_name,
            "message": "Desconectado com sucesso" if success else "Falha ao desconectar"
        }
    
    except Exception as e:
        logger.error(f"Erro ao desconectar: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect-all")
async def connect_all(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Conecta todos os conectores"""
    try:
        manager = get_connector_manager()
        results = await manager.connect_all()
        
        return {
            "success": True,
            "results": results,
            "connected": sum(1 for v in results.values() if v),
            "total": len(results)
        }
    
    except Exception as e:
        logger.error(f"Erro ao conectar todos: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-message")
async def send_message(request: MessageRequest) -> Dict[str, Any]:
    """Envia mensagem através de um conector"""
    try:
        manager = get_connector_manager()
        success = await manager.send_message_to_connector(
            request.connector_name,
            request.recipient_id,
            request.content
        )
        
        return {
            "success": success,
            "connector": request.connector_name,
            "recipient": request.recipient_id,
            "message": "Mensagem enviada com sucesso" if success else "Falha ao enviar mensagem"
        }
    
    except Exception as e:
        logger.error(f"Erro ao enviar mensagem: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages")
async def get_all_messages() -> Dict[str, Any]:
    """Recebe todas as mensagens de todos os conectores"""
    try:
        manager = get_connector_manager()
        messages = await manager.receive_all_messages()
        
        return {
            "success": True,
            "total_messages": len(messages),
            "messages": [msg.to_dict() for msg in messages]
        }
    
    except Exception as e:
        logger.error(f"Erro ao receber mensagens: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhooks/{connector_name}")
async def handle_webhook(connector_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Processa webhook de um conector"""
    try:
        manager = get_connector_manager()
        success = await manager.handle_webhook(connector_name, payload)
        
        return {
            "success": success,
            "connector": connector_name,
            "message": "Webhook processado" if success else "Falha ao processar webhook"
        }
    
    except Exception as e:
        logger.error(f"Erro ao processar webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_name}/status")
async def get_connector_status(connector_name: str) -> Dict[str, Any]:
    """Retorna status de um conector específico"""
    try:
        manager = get_connector_manager()
        connector = manager.get_connector(connector_name)
        
        if not connector:
            raise HTTPException(status_code=404, detail=f"Conector não encontrado: {connector_name}")
        
        status = await connector.get_status()
        return status
    
    except Exception as e:
        logger.error(f"Erro ao obter status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
