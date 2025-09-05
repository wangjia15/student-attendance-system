/**
 * Offline Attendance Hook
 * 
 * Provides a unified interface for attendance operations with offline support:
 * - Automatic offline/online detection
 * - Seamless data persistence during offline periods
 * - Conflict resolution integration
 * - Progress tracking for sync operations
 * - Optimistic UI updates
 */

import { useState, useEffect, useCallback } from 'react';
import { 
  useNetworkState, 
  useSyncStatus, 
  useOfflineState, 
  useConflictState,
  useSyncStore 
} from '../store/sync';
import { offlineStorage } from '../services/offline/offlineStorage';
import progressiveSync from '../services/offline/progressiveSync';

export interface AttendanceOperation {
  id: string;
  type: 'check_in' | 'status_update' | 'bulk_update';
  studentId?: number;
  sessionId: number;
  status?: string;
  data: any;
  timestamp: Date;
  synced: boolean;
  error?: string;
}

export interface OfflineAttendanceState {
  isOnline: boolean;
  isSyncing: boolean;
  pendingOperations: AttendanceOperation[];
  lastSyncTime: Date | null;
  syncProgress: {
    total: number;
    completed: number;
    failed: number;
  };
  conflicts: any[];
  networkQuality: number;
}

export interface UseOfflineAttendanceReturn {
  // State
  state: OfflineAttendanceState;
  
  // Actions
  checkInStudent: (studentId: number, sessionId: number, options?: {
    method?: string;
    location?: string;
  }) => Promise<{ success: boolean; operationId?: string; error?: string }>;
  
  updateAttendanceStatus: (studentId: number, sessionId: number, status: string, options?: {
    reason?: string;
    timestamp?: Date;
  }) => Promise<{ success: boolean; operationId?: string; error?: string }>;
  
  bulkUpdateAttendance: (updates: Array<{
    studentId: number;
    status: string;
    reason?: string;
  }>, sessionId: number) => Promise<{ success: boolean; operationId?: string; error?: string }>;
  
  // Sync management
  forcSync: () => Promise<void>;
  pauseSync: () => void;
  resumeSync: () => void;
  
  // Offline management
  getOfflineCapabilities: () => {
    canCheckIn: boolean;
    canUpdateStatus: boolean;
    canBulkUpdate: boolean;
    estimatedStorageLeft: string;
  };
  
  clearOfflineData: () => Promise<void>;
  
  // Progress tracking
  getSyncProgress: () => {
    isActive: boolean;
    current: string | null;
    progress: number;
    eta: string | null;
  };
}

/**
 * Hook for managing offline attendance operations
 */
export const useOfflineAttendance = (): UseOfflineAttendanceReturn => {
  const { isOnline, networkQuality } = useNetworkState();
  const { status: syncStatus, progress: syncProgress, lastSyncAt } = useSyncStatus();
  const { offlineChanges, unsyncedChanges } = useOfflineState();
  const { activeConflicts } = useConflictState();
  const { queueAttendanceUpdate, queueBulkOperation, startSync, pauseSync, resumeSync } = useSyncStore();
  
  const [pendingOperations, setPendingOperations] = useState<AttendanceOperation[]>([]);
  const [syncProgressState, setSyncProgressState] = useState<any>(null);
  
  // Update pending operations from offline changes
  useEffect(() => {
    const operations: AttendanceOperation[] = offlineChanges.map(change => ({
      id: change.id,
      type: change.type as any,
      studentId: change.data.student_id,
      sessionId: change.data.session_id || change.data.class_session_id,
      status: change.data.status,
      data: change.data,
      timestamp: new Date(change.timestamp),
      synced: change.synced,
      error: undefined
    }));
    
    setPendingOperations(operations);
  }, [offlineChanges]);
  
  // Listen to progressive sync updates
  useEffect(() => {
    const unsubscribe = progressiveSync.onProgress((progress) => {
      setSyncProgressState(progress);
    });
    
    return unsubscribe;
  }, []);
  
  // Check-in student with offline support
  const checkInStudent = useCallback(async (
    studentId: number,
    sessionId: number,
    options: { method?: string; location?: string } = {}
  ): Promise<{ success: boolean; operationId?: string; error?: string }> => {
    
    try {
      const operationData = {
        student_id: studentId,
        session_id: sessionId,
        method: options.method || 'manual',
        location: options.location,
        timestamp: new Date().toISOString(),
        check_in_time: new Date().toISOString()
      };
      
      if (isOnline) {
        // Try online operation first
        try {
          const response = await fetch(`/api/attendance/check-in`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(operationData)
          });
          
          if (response.ok) {
            return { success: true };
          } else {
            throw new Error(`HTTP ${response.status}`);
          }
        } catch (error) {
          // Fall back to offline mode
          console.warn('Online check-in failed, queuing for offline sync:', error);
        }
      }
      
      // Queue for offline sync
      const operationId = await queueAttendanceUpdate(
        studentId,
        'present',
        sessionId.toString()
      );
      
      return { success: true, operationId };
      
    } catch (error) {
      return { 
        success: false, 
        error: error instanceof Error ? error.message : 'Unknown error' 
      };
    }
  }, [isOnline, queueAttendanceUpdate]);
  
  // Update attendance status with offline support
  const updateAttendanceStatus = useCallback(async (
    studentId: number,
    sessionId: number,
    status: string,
    options: { reason?: string; timestamp?: Date } = {}
  ): Promise<{ success: boolean; operationId?: string; error?: string }> => {
    
    try {
      const operationData = {
        student_id: studentId,
        session_id: sessionId,
        status,
        reason: options.reason,
        timestamp: (options.timestamp || new Date()).toISOString()
      };
      
      if (isOnline) {
        // Try online operation first
        try {
          const response = await fetch(`/api/attendance/${sessionId}/students/${studentId}`, {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(operationData)
          });
          
          if (response.ok) {
            return { success: true };
          } else {
            throw new Error(`HTTP ${response.status}`);
          }
        } catch (error) {
          // Fall back to offline mode
          console.warn('Online status update failed, queuing for offline sync:', error);
        }
      }
      
      // Queue for offline sync
      const operationId = await queueAttendanceUpdate(
        studentId,
        status,
        sessionId.toString()
      );
      
      return { success: true, operationId };
      
    } catch (error) {
      return { 
        success: false, 
        error: error instanceof Error ? error.message : 'Unknown error' 
      };
    }
  }, [isOnline, queueAttendanceUpdate]);
  
  // Bulk update attendance with offline support
  const bulkUpdateAttendance = useCallback(async (
    updates: Array<{
      studentId: number;
      status: string;
      reason?: string;
    }>,
    sessionId: number
  ): Promise<{ success: boolean; operationId?: string; error?: string }> => {
    
    try {
      const operations = updates.map(update => ({
        type: 'status_update',
        data: {
          student_id: update.studentId,
          session_id: sessionId,
          status: update.status,
          reason: update.reason,
          timestamp: new Date().toISOString()
        },
        timestamp: new Date().toISOString(),
        priority: 2
      }));
      
      if (isOnline) {
        // Try online operation first
        try {
          const response = await fetch(`/api/attendance/bulk`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ operations })
          });
          
          if (response.ok) {
            return { success: true };
          } else {
            throw new Error(`HTTP ${response.status}`);
          }
        } catch (error) {
          // Fall back to offline mode
          console.warn('Online bulk update failed, queuing for offline sync:', error);
        }
      }
      
      // Queue for offline sync
      const operationId = await queueBulkOperation(operations);
      
      return { success: true, operationId };
      
    } catch (error) {
      return { 
        success: false, 
        error: error instanceof Error ? error.message : 'Unknown error' 
      };
    }
  }, [isOnline, queueBulkOperation]);
  
  // Force sync
  const forceSync = useCallback(async (): Promise<void> => {
    await startSync(true);
  }, [startSync]);
  
  // Get offline capabilities
  const getOfflineCapabilities = useCallback(() => {
    const storageInfo = navigator.storage && navigator.storage.estimate ? 
      navigator.storage.estimate() : Promise.resolve({ usage: 0, quota: 0 });
    
    return {
      canCheckIn: true,
      canUpdateStatus: true,
      canBulkUpdate: true,
      estimatedStorageLeft: 'Unknown' // Would need to implement storage estimation
    };
  }, []);
  
  // Clear offline data
  const clearOfflineData = useCallback(async (): Promise<void> => {
    await offlineStorage.clearAllCache();
    setPendingOperations([]);
  }, []);
  
  // Get sync progress
  const getSyncProgress = useCallback(() => {
    const isActive = syncStatus === 'syncing';
    const progress = syncProgress.total > 0 ? (syncProgress.completed / syncProgress.total) * 100 : 0;
    
    let eta: string | null = null;
    if (syncProgressState && syncProgressState.estimatedTimeRemaining > 0) {
      const seconds = Math.ceil(syncProgressState.estimatedTimeRemaining / 1000);
      if (seconds < 60) {
        eta = `${seconds}s`;
      } else {
        eta = `${Math.ceil(seconds / 60)}m`;
      }
    }
    
    return {
      isActive,
      current: syncProgress.currentOperation || null,
      progress,
      eta
    };
  }, [syncStatus, syncProgress, syncProgressState]);
  
  // Build state object
  const state: OfflineAttendanceState = {
    isOnline,
    isSyncing: syncStatus === 'syncing',
    pendingOperations,
    lastSyncTime: lastSyncAt ? new Date(lastSyncAt) : null,
    syncProgress: {
      total: syncProgress.total,
      completed: syncProgress.completed,
      failed: syncProgress.failed
    },
    conflicts: activeConflicts,
    networkQuality
  };
  
  return {
    state,
    checkInStudent,
    updateAttendanceStatus,
    bulkUpdateAttendance,
    forcSync: forceSync,
    pauseSync,
    resumeSync,
    getOfflineCapabilities,
    clearOfflineData,
    getSyncProgress
  };
};

export default useOfflineAttendance;