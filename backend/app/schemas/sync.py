"""
Pydantic schemas for sync operations
"""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Dict, Any, Optional, Union
from enum import Enum

class SyncOperationType(str, Enum):
    """Sync operation types"""
    CHECK_IN = "check_in"
    STATUS_UPDATE = "status_update" 
    BULK_OPERATION = "bulk_operation"
    SESSION_UPDATE = "session_update"

class SyncResult(str, Enum):
    """Sync operation results"""
    SUCCESS = "success"
    CONFLICT = "conflict"
    ERROR = "error"
    PARTIAL_SUCCESS = "partial_success"

class ConflictType(str, Enum):
    """Types of sync conflicts"""
    ATTENDANCE_STATUS = "attendance_status"
    TIMESTAMP_CONFLICT = "timestamp_conflict"
    CONCURRENT_MODIFICATION = "concurrent_modification"
    DATA_INTEGRITY = "data_integrity"

class SyncOperationRequest(BaseModel):
    """Request for a single sync operation"""
    type: SyncOperationType
    data: Dict[str, Any]
    timestamp: datetime
    priority: Optional[int] = Field(default=1, ge=1, le=10)
    depends_on: Optional[List[str]] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class SyncBatchRequest(BaseModel):
    """Request for batch sync operations"""
    operations: List[Dict[str, Any]]
    client_info: Optional[Dict[str, Any]] = None
    batch_timeout_ms: Optional[int] = Field(default=30000, ge=1000, le=300000)
    
    class Config:
        schema_extra = {
            "example": {
                "operations": [
                    {
                        "type": "check_in",
                        "data": {
                            "student_id": 123,
                            "session_id": 456,
                            "method": "offline",
                            "location": "Room 101"
                        },
                        "timestamp": "2023-12-01T10:30:00Z",
                        "priority": 3
                    },
                    {
                        "type": "status_update",
                        "data": {
                            "student_id": 124,
                            "session_id": 456,
                            "status": "present"
                        },
                        "timestamp": "2023-12-01T10:31:00Z",
                        "priority": 2
                    }
                ],
                "client_info": {
                    "version": "1.0.0",
                    "platform": "web",
                    "offline_duration_ms": 120000
                }
            }
        }

class ConflictData(BaseModel):
    """Conflict information"""
    type: ConflictType
    local_data: Dict[str, Any]
    server_data: Dict[str, Any]
    message: str
    resolution_options: Optional[List[str]] = None

class SyncOperationResult(BaseModel):
    """Result of a single sync operation"""
    type: SyncOperationType
    result: SyncResult
    data: Optional[Dict[str, Any]] = None
    conflict_data: Optional[ConflictData] = None
    error: Optional[str] = None
    processing_time_ms: Optional[int] = None

class SyncOperationResponse(BaseModel):
    """Response for a single sync operation"""
    operation_id: str
    result: SyncResult
    conflict_data: Optional[ConflictData] = None
    error: Optional[str] = None
    processing_time_ms: int
    timestamp: datetime
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class SyncBatchResponse(BaseModel):
    """Response for batch sync operations"""
    batch_id: str
    processed: int
    successful: int
    conflicts: int
    errors: int
    operations: List[SyncOperationResult]
    conflicts_data: List[Dict[str, Any]]
    processing_time_ms: int
    timestamp: datetime
    bandwidth_info: Optional[Dict[str, Any]] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "batch_id": "batch_1701429600.123",
                "processed": 2,
                "successful": 1,
                "conflicts": 1,
                "errors": 0,
                "operations": [
                    {
                        "type": "check_in",
                        "result": "success",
                        "processing_time_ms": 150
                    },
                    {
                        "type": "status_update", 
                        "result": "conflict",
                        "conflict_data": {
                            "type": "attendance_status",
                            "local_data": {"status": "present"},
                            "server_data": {"status": "absent"},
                            "message": "Status conflict detected"
                        }
                    }
                ],
                "conflicts_data": [],
                "processing_time_ms": 320,
                "timestamp": "2023-12-01T10:30:00.123Z"
            }
        }

class ConflictResolutionStrategy(str, Enum):
    """Conflict resolution strategies"""
    LOCAL_WINS = "local_wins"
    SERVER_WINS = "server_wins"
    MERGE = "merge"
    USER_GUIDED = "user_guided"
    REJECT = "reject"

class ConflictResolution(BaseModel):
    """User-provided conflict resolution"""
    conflict_id: str
    strategy: ConflictResolutionStrategy
    resolved_data: Optional[Dict[str, Any]] = None
    user_notes: Optional[str] = None
    
    class Config:
        schema_extra = {
            "example": {
                "conflict_id": "conflict_123",
                "strategy": "local_wins",
                "resolved_data": {
                    "status": "present",
                    "notes": "Student was present but system showed absent"
                },
                "user_notes": "Student confirmed they were in class"
            }
        }

class SyncStatsResponse(BaseModel):
    """Sync statistics response"""
    user_id: int
    period_days: int
    operations_processed: int
    conflicts_resolved: int
    average_processing_time_ms: float
    success_rate: float
    timestamp: datetime
    detailed_stats: Optional[Dict[str, Any]] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        schema_extra = {
            "example": {
                "user_id": 123,
                "period_days": 7,
                "operations_processed": 45,
                "conflicts_resolved": 3,
                "average_processing_time_ms": 250.5,
                "success_rate": 95.6,
                "timestamp": "2023-12-01T10:30:00Z",
                "detailed_stats": {
                    "operations_by_type": {
                        "check_in": 20,
                        "status_update": 15,
                        "bulk_operation": 10
                    },
                    "conflicts_by_type": {
                        "attendance_status": 2,
                        "timestamp_conflict": 1
                    }
                }
            }
        }

class NetworkOptimizationRequest(BaseModel):
    """Request for network-optimized sync"""
    connection_speed: Optional[str] = None  # "2g", "3g", "4g", "wifi"
    data_saver_mode: Optional[bool] = False
    max_operations_per_batch: Optional[int] = Field(default=10, ge=1, le=100)
    compression_enabled: Optional[bool] = True
    
class ProgressiveSync(BaseModel):
    """Progressive sync configuration"""
    chunk_size: int = Field(default=5, ge=1, le=50)
    chunk_delay_ms: int = Field(default=1000, ge=0, le=10000)
    priority_threshold: int = Field(default=3, ge=1, le=10)
    bandwidth_limit_kbps: Optional[int] = None

class OfflineCapabilities(BaseModel):
    """Client offline capabilities"""
    max_offline_duration_ms: int
    storage_capacity_mb: float
    supported_operations: List[SyncOperationType]
    conflict_resolution_mode: str  # "auto", "manual", "hybrid"

class SyncHealthResponse(BaseModel):
    """Sync service health information"""
    service: str
    status: str
    timestamp: datetime
    version: str
    active_connections: Optional[int] = None
    queue_length: Optional[int] = None
    average_response_time_ms: Optional[float] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }