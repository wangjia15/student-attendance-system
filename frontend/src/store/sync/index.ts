/**
 * Offline Sync Store
 * 
 * Manages offline sync state and integrates with the real-time store patterns.
 * Handles:
 * - Sync queue state management
 * - Offline/online mode transitions
 * - Conflict tracking and resolution
 * - Bandwidth-aware sync scheduling
 * - Progress tracking for sync operations
 */

import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { 
  NetworkStatus, 
  NetworkInfo,
  networkMonitor 
} from '../../services/offline/networkMonitor';
import { 
  SyncStatus, 
  SyncProgress, 
  SyncResult,
  syncProcessor 
} from '../../services/offline/syncProcessor';
import { 
  ConflictData, 
  ResolutionResult,
  conflictResolver 
} from '../../utils/conflict-resolution';

// Sync store state interface
export interface SyncState {
  // Network state
  networkStatus: NetworkStatus;
  isOnline: boolean;
  networkQuality: number; // 0-100 score
  lastOnlineAt: number;
  lastSyncAt: number;
  
  // Sync operation state
  syncStatus: SyncStatus;
  syncProgress: SyncProgress;
  pendingOperations: number;
  failedOperations: number;
  
  // Offline mode state
  isOfflineMode: boolean;
  offlineChanges: Array<{
    id: string;
    type: string;
    data: any;
    timestamp: number;
    synced: boolean;
  }>;
  
  // Conflict management
  activeConflicts: ConflictData[];
  resolvedConflicts: Array<{
    conflict: ConflictData;
    resolution: ResolutionResult;
    timestamp: number;
  }>;
  
  // Sync scheduling
  scheduledSync: {
    nextSyncAt: number;
    interval: number;
    backoffMultiplier: number;
  };
  
  // Sync statistics
  stats: {
    totalSynced: number;
    totalFailed: number;
    totalConflicts: number;
    totalBytesTransferred: number;
    averageSyncTime: number;
    lastError: string | null;
  };
  
  // UI preferences
  preferences: {
    autoSync: boolean;
    syncOnGoodConnection: boolean;
    showOfflineIndicator: boolean;
    showSyncProgress: boolean;
    confirmConflictResolutions: boolean;
  };
}

// Sync store actions interface
export interface SyncActions {
  // Network state management
  updateNetworkState: (networkInfo: NetworkInfo) => void;
  setOnlineStatus: (isOnline: boolean) => void;
  
  // Sync operation management
  startSync: (force?: boolean) => Promise<void>;
  pauseSync: () => void;
  resumeSync: () => Promise<void>;
  stopSync: () => void;
  updateSyncProgress: (progress: SyncProgress) => void;
  
  // Offline mode management
  enableOfflineMode: () => void;
  disableOfflineMode: () => void;
  addOfflineChange: (type: string, data: any) => string;
  markChangeAsSynced: (changeId: string) => void;
  clearOfflineChanges: () => void;
  
  // Conflict management
  addConflict: (conflict: ConflictData) => void;
  resolveConflict: (conflictId: string, resolution: ResolutionResult) => void;
  clearConflicts: () => void;
  
  // Sync scheduling
  scheduleNextSync: (delay?: number) => void;
  clearScheduledSync: () => void;
  adjustSyncInterval: (networkQuality: number) => void;
  
  // Statistics
  recordSyncResult: (results: SyncResult[]) => void;
  resetStats: () => void;
  
  // Preferences
  setAutoSync: (enabled: boolean) => void;
  setSyncOnGoodConnection: (enabled: boolean) => void;
  setShowOfflineIndicator: (show: boolean) => void;
  setShowSyncProgress: (show: boolean) => void;
  setConfirmConflictResolutions: (confirm: boolean) => void;
  
  // Actions
  queueAttendanceUpdate: (studentId: number, status: string, sessionId: string) => Promise<string>;
  queueBulkOperation: (operations: any[]) => Promise<string>;
  processPendingChanges: () => Promise<void>;
  handleConflictResolution: (conflict: ConflictData) => Promise<ResolutionResult>;
}

// Initial state
const initialState: SyncState = {
  networkStatus: NetworkStatus.UNKNOWN,
  isOnline: false,
  networkQuality: 50,
  lastOnlineAt: 0,
  lastSyncAt: 0,
  
  syncStatus: SyncStatus.IDLE,
  syncProgress: {
    total: 0,
    completed: 0,
    failed: 0,
    estimatedTimeRemaining: 0,
    bytesTransferred: 0,
    totalBytes: 0
  },
  pendingOperations: 0,
  failedOperations: 0,
  
  isOfflineMode: false,
  offlineChanges: [],
  
  activeConflicts: [],
  resolvedConflicts: [],
  
  scheduledSync: {
    nextSyncAt: 0,
    interval: 30000, // 30 seconds default
    backoffMultiplier: 1
  },
  
  stats: {
    totalSynced: 0,
    totalFailed: 0,
    totalConflicts: 0,
    totalBytesTransferred: 0,
    averageSyncTime: 0,
    lastError: null
  },
  
  preferences: {
    autoSync: true,
    syncOnGoodConnection: true,
    showOfflineIndicator: true,
    showSyncProgress: true,
    confirmConflictResolutions: false
  }
};

// Create the sync store
export const useSyncStore = create<SyncState & SyncActions>()(
  subscribeWithSelector((set, get) => ({
    ...initialState,
    
    // Network state management
    updateNetworkState: (networkInfo: NetworkInfo) => {
      set((state) => {
        const wasOnline = state.isOnline;
        const isNowOnline = networkInfo.isOnline;
        
        const updates: Partial<SyncState> = {
          networkStatus: networkInfo.status,
          isOnline: isNowOnline,
          networkQuality: networkMonitor.getNetworkState().qualityScore
        };
        
        // Track online/offline transitions
        if (!wasOnline && isNowOnline) {
          updates.lastOnlineAt = networkInfo.timestamp;
          
          // Schedule sync when coming back online
          if (state.preferences.autoSync) {
            setTimeout(() => get().startSync(), 1000);
          }
        }
        
        // Auto-adjust sync interval based on network quality
        if (isNowOnline) {
          get().adjustSyncInterval(updates.networkQuality!);
        }
        
        return { ...state, ...updates };
      });
    },
    
    setOnlineStatus: (isOnline: boolean) => {
      set((state) => ({
        ...state,
        isOnline,
        lastOnlineAt: isOnline ? Date.now() : state.lastOnlineAt
      }));
    },
    
    // Sync operation management
    startSync: async (force = false) => {
      const state = get();
      
      if (!force && (!state.isOnline || state.syncStatus === SyncStatus.SYNCING)) {
        return;
      }
      
      try {
        await syncProcessor.startSync(force);
      } catch (error) {
        console.error('Failed to start sync:', error);
        set((state) => ({
          ...state,
          stats: {
            ...state.stats,
            lastError: error instanceof Error ? error.message : 'Unknown error'
          }
        }));
      }
    },
    
    pauseSync: () => {
      syncProcessor.pauseSync();
      set((state) => ({ ...state, syncStatus: SyncStatus.PAUSED }));
    },
    
    resumeSync: async () => {
      await syncProcessor.resumeSync();
    },
    
    stopSync: () => {
      syncProcessor.stopSync();
      set((state) => ({
        ...state,
        syncStatus: SyncStatus.IDLE,
        syncProgress: initialState.syncProgress
      }));
    },
    
    updateSyncProgress: (progress: SyncProgress) => {
      set((state) => ({ ...state, syncProgress: progress }));
    },
    
    // Offline mode management
    enableOfflineMode: () => {
      set((state) => ({ ...state, isOfflineMode: true }));
    },
    
    disableOfflineMode: () => {
      set((state) => ({ ...state, isOfflineMode: false }));
    },
    
    addOfflineChange: (type: string, data: any): string => {
      const changeId = `change_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      
      set((state) => ({
        ...state,
        offlineChanges: [
          ...state.offlineChanges,
          {
            id: changeId,
            type,
            data,
            timestamp: Date.now(),
            synced: false
          }
        ]
      }));
      
      return changeId;
    },
    
    markChangeAsSynced: (changeId: string) => {
      set((state) => ({
        ...state,
        offlineChanges: state.offlineChanges.map(change =>
          change.id === changeId ? { ...change, synced: true } : change
        )
      }));
    },
    
    clearOfflineChanges: () => {
      set((state) => ({ ...state, offlineChanges: [] }));
    },
    
    // Conflict management
    addConflict: (conflict: ConflictData) => {
      set((state) => ({
        ...state,
        activeConflicts: [...state.activeConflicts, conflict]
      }));
    },
    
    resolveConflict: (conflictId: string, resolution: ResolutionResult) => {
      set((state) => {
        const conflict = state.activeConflicts.find(c => c.entityId === conflictId);
        
        if (!conflict) return state;
        
        return {
          ...state,
          activeConflicts: state.activeConflicts.filter(c => c.entityId !== conflictId),
          resolvedConflicts: [
            ...state.resolvedConflicts,
            {
              conflict,
              resolution,
              timestamp: Date.now()
            }
          ],
          stats: {
            ...state.stats,
            totalConflicts: state.stats.totalConflicts + 1
          }
        };
      });
    },
    
    clearConflicts: () => {
      set((state) => ({
        ...state,
        activeConflicts: [],
        resolvedConflicts: []
      }));
    },
    
    // Sync scheduling
    scheduleNextSync: (delay?: number) => {
      const state = get();
      const syncDelay = delay || state.scheduledSync.interval * state.scheduledSync.backoffMultiplier;
      
      set((currentState) => ({
        ...currentState,
        scheduledSync: {
          ...currentState.scheduledSync,
          nextSyncAt: Date.now() + syncDelay
        }
      }));
      
      // Clear any existing timeout
      get().clearScheduledSync();
      
      // Schedule the sync
      setTimeout(() => {
        const currentState = get();
        if (currentState.preferences.autoSync && currentState.isOnline) {
          currentState.startSync();
        }
      }, syncDelay);
    },
    
    clearScheduledSync: () => {
      // This would clear any existing setTimeout, but since we can't store the timeout ID
      // in Zustand state, we rely on the condition check in the setTimeout callback
      set((state) => ({
        ...state,
        scheduledSync: {
          ...state.scheduledSync,
          nextSyncAt: 0
        }
      }));
    },
    
    adjustSyncInterval: (networkQuality: number) => {
      set((state) => {
        let interval = state.scheduledSync.interval;
        let backoffMultiplier = 1;
        
        // Adjust based on network quality
        if (networkQuality > 80) {
          interval = 15000; // 15 seconds for excellent connection
        } else if (networkQuality > 60) {
          interval = 30000; // 30 seconds for good connection
        } else if (networkQuality > 40) {
          interval = 60000; // 1 minute for fair connection
        } else {
          interval = 120000; // 2 minutes for poor connection
          backoffMultiplier = 2;
        }
        
        return {
          ...state,
          scheduledSync: {
            ...state.scheduledSync,
            interval,
            backoffMultiplier
          }
        };
      });
    },
    
    // Statistics
    recordSyncResult: (results: SyncResult[]) => {
      set((state) => {
        const successful = results.filter(r => r.success).length;
        const failed = results.filter(r => !r.success).length;
        const totalDuration = results.reduce((sum, r) => sum + r.duration, 0);
        const avgDuration = results.length > 0 ? totalDuration / results.length : 0;
        
        return {
          ...state,
          lastSyncAt: Date.now(),
          stats: {
            ...state.stats,
            totalSynced: state.stats.totalSynced + successful,
            totalFailed: state.stats.totalFailed + failed,
            averageSyncTime: (state.stats.averageSyncTime + avgDuration) / 2,
            lastError: failed > 0 ? results.find(r => !r.success)?.error || null : null
          }
        };
      });
    },
    
    resetStats: () => {
      set((state) => ({
        ...state,
        stats: initialState.stats
      }));
    },
    
    // Preferences
    setAutoSync: (enabled: boolean) => {
      set((state) => ({
        ...state,
        preferences: { ...state.preferences, autoSync: enabled }
      }));
    },
    
    setSyncOnGoodConnection: (enabled: boolean) => {
      set((state) => ({
        ...state,
        preferences: { ...state.preferences, syncOnGoodConnection: enabled }
      }));
    },
    
    setShowOfflineIndicator: (show: boolean) => {
      set((state) => ({
        ...state,
        preferences: { ...state.preferences, showOfflineIndicator: show }
      }));
    },
    
    setShowSyncProgress: (show: boolean) => {
      set((state) => ({
        ...state,
        preferences: { ...state.preferences, showSyncProgress: show }
      }));
    },
    
    setConfirmConflictResolutions: (confirm: boolean) => {
      set((state) => ({
        ...state,
        preferences: { ...state.preferences, confirmConflictResolutions: confirm }
      }));
    },
    
    // Actions
    queueAttendanceUpdate: async (studentId: number, status: string, sessionId: string): Promise<string> => {
      const operationData = {
        student_id: studentId,
        status,
        session_id: sessionId,
        timestamp: new Date().toISOString(),
        updated_by: 'offline_user'
      };
      
      // Add to offline changes
      const changeId = get().addOfflineChange('attendance_update', operationData);
      
      // Queue for sync
      const syncId = await syncProcessor.queueOperation(
        'status_update',
        `/api/attendance/${sessionId}/students/${studentId}`,
        'PATCH',
        operationData,
        { priority: 3 } // High priority for attendance updates
      );
      
      return syncId;
    },
    
    queueBulkOperation: async (operations: any[]): Promise<string> => {
      const operationData = {
        operations,
        timestamp: new Date().toISOString(),
        type: 'bulk_update'
      };
      
      // Add to offline changes
      const changeId = get().addOfflineChange('bulk_operation', operationData);
      
      // Queue for sync
      const syncId = await syncProcessor.queueOperation(
        'bulk_operation',
        '/api/attendance/bulk',
        'POST',
        operationData,
        { priority: 2 } // Medium priority for bulk operations
      );
      
      return syncId;
    },
    
    processPendingChanges: async (): Promise<void> => {
      const state = get();
      
      if (!state.isOnline || state.offlineChanges.length === 0) {
        return;
      }
      
      const unsyncedChanges = state.offlineChanges.filter(change => !change.synced);
      
      for (const change of unsyncedChanges) {
        try {
          // Convert offline change to sync operation
          await syncProcessor.queueOperation(
            change.type as any,
            `/api/sync/${change.type}`,
            'POST',
            change.data
          );
          
          // Mark as queued for sync
          get().markChangeAsSynced(change.id);
          
        } catch (error) {
          console.error('Failed to queue offline change:', error);
        }
      }
    },
    
    handleConflictResolution: async (conflict: ConflictData): Promise<ResolutionResult> => {
      const state = get();
      
      // Add to active conflicts if not already present
      if (!state.activeConflicts.some(c => c.entityId === conflict.entityId)) {
        get().addConflict(conflict);
      }
      
      try {
        // Resolve the conflict
        const resolution = await conflictResolver.resolveConflict(conflict);
        
        // If requires user input and preferences say to confirm, handle accordingly
        if (resolution.requiresUserInput && state.preferences.confirmConflictResolutions) {
          // For now, we'll resolve automatically but log the requirement
          console.warn('Conflict requires user input but auto-resolving:', conflict);
        }
        
        // Record the resolution
        get().resolveConflict(conflict.entityId, resolution);
        
        return resolution;
        
      } catch (error) {
        console.error('Failed to resolve conflict:', error);
        
        // Return a default resolution
        return {
          strategy: 'reject_changes' as any,
          resolvedData: conflict.serverVersion,
          requiresUserInput: true,
          conflicts: [],
          confidence: 0,
          explanation: `Failed to resolve: ${error instanceof Error ? error.message : 'Unknown error'}`
        };
      }
    }
  }))
);

// Initialize the store with network monitoring
if (typeof window !== 'undefined') {
  const store = useSyncStore.getState();
  
  // Set up network monitoring
  networkMonitor.onNetworkChange((networkInfo) => {
    store.updateNetworkState(networkInfo);
  });
  
  // Set up sync processor event handlers
  syncProcessor.onProgress((progress) => {
    store.updateSyncProgress(progress);
  });
  
  syncProcessor.onComplete((results) => {
    store.recordSyncResult(results);
  });
  
  syncProcessor.onError((error) => {
    useSyncStore.setState((state) => ({
      ...state,
      stats: {
        ...state.stats,
        lastError: error
      }
    }));
  });
  
  syncProcessor.onConflict(async (operation, conflictData) => {
    const conflict: ConflictData = {
      type: 'attendance_status' as any,
      entityId: operation.id,
      localVersion: operation.data,
      serverVersion: conflictData,
      timestamp: Date.now(),
      conflictFields: Object.keys(conflictData || {})
    };
    
    return store.handleConflictResolution(conflict);
  });
  
  // Start network monitoring
  networkMonitor.startMonitoring();
  
  // Initial network state check
  networkMonitor.forceUpdate().then((networkInfo) => {
    store.updateNetworkState(networkInfo);
  });
}

// Selectors for easy access to specific parts of sync state
export const useNetworkState = () => {
  return useSyncStore((state) => ({
    isOnline: state.isOnline,
    networkStatus: state.networkStatus,
    networkQuality: state.networkQuality,
    lastOnlineAt: state.lastOnlineAt
  }));
};

export const useSyncStatus = () => {
  return useSyncStore((state) => ({
    status: state.syncStatus,
    progress: state.syncProgress,
    pendingOperations: state.pendingOperations,
    failedOperations: state.failedOperations,
    lastSyncAt: state.lastSyncAt
  }));
};

export const useOfflineState = () => {
  return useSyncStore((state) => ({
    isOfflineMode: state.isOfflineMode,
    offlineChanges: state.offlineChanges,
    unsyncedChanges: state.offlineChanges.filter(c => !c.synced).length
  }));
};

export const useConflictState = () => {
  return useSyncStore((state) => ({
    activeConflicts: state.activeConflicts,
    resolvedConflicts: state.resolvedConflicts,
    hasConflicts: state.activeConflicts.length > 0
  }));
};

export const useSyncStats = () => {
  return useSyncStore((state) => state.stats);
};

export const useSyncPreferences = () => {
  return useSyncStore((state) => state.preferences);
};

export default useSyncStore;