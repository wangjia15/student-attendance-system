import React, { useEffect, useState } from 'react';
import { NotificationEvent } from '../services/realtime';
import './StudentJoinNotification.css';

interface StudentJoinNotificationProps {
  notifications: NotificationEvent[];
  onDismiss: (id: string) => void;
  onClearAll: () => void;
  className?: string;
}

export const StudentJoinNotification: React.FC<StudentJoinNotificationProps> = ({
  notifications,
  onDismiss,
  onClearAll,
  className = ''
}) => {
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [lastNotificationId, setLastNotificationId] = useState<string>('');

  // Play sound for new notifications
  useEffect(() => {
    if (notifications.length > 0) {
      const latestNotification = notifications[0];
      
      // Only play sound for new notifications
      if (latestNotification.id !== lastNotificationId && soundEnabled) {
        playNotificationSound(latestNotification.type, latestNotification.priority);
        setLastNotificationId(latestNotification.id);
      }
    }
  }, [notifications, lastNotificationId, soundEnabled]);

  const playNotificationSound = (type: string, priority: string) => {
    // Use Web Audio API for better control
    if ('AudioContext' in window || 'webkitAudioContext' in window) {
      try {
        const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
        
        // Different tones for different notification types
        const frequencies = {
          student_join: [800, 1000], // Pleasant two-tone chime
          milestone: [600, 800, 1000], // Ascending celebration
          session_update: [700], // Single tone
          warning: [400, 300] // Descending warning
        };

        const freq = frequencies[type as keyof typeof frequencies] || [500];
        
        freq.forEach((frequency, index) => {
          setTimeout(() => {
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            oscillator.frequency.setValueAtTime(frequency, audioContext.currentTime);
            oscillator.type = 'sine';
            
            gainNode.gain.setValueAtTime(0, audioContext.currentTime);
            gainNode.gain.linearRampToValueAtTime(
              priority === 'high' ? 0.3 : 0.15, 
              audioContext.currentTime + 0.1
            );
            gainNode.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + 0.5);
            
            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.5);
          }, index * 200);
        });
      } catch (error) {
        console.warn('Could not play notification sound:', error);
      }
    }
  };

  const getNotificationIcon = (type: string): string => {
    const icons = {
      student_join: '👋',
      milestone: '🎉',
      session_update: '📝',
      warning: '⚠️'
    };
    return icons[type as keyof typeof icons] || '📱';
  };

  const getNotificationColor = (priority: string): string => {
    const colors = {
      high: '#dc3545',
      medium: '#007bff',
      low: '#28a745'
    };
    return colors[priority as keyof typeof colors] || '#6c757d';
  };

  const formatTimeAgo = (timestamp: Date): string => {
    const now = new Date();
    const diffMs = now.getTime() - timestamp.getTime();
    const diffSeconds = Math.floor(diffMs / 1000);
    const diffMinutes = Math.floor(diffSeconds / 60);

    if (diffSeconds < 30) return 'Just now';
    if (diffSeconds < 60) return `${diffSeconds}s ago`;
    if (diffMinutes < 60) return `${diffMinutes}m ago`;
    return timestamp.toLocaleTimeString();
  };

  if (notifications.length === 0) {
    return null;
  }

  return (
    <div className={`notification-container ${className}`}>
      <div className="notification-header">
        <h4>
          <span className="notification-icon">🔔</span>
          Live Notifications
          <span className="notification-count">({notifications.length})</span>
        </h4>
        
        <div className="notification-controls">
          <button
            className={`sound-toggle ${soundEnabled ? 'enabled' : 'disabled'}`}
            onClick={() => setSoundEnabled(!soundEnabled)}
            title={soundEnabled ? 'Disable sound' : 'Enable sound'}
          >
            {soundEnabled ? '🔊' : '🔇'}
          </button>
          
          {notifications.length > 1 && (
            <button
              className="clear-all-button"
              onClick={onClearAll}
              title="Clear all notifications"
            >
              Clear All
            </button>
          )}
        </div>
      </div>

      <div className="notification-list">
        {notifications.map((notification) => (
          <div
            key={notification.id}
            className={`notification-item priority-${notification.priority} type-${notification.type}`}
            style={{
              borderLeftColor: getNotificationColor(notification.priority)
            }}
          >
            <div className="notification-content">
              <div className="notification-main">
                <span className="notification-type-icon">
                  {getNotificationIcon(notification.type)}
                </span>
                <div className="notification-text">
                  <div className="notification-title">{notification.title}</div>
                  <div className="notification-message">{notification.message}</div>
                </div>
                <button
                  className="dismiss-button"
                  onClick={() => onDismiss(notification.id)}
                  aria-label="Dismiss notification"
                >
                  ×
                </button>
              </div>
              
              <div className="notification-footer">
                <span className="notification-time">
                  {formatTimeAgo(notification.timestamp)}
                </span>
                {notification.action && (
                  <button
                    className="notification-action"
                    onClick={notification.action.handler}
                  >
                    {notification.action.label}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Notification Summary for Screen Readers */}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {notifications.length > 0 && 
          `${notifications.length} notification${notifications.length === 1 ? '' : 's'} available. 
           Latest: ${notifications[0].title} - ${notifications[0].message}`
        }
      </div>
    </div>
  );
};