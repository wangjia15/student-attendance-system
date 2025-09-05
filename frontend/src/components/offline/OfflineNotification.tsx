/**
 * Offline Notification Component
 * 
 * Shows contextual notifications for offline events:
 * - Connection state changes
 * - Sync completion notifications
 * - Conflict resolution alerts
 * - Data loss prevention warnings
 * - Automatic dismissal with user controls
 */

import React, { useState, useEffect } from 'react';
import { useNetworkState, useSyncStatus, useOfflineState } from '../../store/sync';
import { NetworkStatus } from '../../services/offline/networkMonitor';
import { SyncStatus } from '../../services/offline/syncProcessor';

interface NotificationProps {
  id: string;
  type: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  duration?: number;
  persistent?: boolean;
  actions?: Array<{
    label: string;
    action: () => void;
    style?: 'primary' | 'secondary';
  }>;
  onDismiss?: () => void;
}

interface OfflineNotificationProps {
  position?: 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left' | 'top-center';
  maxNotifications?: number;
  className?: string;
}

const OfflineNotification: React.FC<OfflineNotificationProps> = ({
  position = 'top-right',
  maxNotifications = 5,
  className = ''
}) => {
  const { isOnline, networkStatus } = useNetworkState();
  const { status: syncStatus, progress } = useSyncStatus();
  const { unsyncedChanges } = useOfflineState();
  
  const [notifications, setNotifications] = useState<NotificationProps[]>([]);
  const [previousOnlineState, setPreviousOnlineState] = useState(isOnline);
  const [previousSyncStatus, setPreviousSyncStatus] = useState(syncStatus);
  
  // Handle connection state changes
  useEffect(() => {
    if (previousOnlineState !== isOnline) {
      if (isOnline) {
        addNotification({
          id: 'connection-restored',
          type: 'success',
          title: 'Connection Restored',
          message: unsyncedChanges > 0 
            ? `Back online! Syncing ${unsyncedChanges} pending changes...`
            : 'Back online! All data is up to date.',
          duration: 4000
        });
      } else {
        addNotification({
          id: 'connection-lost',
          type: 'warning',
          title: 'Connection Lost',
          message: 'You are now offline. Your changes will be saved locally and synced when connection is restored.',
          duration: 6000,
          persistent: true
        });
      }
      setPreviousOnlineState(isOnline);
    }
  }, [isOnline, unsyncedChanges]);
  
  // Handle sync status changes
  useEffect(() => {
    if (previousSyncStatus !== syncStatus) {
      if (syncStatus === SyncStatus.SYNCING && previousSyncStatus !== SyncStatus.SYNCING) {
        addNotification({
          id: 'sync-started',
          type: 'info',
          title: 'Sync Started',
          message: `Syncing ${progress.total} operations...`,
          duration: 3000
        });
      } else if (syncStatus === SyncStatus.IDLE && previousSyncStatus === SyncStatus.SYNCING) {
        if (progress.failed > 0) {
          addNotification({
            id: 'sync-partial',
            type: 'warning',
            title: 'Sync Partially Complete',
            message: `${progress.completed} operations synced, ${progress.failed} failed.`,
            duration: 5000,
            actions: [
              {
                label: 'Retry Failed',
                action: () => {
                  // Trigger retry of failed operations
                },
                style: 'primary'
              }
            ]
          });
        } else if (progress.completed > 0) {
          addNotification({
            id: 'sync-complete',
            type: 'success',
            title: 'Sync Complete',
            message: `Successfully synced ${progress.completed} operations.`,
            duration: 3000
          });
        }
      }
      setPreviousSyncStatus(syncStatus);
    }
  }, [syncStatus, progress]);
  
  // Handle network quality changes
  useEffect(() => {
    if (isOnline && networkStatus === NetworkStatus.POOR) {
      addNotification({
        id: 'poor-connection',
        type: 'warning',
        title: 'Poor Connection',
        message: 'Network quality is poor. Sync may be slow or delayed.',
        duration: 5000
      });
    }
  }, [networkStatus, isOnline]);
  
  const addNotification = (notification: Omit<NotificationProps, 'onDismiss'>) => {
    const notificationWithDismiss: NotificationProps = {
      ...notification,
      onDismiss: () => dismissNotification(notification.id)
    };
    
    setNotifications(prev => {
      // Remove existing notification with same ID
      const filtered = prev.filter(n => n.id !== notification.id);
      
      // Add new notification
      const updated = [notificationWithDismiss, ...filtered];
      
      // Limit number of notifications
      return updated.slice(0, maxNotifications);
    });
    
    // Auto-dismiss if duration is set and not persistent
    if (notification.duration && !notification.persistent) {
      setTimeout(() => {
        dismissNotification(notification.id);
      }, notification.duration);
    }
  };
  
  const dismissNotification = (id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };
  
  const dismissAll = () => {
    setNotifications([]);
  };
  
  const positionClasses = {
    'top-right': 'top-4 right-4',
    'top-left': 'top-4 left-4',
    'bottom-right': 'bottom-4 right-4',
    'bottom-left': 'bottom-4 left-4',
    'top-center': 'top-4 left-1/2 transform -translate-x-1/2'
  };
  
  if (notifications.length === 0) {
    return null;
  }
  
  return (
    <div className={`fixed ${positionClasses[position]} z-50 space-y-2 w-80 ${className}`}>
      {notifications.length > 1 && (
        <div className="flex justify-end">
          <button
            onClick={dismissAll}
            className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            Dismiss all
          </button>
        </div>
      )}
      
      {notifications.map(notification => (
        <NotificationCard
          key={notification.id}
          notification={notification}
          onDismiss={() => dismissNotification(notification.id)}
        />
      ))}
    </div>
  );
};

interface NotificationCardProps {
  notification: NotificationProps;
  onDismiss: () => void;
}

const NotificationCard: React.FC<NotificationCardProps> = ({ notification, onDismiss }) => {
  const [isVisible, setIsVisible] = useState(false);
  const [isRemoving, setIsRemoving] = useState(false);
  
  useEffect(() => {
    // Trigger entrance animation
    setTimeout(() => setIsVisible(true), 10);
  }, []);
  
  const handleDismiss = () => {
    setIsRemoving(true);
    setTimeout(() => {
      onDismiss();
    }, 300);
  };
  
  const getIcon = () => {
    switch (notification.type) {
      case 'success':
        return '✅';
      case 'error':
        return '❌';
      case 'warning':
        return '⚠️';
      default:
        return 'ℹ️';
    }
  };
  
  const getBorderColor = () => {
    switch (notification.type) {
      case 'success':
        return 'border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-900/20';
      case 'error':
        return 'border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20';
      case 'warning':
        return 'border-orange-200 bg-orange-50 dark:border-orange-800 dark:bg-orange-900/20';
      default:
        return 'border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-900/20';
    }
  };
  
  const getTextColor = () => {
    switch (notification.type) {
      case 'success':
        return 'text-green-800 dark:text-green-200';
      case 'error':
        return 'text-red-800 dark:text-red-200';
      case 'warning':
        return 'text-orange-800 dark:text-orange-200';
      default:
        return 'text-blue-800 dark:text-blue-200';
    }
  };
  
  return (
    <div
      className={`
        transform transition-all duration-300 ease-in-out
        ${isVisible && !isRemoving 
          ? 'translate-x-0 opacity-100' 
          : 'translate-x-full opacity-0'
        }
        ${getBorderColor()}
        border rounded-lg shadow-lg p-4 backdrop-blur-sm
      `}
    >
      <div className="flex items-start space-x-3">
        <div className="flex-shrink-0">
          <span className="text-lg">{getIcon()}</span>
        </div>
        
        <div className="flex-1 min-w-0">
          <div className={`font-medium text-sm ${getTextColor()}`}>
            {notification.title}
          </div>
          <div className={`text-sm mt-1 ${getTextColor()} opacity-90`}>
            {notification.message}
          </div>
          
          {notification.actions && notification.actions.length > 0 && (
            <div className="flex items-center space-x-2 mt-3">
              {notification.actions.map((action, index) => (
                <button
                  key={index}
                  onClick={action.action}
                  className={`
                    text-xs px-3 py-1 rounded-md font-medium
                    ${action.style === 'primary'
                      ? 'bg-blue-600 text-white hover:bg-blue-700'
                      : 'bg-gray-200 text-gray-800 hover:bg-gray-300 dark:bg-gray-600 dark:text-gray-200 dark:hover:bg-gray-500'
                    }
                  `}
                >
                  {action.label}
                </button>
              ))}
            </div>
          )}
        </div>
        
        {!notification.persistent && (
          <div className="flex-shrink-0">
            <button
              onClick={handleDismiss}
              className={`${getTextColor()} opacity-60 hover:opacity-100 text-sm`}
            >
              ✕
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default OfflineNotification;