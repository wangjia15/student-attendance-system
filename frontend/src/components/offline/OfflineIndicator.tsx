/**
 * Offline Indicator Component
 * 
 * Provides clear visual feedback about connection status and sync state:
 * - Connection status indicator with network quality
 * - Sync progress display with details
 * - Offline mode notifications
 * - Conflict resolution prompts
 * - Bandwidth optimization status
 */

import React, { useState, useEffect } from 'react';
import { 
  useNetworkState, 
  useSyncStatus, 
  useOfflineState, 
  useConflictState,
  useSyncStore 
} from '../../store/sync';
import { NetworkStatus } from '../../services/offline/networkMonitor';
import { SyncStatus } from '../../services/offline/syncProcessor';
import progressiveSync from '../../services/offline/progressiveSync';

interface OfflineIndicatorProps {
  showDetails?: boolean;
  position?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left';
  compact?: boolean;
  className?: string;
}

const OfflineIndicator: React.FC<OfflineIndicatorProps> = ({
  showDetails = false,
  position = 'top-right',
  compact = false,
  className = ''
}) => {
  const { isOnline, networkStatus, networkQuality, lastOnlineAt } = useNetworkState();
  const { status: syncStatus, progress, pendingOperations, lastSyncAt } = useSyncStatus();
  const { isOfflineMode, unsyncedChanges } = useOfflineState();
  const { hasConflicts, activeConflicts } = useConflictState();
  
  const [showDetails, setShowDetails] = useState(showDetails);
  const [progressiveProgress, setProgressiveProgress] = useState<any>(null);
  
  useEffect(() => {
    // Listen to progressive sync updates
    const unsubscribe = progressiveSync.onProgress((progress) => {
      setProgressiveProgress(progress);
    });
    
    return unsubscribe;
  }, []);
  
  const getConnectionIcon = () => {
    if (!isOnline) return '🔴';
    
    switch (networkStatus) {
      case NetworkStatus.EXCELLENT:
        return '🟢';
      case NetworkStatus.GOOD:
        return '🟡';
      case NetworkStatus.POOR:
        return '🟠';
      default:
        return '⚪';
    }
  };
  
  const getConnectionText = () => {
    if (!isOnline) return 'Offline';
    
    switch (networkStatus) {
      case NetworkStatus.EXCELLENT:
        return 'Excellent';
      case NetworkStatus.GOOD:
        return 'Good';
      case NetworkStatus.POOR:
        return 'Poor';
      default:
        return 'Unknown';
    }
  };
  
  const getSyncIcon = () => {
    switch (syncStatus) {
      case SyncStatus.SYNCING:
        return '🔄';
      case SyncStatus.PAUSED:
        return '⏸️';
      case SyncStatus.ERROR:
        return '❌';
      default:
        return '✅';
    }
  };
  
  const formatTime = (timestamp: number) => {
    if (!timestamp) return 'Never';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
  };
  
  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${Math.round(ms / 1000)}s`;
    return `${Math.round(ms / 60000)}m`;
  };
  
  const positionClasses = {
    'top-right': 'top-4 right-4',
    'top-left': 'top-4 left-4',
    'bottom-right': 'bottom-4 right-4',
    'bottom-left': 'bottom-4 left-4'
  };
  
  if (compact) {
    return (
      <div className={`fixed ${positionClasses[position]} z-50 ${className}`}>
        <div 
          className="flex items-center space-x-1 bg-white dark:bg-gray-800 rounded-full px-3 py-1 shadow-lg border cursor-pointer transition-all hover:shadow-xl"
          onClick={() => setShowDetails(!showDetails)}
        >
          <span className="text-sm">{getConnectionIcon()}</span>
          {unsyncedChanges > 0 && (
            <span className="bg-blue-500 text-white text-xs rounded-full px-1.5 py-0.5 min-w-[1.5rem] text-center">
              {unsyncedChanges}
            </span>
          )}
          {hasConflicts && (
            <span className="text-orange-500 text-sm">⚠️</span>
          )}
        </div>
        
        {showDetails && (
          <div className="absolute top-full mt-2 right-0 w-80 bg-white dark:bg-gray-800 rounded-lg shadow-xl border p-4 text-sm">
            <CompactDetails 
              isOnline={isOnline}
              networkStatus={networkStatus}
              networkQuality={networkQuality}
              syncStatus={syncStatus}
              progress={progress}
              unsyncedChanges={unsyncedChanges}
              hasConflicts={hasConflicts}
              activeConflicts={activeConflicts}
              progressiveProgress={progressiveProgress}
            />
          </div>
        )}
      </div>
    );
  }
  
  return (
    <div className={`fixed ${positionClasses[position]} z-50 w-72 ${className}`}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl border p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 dark:text-white">
            Connection Status
          </h3>
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            {showDetails ? '▼' : '▶'}
          </button>
        </div>
        
        <div className="space-y-3">
          {/* Connection Status */}
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="text-lg">{getConnectionIcon()}</span>
              <span className="text-sm text-gray-700 dark:text-gray-300">
                {getConnectionText()}
              </span>
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400">
              Quality: {networkQuality}%
            </div>
          </div>
          
          {/* Sync Status */}
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <span className="text-lg">{getSyncIcon()}</span>
              <span className="text-sm text-gray-700 dark:text-gray-300">
                {syncStatus === SyncStatus.SYNCING ? 'Syncing...' : 
                 syncStatus === SyncStatus.PAUSED ? 'Paused' :
                 syncStatus === SyncStatus.ERROR ? 'Error' : 'Idle'}
              </span>
            </div>
            {progress.total > 0 && (
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {progress.completed}/{progress.total}
              </div>
            )}
          </div>
          
          {/* Unsynced Changes */}
          {unsyncedChanges > 0 && (
            <div className="flex items-center justify-between p-2 bg-blue-50 dark:bg-blue-900/20 rounded">
              <span className="text-sm text-blue-700 dark:text-blue-300">
                Unsynced changes
              </span>
              <span className="bg-blue-500 text-white text-xs rounded-full px-2 py-1">
                {unsyncedChanges}
              </span>
            </div>
          )}
          
          {/* Conflicts */}
          {hasConflicts && (
            <div className="flex items-center justify-between p-2 bg-orange-50 dark:bg-orange-900/20 rounded">
              <span className="text-sm text-orange-700 dark:text-orange-300">
                Conflicts need attention
              </span>
              <span className="bg-orange-500 text-white text-xs rounded-full px-2 py-1">
                {activeConflicts.length}
              </span>
            </div>
          )}
          
          {/* Progressive Sync Progress */}
          {progressiveProgress && progressiveProgress.totalChunks > 0 && (
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-gray-600 dark:text-gray-400">
                <span>Sync Progress</span>
                <span>{Math.round((progressiveProgress.completedChunks / progressiveProgress.totalChunks) * 100)}%</span>
              </div>
              <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                <div 
                  className="bg-blue-500 h-2 rounded-full transition-all"
                  style={{ 
                    width: `${(progressiveProgress.completedChunks / progressiveProgress.totalChunks) * 100}%` 
                  }}
                />
              </div>
              {progressiveProgress.estimatedTimeRemaining > 0 && (
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  {formatDuration(progressiveProgress.estimatedTimeRemaining)} remaining
                </div>
              )}
            </div>
          )}
          
          {showDetails && (
            <DetailedInfo 
              isOnline={isOnline}
              networkStatus={networkStatus}
              networkQuality={networkQuality}
              lastOnlineAt={lastOnlineAt}
              syncStatus={syncStatus}
              progress={progress}
              lastSyncAt={lastSyncAt}
              pendingOperations={pendingOperations}
              isOfflineMode={isOfflineMode}
              progressiveProgress={progressiveProgress}
            />
          )}
        </div>
      </div>
    </div>
  );
};

interface CompactDetailsProps {
  isOnline: boolean;
  networkStatus: NetworkStatus;
  networkQuality: number;
  syncStatus: SyncStatus;
  progress: any;
  unsyncedChanges: number;
  hasConflicts: boolean;
  activeConflicts: any[];
  progressiveProgress: any;
}

const CompactDetails: React.FC<CompactDetailsProps> = ({
  isOnline,
  networkStatus,
  networkQuality,
  syncStatus,
  progress,
  unsyncedChanges,
  hasConflicts,
  activeConflicts,
  progressiveProgress
}) => {
  return (
    <div className="space-y-3">
      <div>
        <div className="font-medium text-gray-900 dark:text-white mb-1">Connection</div>
        <div className="text-sm text-gray-600 dark:text-gray-400">
          Status: {isOnline ? 'Online' : 'Offline'}<br/>
          Quality: {networkQuality}% ({networkStatus})
        </div>
      </div>
      
      {syncStatus === SyncStatus.SYNCING && progress.total > 0 && (
        <div>
          <div className="font-medium text-gray-900 dark:text-white mb-1">Sync Progress</div>
          <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2 mb-1">
            <div 
              className="bg-blue-500 h-2 rounded-full"
              style={{ width: `${(progress.completed / progress.total) * 100}%` }}
            />
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            {progress.completed}/{progress.total} operations
          </div>
        </div>
      )}
      
      {unsyncedChanges > 0 && (
        <div>
          <div className="font-medium text-gray-900 dark:text-white mb-1">Pending</div>
          <div className="text-sm text-gray-600 dark:text-gray-400">
            {unsyncedChanges} unsynced changes
          </div>
        </div>
      )}
      
      {hasConflicts && (
        <div>
          <div className="font-medium text-gray-900 dark:text-white mb-1">Conflicts</div>
          <div className="text-sm text-gray-600 dark:text-gray-400">
            {activeConflicts.length} conflicts need resolution
          </div>
        </div>
      )}
    </div>
  );
};

interface DetailedInfoProps {
  isOnline: boolean;
  networkStatus: NetworkStatus;
  networkQuality: number;
  lastOnlineAt: number;
  syncStatus: SyncStatus;
  progress: any;
  lastSyncAt: number;
  pendingOperations: number;
  isOfflineMode: boolean;
  progressiveProgress: any;
}

const DetailedInfo: React.FC<DetailedInfoProps> = ({
  isOnline,
  networkStatus,
  networkQuality,
  lastOnlineAt,
  syncStatus,
  progress,
  lastSyncAt,
  pendingOperations,
  isOfflineMode,
  progressiveProgress
}) => {
  const formatTime = (timestamp: number) => {
    if (!timestamp) return 'Never';
    return new Date(timestamp).toLocaleString();
  };
  
  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };
  
  return (
    <div className="border-t pt-3 mt-3 space-y-2 text-xs text-gray-600 dark:text-gray-400">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <span className="font-medium">Last Online:</span><br/>
          {formatTime(lastOnlineAt)}
        </div>
        <div>
          <span className="font-medium">Last Sync:</span><br/>
          {formatTime(lastSyncAt)}
        </div>
      </div>
      
      {pendingOperations > 0 && (
        <div>
          <span className="font-medium">Pending Operations:</span> {pendingOperations}
        </div>
      )}
      
      {progressiveProgress && (
        <div className="space-y-1">
          <div className="font-medium">Progressive Sync:</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div>Speed: {formatBytes(progressiveProgress.currentSpeed)}/s</div>
            <div>Chunks: {progressiveProgress.completedChunks}/{progressiveProgress.totalChunks}</div>
            <div>Transferred: {formatBytes(progressiveProgress.bytesTransferred)}</div>
            <div>Total: {formatBytes(progressiveProgress.totalBytes)}</div>
          </div>
          
          {progressiveProgress.adaptiveMetrics && (
            <div className="pt-1 border-t">
              <div className="font-medium mb-1">Adaptive Metrics:</div>
              <div>Chunk Size: {progressiveProgress.adaptiveMetrics.optimalChunkSize} ops</div>
              <div>Network Usage: {Math.round(progressiveProgress.adaptiveMetrics.networkUtilization)}%</div>
              <div>Compression: {Math.round(progressiveProgress.adaptiveMetrics.compressionEfficiency * 100)}%</div>
            </div>
          )}
        </div>
      )}
      
      {isOfflineMode && (
        <div className="p-2 bg-yellow-50 dark:bg-yellow-900/20 rounded text-yellow-700 dark:text-yellow-300">
          Operating in offline mode
        </div>
      )}
    </div>
  );
};

export default OfflineIndicator;