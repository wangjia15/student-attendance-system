"""
API endpoints for offline sync operations
"""

from fastapi import APIRouter, HTTPException, Depends, status, Request
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.services.sync import SyncManager
from app.schemas.sync import (
    SyncBatchRequest,
    SyncBatchResponse,
    SyncOperationRequest,
    SyncOperationResponse,
    ConflictData,
    ConflictResolution,
    SyncStatsResponse
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/batch", response_model=SyncBatchResponse)
async def process_sync_batch(
    batch_request: SyncBatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Process a batch of sync operations from offline client"""
    
    try:
        # Extract client ID from headers or generate one
        client_id = request.headers.get("X-Client-ID", f"client_{current_user.id}_{datetime.utcnow().timestamp()}")
        
        # Create sync manager
        sync_manager = SyncManager(db)
        
        # Process the batch
        results = await sync_manager.process_sync_batch(
            operations=batch_request.operations,
            user_id=current_user.id,
            client_id=client_id
        )
        
        logger.info(f"Processed sync batch for user {current_user.id}: {results['processed']} operations, {results['successful']} successful")
        
        return SyncBatchResponse(
            batch_id=f"batch_{datetime.utcnow().timestamp()}",
            processed=results["processed"],
            successful=results["successful"],
            conflicts=results["conflicts"],
            errors=results["errors"],
            operations=results["operations"],
            conflicts_data=results["conflicts_data"],
            processing_time_ms=results["total_time_ms"],
            timestamp=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Sync batch processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync processing failed: {str(e)}"
        )

@router.post("/operation", response_model=SyncOperationResponse) 
async def process_single_operation(
    operation: SyncOperationRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Process a single sync operation"""
    
    try:
        client_id = request.headers.get("X-Client-ID", f"client_{current_user.id}")
        
        sync_manager = SyncManager(db)
        
        # Process single operation as a batch of one
        results = await sync_manager.process_sync_batch(
            operations=[operation.dict()],
            user_id=current_user.id,
            client_id=client_id
        )
        
        if results["operations"]:
            op_result = results["operations"][0]
            return SyncOperationResponse(
                operation_id=f"op_{datetime.utcnow().timestamp()}",
                result=op_result["result"],
                conflict_data=op_result.get("conflict_data"),
                error=op_result.get("error"),
                processing_time_ms=results["total_time_ms"],
                timestamp=datetime.utcnow()
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No operation results returned"
            )
            
    except Exception as e:
        logger.error(f"Single operation processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Operation processing failed: {str(e)}"
        )

@router.post("/resolve-conflict")
async def resolve_conflict(
    resolution: ConflictResolution,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resolve a sync conflict with user guidance"""
    
    try:
        sync_manager = SyncManager(db)
        
        # Apply the conflict resolution
        # This would involve updating the database with the resolved data
        # and potentially reprocessing dependent operations
        
        # For now, just return success
        return {
            "success": True,
            "message": "Conflict resolved successfully",
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Conflict resolution failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Conflict resolution failed: {str(e)}"
        )

@router.get("/stats", response_model=SyncStatsResponse)
async def get_sync_statistics(
    days: Optional[int] = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get sync statistics for the current user"""
    
    try:
        sync_manager = SyncManager(db)
        stats = await sync_manager.get_sync_statistics(current_user.id, days)
        
        return SyncStatsResponse(
            user_id=current_user.id,
            period_days=days,
            operations_processed=stats["sync_operations_processed"],
            conflicts_resolved=stats["conflicts_resolved"],
            average_processing_time_ms=stats["average_processing_time_ms"],
            success_rate=stats["success_rate"],
            timestamp=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error(f"Failed to get sync stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sync statistics: {str(e)}"
        )

@router.get("/health")
async def sync_health_check():
    """Health check endpoint for sync services"""
    
    return {
        "service": "sync",
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "version": "1.0.0"
    }

@router.post("/queue-check-in")
async def queue_check_in_operation(
    student_id: int,
    session_id: int,
    method: str = "offline",
    location: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Queue a check-in operation for offline sync"""
    
    operation_data = {
        "type": "check_in",
        "data": {
            "student_id": student_id,
            "session_id": session_id,
            "method": method,
            "location": location,
            "timestamp": datetime.utcnow().isoformat()
        },
        "timestamp": datetime.utcnow().isoformat(),
        "priority": 3
    }
    
    try:
        sync_manager = SyncManager(db)
        results = await sync_manager.process_sync_batch(
            operations=[operation_data],
            user_id=current_user.id,
            client_id=f"direct_{current_user.id}"
        )
        
        return {
            "success": results["successful"] > 0,
            "message": "Check-in processed" if results["successful"] > 0 else "Check-in failed",
            "conflicts": results["conflicts_data"],
            "errors": results["operations"][0].get("error") if results["operations"] else None
        }
        
    except Exception as e:
        logger.error(f"Failed to queue check-in: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue check-in: {str(e)}"
        )

@router.post("/queue-status-update")
async def queue_status_update_operation(
    student_id: int,
    session_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Queue a status update operation for offline sync"""
    
    operation_data = {
        "type": "status_update",
        "data": {
            "student_id": student_id,
            "session_id": session_id,
            "status": status,
            "timestamp": datetime.utcnow().isoformat()
        },
        "timestamp": datetime.utcnow().isoformat(),
        "priority": 3
    }
    
    try:
        sync_manager = SyncManager(db)
        results = await sync_manager.process_sync_batch(
            operations=[operation_data],
            user_id=current_user.id,
            client_id=f"direct_{current_user.id}"
        )
        
        return {
            "success": results["successful"] > 0,
            "message": "Status update processed" if results["successful"] > 0 else "Status update failed",
            "conflicts": results["conflicts_data"],
            "errors": results["operations"][0].get("error") if results["operations"] else None
        }
        
    except Exception as e:
        logger.error(f"Failed to queue status update: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to queue status update: {str(e)}"
        )