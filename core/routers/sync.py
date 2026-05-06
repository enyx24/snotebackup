"""
Router for sync operations.
Exposes endpoints for server to trigger client-side full sync.
"""

try:
    from fastapi import APIRouter, Header, HTTPException, status
except ImportError:
    # Fallback if FastAPI not imported yet
    APIRouter = None

from utils.load_config import _load_client_config
from utils.log import get_logger
from core.services.full_sync import FullSyncService

logger = get_logger(__name__)


if APIRouter:
    router = APIRouter(prefix="/sync", tags=["sync"])
else:
    router = None


def _verify_token(authorization: str = None) -> bool:
    """
    Verify Authorization header token against config.
    Expects format: "Bearer {token}"
    """
    if not authorization:
        return False
    
    try:
        cfg = _load_client_config("config/services.yaml")
        client_cfg = cfg.get("services", {}).get("client", {}) if isinstance(cfg, dict) else cfg
        expected_token = client_cfg.get("token")
        
        if expected_token and authorization.startswith("Bearer "):
            token = authorization[7:]  # Remove "Bearer " prefix
            return token == expected_token
    except Exception as e:
        logger.error("Token verification error: %s", e)
    
    return False


if router:
    @router.post("/trigger_full_sync")
    def trigger_full_sync(authorization: str = Header(None)):
        """
        Trigger a full sync from client to server.
        Requires Authorization: Bearer {token} header.
        """
        if not _verify_token(authorization):
            logger.warning("Unauthorized full_sync request")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing authorization token"
            )
        
        try:
            logger.info("Starting full sync triggered by server")
            svc = FullSyncService()
            result = svc.run()
            logger.info("Full sync completed: %s", result)
            return {"status": "success", "result": result}
        except Exception as e:
            logger.error("Full sync failed: %s", e, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Full sync failed: {str(e)}"
            )

    @router.get("/checkpoint")
    def get_checkpoint(authorization: str = Header(None)):
        """
        Get current sync checkpoint status.
        Requires Authorization: Bearer {token} header.
        """
        if not _verify_token(authorization):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing authorization token"
            )
        
        try:
            from core.db.client_db import SyncCheckpointDB
            checkpoint_db = SyncCheckpointDB()
            checkpoint = checkpoint_db.get_checkpoint()
            return {"status": "success", "checkpoint": checkpoint}
        except Exception as e:
            logger.error("Failed to get checkpoint: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get checkpoint: {str(e)}"
            )
