"""
FastAPI router for SIS (Student Information System) integration management.
"""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.user import User
from app.models.sis_integration import (
    SISIntegration, SISOAuthToken, SISSyncOperation, 
    SISStudentMapping, SISIntegrationStatus
)
from app.schemas.sis import (
    SISIntegrationCreate, SISIntegrationUpdate, SISIntegrationResponse,
    SISIntegrationSummary, SISOAuthTokenResponse, SISAuthorizationURL,
    SISOAuthCallback, SISSyncOperationResponse, SISSyncRequest,
    SISStudentMappingResponse, SISConflictResolution, SISHealthCheck,
    SISMetrics
)
from app.integrations.sis.config_manager import sis_config_manager
from app.integrations.sis.oauth_service import SISOAuthService
from app.integrations.sis.sync_service import RosterSyncService

router = APIRouter()


@router.get("/integrations", response_model=List[SISIntegrationSummary])
async def list_integrations(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all SIS integrations."""
    # Only allow admin users to manage SIS integrations
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISIntegration)
        .offset(skip)
        .limit(limit)
        .order_by(SISIntegration.created_at.desc())
    )
    integrations = result.scalars().all()
    
    return [SISIntegrationSummary.model_validate(integration) for integration in integrations]


@router.post("/integrations", response_model=SISIntegrationResponse, status_code=status.HTTP_201_CREATED)
async def create_integration(
    integration_data: SISIntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    # Check if provider_id already exists
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.provider_id == integration_data.provider_id)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Integration with provider_id '{integration_data.provider_id}' already exists"
        )
    
    # Create integration
    integration = SISIntegration(
        provider_id=integration_data.provider_id,
        provider_type=integration_data.provider_type,
        name=integration_data.name,
        description=integration_data.description,
        base_url=integration_data.base_url,
        api_version=integration_data.api_version,
        timeout=integration_data.timeout,
        max_retries=integration_data.max_retries,
        rate_limit=integration_data.rate_limit,
        enabled=integration_data.enabled,
        config_json=integration_data.config or {}
    )
    
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    
    # Register with configuration manager
    try:
        sis_config_manager.register_provider(
            integration.provider_id,
            integration.provider_type,
            integration.config
        )
    except Exception as e:
        # Log error but don't fail the request
        print(f"Warning: Failed to register provider with config manager: {e}")
    
    return SISIntegrationResponse.model_validate(integration)


@router.get("/integrations/{integration_id}", response_model=SISIntegrationResponse)
async def get_integration(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.id == integration_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    return SISIntegrationResponse.model_validate(integration)


@router.put("/integrations/{integration_id}", response_model=SISIntegrationResponse)
async def update_integration(
    integration_id: int,
    update_data: SISIntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.id == integration_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    # Update only provided fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        if field == 'config':
            integration.config_json = value
        else:
            setattr(integration, field, value)
    
    integration.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(integration)
    
    return SISIntegrationResponse.model_validate(integration)


@router.delete("/integrations/{integration_id}")
async def delete_integration(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.id == integration_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    await db.delete(integration)
    await db.commit()
    
    return {"message": "Integration deleted successfully"}


@router.get("/integrations/{integration_id}/auth/url", response_model=SISAuthorizationURL)
async def get_auth_url(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get OAuth authorization URL for SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.id == integration_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    try:
        oauth_service = SISOAuthService(integration.config, integration)
        auth_url, state = oauth_service.generate_authorization_url()
        return SISAuthorizationURL(authorization_url=auth_url, state=state)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to generate authorization URL: {str(e)}"
        )


@router.post("/integrations/{integration_id}/auth/callback")
async def handle_auth_callback(
    integration_id: int,
    callback_data: SISOAuthCallback,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Handle OAuth callback for SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    if callback_data.integration_id != integration_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integration ID mismatch"
        )
    
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.id == integration_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    try:
        oauth_service = SISOAuthService(integration.config, integration)
        await oauth_service.exchange_code_for_token(callback_data.code, callback_data.state, db)
        
        # Update integration status
        integration.update_auth_success()
        await db.commit()
        
        return {"message": "Authentication successful"}
    except Exception as e:
        integration.update_auth_failure()
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {str(e)}"
        )


@router.get("/integrations/{integration_id}/tokens", response_model=List[SISOAuthTokenResponse])
async def get_tokens(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get OAuth tokens for SIS integration (without sensitive data)."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISOAuthToken)
        .where(SISOAuthToken.integration_id == integration_id)
        .order_by(SISOAuthToken.created_at.desc())
    )
    tokens = result.scalars().all()
    
    return [SISOAuthTokenResponse.model_validate(token) for token in tokens]


@router.post("/integrations/{integration_id}/sync", response_model=SISSyncOperationResponse)
async def start_sync(
    integration_id: int,
    sync_request: SISSyncRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Start a sync operation for SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.id == integration_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    if not integration.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Integration is disabled"
        )
    
    # Create sync operation record
    sync_operation = SISSyncOperation(
        integration_id=integration_id,
        operation_type=sync_request.operation_type,
        status='pending'
    )
    
    db.add(sync_operation)
    await db.commit()
    await db.refresh(sync_operation)
    
    # Start background sync
    background_tasks.add_task(
        _run_sync_operation,
        sync_operation.id,
        sync_request.force_sync
    )
    
    return SISSyncOperationResponse.model_validate(sync_operation)


@router.get("/integrations/{integration_id}/sync", response_model=List[SISSyncOperationResponse])
async def get_sync_operations(
    integration_id: int,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get sync operations for SIS integration."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIS integrations"
        )
    
    result = await db.execute(
        select(SISSyncOperation)
        .where(SISSyncOperation.integration_id == integration_id)
        .offset(skip)
        .limit(limit)
        .order_by(SISSyncOperation.created_at.desc())
    )
    operations = result.scalars().all()
    
    return [SISSyncOperationResponse.model_validate(op) for op in operations]


@router.get("/integrations/{integration_id}/students", response_model=List[SISStudentMappingResponse])
async def get_student_mappings(
    integration_id: int,
    skip: int = 0,
    limit: int = 100,
    needs_sync: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get student mappings for SIS integration."""
    if current_user.role.value not in ['admin', 'teacher']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    query = select(SISStudentMapping).where(SISStudentMapping.integration_id == integration_id)
    
    if needs_sync is not None:
        query = query.where(SISStudentMapping.needs_sync == needs_sync)
    
    result = await db.execute(
        query.offset(skip).limit(limit).order_by(SISStudentMapping.created_at.desc())
    )
    mappings = result.scalars().all()
    
    return [SISStudentMappingResponse.model_validate(mapping) for mapping in mappings]


@router.post("/integrations/{integration_id}/students/resolve-conflicts")
async def resolve_conflicts(
    integration_id: int,
    resolutions: List[SISConflictResolution],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Resolve sync conflicts for student mappings."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can resolve sync conflicts"
        )
    
    try:
        sync_service = RosterSyncService()
        for resolution in resolutions:
            await sync_service.resolve_conflicts(
                db, resolution.mapping_id, resolution.resolutions
            )
        
        return {"message": f"Resolved conflicts for {len(resolutions)} mappings"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to resolve conflicts: {str(e)}"
        )


@router.get("/integrations/{integration_id}/health", response_model=SISHealthCheck)
async def check_health(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Check health status of SIS integration."""
    result = await db.execute(
        select(SISIntegration).where(SISIntegration.id == integration_id)
    )
    integration = result.scalar_one_or_none()
    
    if not integration:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found"
        )
    
    # Perform basic health checks
    issues = []
    
    if not integration.enabled:
        issues.append("Integration is disabled")
    
    if integration.auth_failure_count >= 3:
        issues.append("Multiple authentication failures")
    
    if integration.sync_failure_count >= 5:
        issues.append("Multiple sync failures")
    
    connectivity = True
    authentication = integration.auth_failure_count < 3
    
    return SISHealthCheck(
        integration_id=integration_id,
        provider_type=integration.provider_type,
        is_healthy=integration.is_healthy,
        status=integration.status,
        connectivity=connectivity,
        authentication=authentication,
        last_check=datetime.utcnow(),
        issues=issues
    )


@router.get("/metrics", response_model=SISMetrics)
async def get_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get SIS integration metrics."""
    if current_user.role.value != 'admin':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can view SIS metrics"
        )
    
    # Get integration counts
    total_result = await db.execute(select(func.count(SISIntegration.id)))
    total_integrations = total_result.scalar()
    
    active_result = await db.execute(
        select(func.count(SISIntegration.id))
        .where(SISIntegration.status == SISIntegrationStatus.ACTIVE)
    )
    active_integrations = active_result.scalar()
    
    healthy_result = await db.execute(
        select(func.count(SISIntegration.id))
        .where(
            SISIntegration.enabled == True,
            SISIntegration.status == SISIntegrationStatus.ACTIVE,
            SISIntegration.auth_failure_count < 3,
            SISIntegration.sync_failure_count < 5
        )
    )
    healthy_integrations = healthy_result.scalar()
    
    # Get sync statistics
    students_result = await db.execute(
        select(func.sum(SISIntegration.total_students_synced))
    )
    total_students_synced = students_result.scalar() or 0
    
    sync_ops_result = await db.execute(select(func.count(SISSyncOperation.id)))
    total_sync_operations = sync_ops_result.scalar()
    
    failed_sync_result = await db.execute(
        select(func.count(SISSyncOperation.id))
        .where(SISSyncOperation.status == 'failed')
    )
    failed_sync_operations = failed_sync_result.scalar()
    
    # Get average sync time
    avg_time_result = await db.execute(
        select(func.avg(SISSyncOperation.duration_seconds))
        .where(SISSyncOperation.status == 'completed')
    )
    average_sync_time = avg_time_result.scalar() or 0.0
    
    # Get last sync times by provider
    last_sync_result = await db.execute(
        select(SISIntegration.provider_type, SISIntegration.last_sync_success)
        .order_by(SISIntegration.last_sync_success.desc())
    )
    last_sync_times = {
        str(provider_type): last_sync
        for provider_type, last_sync in last_sync_result.fetchall()
    }
    
    return SISMetrics(
        total_integrations=total_integrations,
        active_integrations=active_integrations,
        healthy_integrations=healthy_integrations,
        total_students_synced=total_students_synced,
        total_sync_operations=total_sync_operations,
        failed_sync_operations=failed_sync_operations,
        average_sync_time=average_sync_time,
        last_sync_times=last_sync_times
    )


async def _run_sync_operation(operation_id: int, force_sync: bool = False):
    """Background task to run sync operation."""
    from app.core.database import get_db_session
    
    async with get_db_session() as db:
        # Get operation and integration
        result = await db.execute(
            select(SISSyncOperation)
            .options(selectinload(SISSyncOperation.integration))
            .where(SISSyncOperation.id == operation_id)
        )
        operation = result.scalar_one_or_none()
        
        if not operation:
            return
        
        try:
            # Update operation status
            operation.status = 'running'
            operation.started_at = datetime.utcnow()
            await db.commit()
            
            # Run sync based on operation type
            sync_service = RosterSyncService()
            
            if operation.operation_type == 'students':
                await sync_service.sync_students(db, operation.integration, force_sync)
            elif operation.operation_type == 'enrollments':
                await sync_service.sync_enrollments(db, operation.integration, force_sync)
            elif operation.operation_type == 'full':
                await sync_service.sync_integration_roster(db, operation.integration, force_sync)
            
            # Mark as completed
            operation.status = 'completed'
            operation.completed_at = datetime.utcnow()
            operation.integration.update_sync_success()
            
        except Exception as e:
            # Mark as failed
            operation.status = 'failed'
            operation.error_message = str(e)
            operation.completed_at = datetime.utcnow()
            operation.integration.update_sync_failure()
        
        await db.commit()