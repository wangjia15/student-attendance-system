/**
 * Connection Status Indicator Component
 * 
 * Displays the current real-time connection status with visual indicators,
 * connection statistics, and reconnection controls.
 */

import React, { useState } from 'react';
import { ConnectionState } from '../services/websocket';
import { useConnectionState, useRealtimeStore } from '../store/realtime';

export interface ConnectionStatusIndicatorProps {
  /** Show detailed connection statistics */
  showStats?: boolean;
  /** Show reconnection controls */
  showControls?: boolean;
  /** Compact mode for smaller displays */
  compact?: boolean;
  /** Custom class name */
  className?: string;
  /** Callback when manual reconnect is triggered */
  onReconnect?: () => void;
}

const ConnectionStatusIndicator: React.FC<ConnectionStatusIndicatorProps> = ({
  showStats = false,
  showControls = false,
  compact = false,
  className = '',
  onReconnect
}) => {
  const [showDetails, setShowDetails] = useState(false);
  const { connectionState, isConnected, connectionError, connectionStats } = useConnectionState();
  const realtimeStore = useRealtimeStore();
  
  // Get status display info
  const getStatusInfo = () => {
    switch (connectionState) {
      case ConnectionState.DISCONNECTED:
        return {
          text: 'Offline',
          icon: '❌',
          color: '#dc3545',
          bgColor: '#f8d7da',
          borderColor: '#f5c6cb'
        };
      case ConnectionState.CONNECTING:
        return {
          text: 'Connecting...',
          icon: '⏳',
          color: '#856404',
          bgColor: '#fff3cd',
          borderColor: '#ffeaa7'
        };
      case ConnectionState.CONNECTED:
        return {
          text: 'Connected',
          icon: '🔗',
          color: '#0c5460',
          bgColor: '#d1ecf1',
          borderColor: '#bee5eb'
        };
      case ConnectionState.AUTHENTICATING:
        return {
          text: 'Authenticating...',
          icon: '🔐',
          color: '#856404',
          bgColor: '#fff3cd',
          borderColor: '#ffeaa7'
        };
      case ConnectionState.AUTHENTICATED:
        return {
          text: 'Live Updates Active',
          icon: '✅',
          color: '#155724',
          bgColor: '#d4edda',
          borderColor: '#c3e6cb'
        };
      case ConnectionState.ERROR:
        return {
          text: 'Connection Error',
          icon: '⚠️',
          color: '#721c24',
          bgColor: '#f8d7da',
          borderColor: '#f5c6cb'
        };
      default:
        return {
          text: 'Unknown',
          icon: '❓',
          color: '#6c757d',
          bgColor: '#f8f9fa',
          borderColor: '#dee2e6'
        };
    }
  };

  const statusInfo = getStatusInfo();
  
  const handleReconnect = () => {
    if (onReconnect) {
      onReconnect();
    }
  };
  
  const formatUptime = (ms: number) => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    
    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`;
    } else if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`;
    } else {
      return `${seconds}s`;
    }
  };

  if (compact) {
    return (
      <div 
        className={`connection-status-compact ${className}`}
        title={`${statusInfo.text}${connectionError ? ` - ${connectionError}` : ''}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          padding: '4px 8px',
          borderRadius: '12px',
          fontSize: '12px',
          backgroundColor: statusInfo.bgColor,
          color: statusInfo.color,
          border: `1px solid ${statusInfo.borderColor}`,
        }}
      >
        <span style={{ marginRight: '4px' }}>{statusInfo.icon}</span>
        {isConnected && connectionStats.averageLatency > 0 && (
          <span>{Math.round(connectionStats.averageLatency)}ms</span>
        )}
      </div>
    );
  }

  return (
    <div className={`connection-status-indicator ${className}`}>
      <div 
        className="status-main"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          borderRadius: '8px',
          backgroundColor: statusInfo.bgColor,
          color: statusInfo.color,
          border: `1px solid ${statusInfo.borderColor}`,
          marginBottom: showStats || showDetails ? '8px' : '0'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="status-indicator" style={{ fontSize: '16px' }}>
            {statusInfo.icon}
          </span>
          <span className="status-text" style={{ fontWeight: '500' }}>
            {statusInfo.text}
          </span>
          {connectionError && (
            <span 
              className="error-icon" 
              title={connectionError}
              style={{ color: '#dc3545', cursor: 'help' }}
            >
              ⚠️
            </span>
          )}
        </div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {isConnected && connectionStats.averageLatency > 0 && (
            <span style={{ fontSize: '12px', opacity: 0.7 }}>
              {Math.round(connectionStats.averageLatency)}ms
            </span>
          )}
          
          {(showStats || showControls) && (
            <button
              onClick={() => setShowDetails(!showDetails)}
              style={{
                background: 'none',
                border: 'none',
                color: 'inherit',
                cursor: 'pointer',
                fontSize: '12px',
                opacity: 0.7
              }}
            >
              {showDetails ? '▲' : '▼'}
            </button>
          )}
        </div>
      </div>

      {showDetails && (
        <div 
          className="status-details"
          style={{
            padding: '12px',
            backgroundColor: 'white',
            border: '1px solid #dee2e6',
            borderRadius: '8px',
            fontSize: '12px'
          }}
        >
          {showStats && (
            <div className="connection-stats" style={{ marginBottom: showControls ? '12px' : '0' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
                <div>
                  <strong>Uptime:</strong> {formatUptime(connectionStats.uptime)}
                </div>
                <div>
                  <strong>Messages:</strong> {connectionStats.messagesReceived + connectionStats.messagesSent}
                </div>
                <div>
                  <strong>Reconnects:</strong> {connectionStats.reconnectionCount}
                </div>
                <div>
                  <strong>Errors:</strong> {connectionStats.errorCount}
                </div>
              </div>
              {isConnected && (
                <div style={{ marginTop: '8px', color: '#28a745' }}>
                  ✅ Connection healthy
                </div>
              )}
            </div>
          )}

          {showControls && (
            <div className="connection-controls">
              <button
                onClick={handleReconnect}
                disabled={connectionState === ConnectionState.CONNECTING}
                style={{
                  padding: '6px 12px',
                  borderRadius: '4px',
                  border: '1px solid #007bff',
                  backgroundColor: 'white',
                  color: '#007bff',
                  cursor: connectionState === ConnectionState.CONNECTING ? 'not-allowed' : 'pointer',
                  fontSize: '12px',
                  marginRight: '8px',
                  opacity: connectionState === ConnectionState.CONNECTING ? 0.5 : 1
                }}
              >
                {connectionState === ConnectionState.CONNECTING ? 'Reconnecting...' : 'Reconnect'}
              </button>
              
              <button
                onClick={() => realtimeStore.setShowConnectionIndicator(!realtimeStore.ui.showConnectionIndicator)}
                style={{
                  padding: '6px 12px',
                  borderRadius: '4px',
                  border: '1px solid #6c757d',
                  backgroundColor: 'white',
                  color: '#6c757d',
                  cursor: 'pointer',
                  fontSize: '12px'
                }}
              >
                {realtimeStore.ui.showConnectionIndicator ? 'Hide' : 'Show'} Indicator
              </button>
            </div>
          )}
          
          {connectionError && (
            <div 
              style={{
                marginTop: '8px',
                padding: '8px',
                backgroundColor: '#f8d7da',
                color: '#721c24',
                borderRadius: '4px',
                fontSize: '11px'
              }}
            >
              <strong>Error:</strong> {connectionError}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ConnectionStatusIndicator;