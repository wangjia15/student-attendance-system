import React, { useState, useEffect, useMemo } from 'react';
import { ClassSessionResponse } from '../types/api';
import { useClassSessionWebSocket } from '../hooks/useWebSocket';
import { realtimeService, RealtimeState, StudentJoinEvent } from '../services/realtime';
import { StudentJoinNotification } from './StudentJoinNotification';
import './AttendanceDashboard.css';

interface AttendanceDashboardProps {
  session: ClassSessionResponse;
  onSessionUpdate?: (updates: Partial<ClassSessionResponse>) => void;
}

export const AttendanceDashboard: React.FC<AttendanceDashboardProps> = ({
  session,
  onSessionUpdate
}) => {
  const [realtimeState, setRealtimeState] = useState<RealtimeState>(realtimeService.getState());
  const [selectedTimeRange, setSelectedTimeRange] = useState<'1m' | '5m' | '15m' | 'all'>('5m');
  const [showNotifications, setShowNotifications] = useState(true);

  // WebSocket connection for live updates
  const wsConnection = useClassSessionWebSocket(
    session.id,
    session.jwt_token || '', // Use JWT token from session
    true // Enable connection
  );

  // Subscribe to realtime service updates
  useEffect(() => {
    const unsubscribe = realtimeService.subscribe(setRealtimeState);
    
    // Initialize with current session stats
    realtimeService.initialize({
      class_id: session.id,
      class_name: session.name,
      status: session.status,
      time_remaining_minutes: Math.max(0, 
        Math.floor((new Date(session.expires_at).getTime() - new Date().getTime()) / 60000)
      ),
      total_joins: session.total_joins,
      unique_students: session.unique_student_count,
      recent_joins: [],
      participation_rate: session.max_students ? 
        (session.unique_student_count / session.max_students) * 100 : undefined
    });

    return unsubscribe;
  }, [session]);

  // Process WebSocket messages
  useEffect(() => {
    if (wsConnection.studentJoins.length > 0) {
      const latestJoin = wsConnection.studentJoins[wsConnection.studentJoins.length - 1];
      realtimeService.processStudentJoin(latestJoin);
    }
  }, [wsConnection.studentJoins]);

  useEffect(() => {
    if (wsConnection.sessionUpdates.length > 0) {
      const latestUpdate = wsConnection.sessionUpdates[wsConnection.sessionUpdates.length - 1];
      realtimeService.processSessionUpdate(latestUpdate);
      
      // Update parent component with session changes
      if (onSessionUpdate) {
        onSessionUpdate(latestUpdate.data);
      }
    }
  }, [wsConnection.sessionUpdates, onSessionUpdate]);

  useEffect(() => {
    if (wsConnection.stats) {
      realtimeService.processStatsUpdate(wsConnection.stats);
    }
  }, [wsConnection.stats]);

  // Filter student joins by time range
  const filteredStudentJoins = useMemo(() => {
    if (selectedTimeRange === 'all') return realtimeState.studentJoins;
    
    const now = new Date();
    const timeRanges = {
      '1m': 60000,
      '5m': 300000,
      '15m': 900000
    };
    
    const cutoffTime = new Date(now.getTime() - timeRanges[selectedTimeRange]);
    return realtimeState.studentJoins.filter(join => join.joinedAt >= cutoffTime);
  }, [realtimeState.studentJoins, selectedTimeRange]);

  // Calculate time remaining
  const timeRemaining = useMemo(() => {
    if (!session.expires_at) return 'No expiration';
    
    const now = new Date();
    const expires = new Date(session.expires_at);
    
    // Check if expires_at is a valid date
    if (isNaN(expires.getTime())) {
      return 'Invalid date';
    }
    
    const diff = expires.getTime() - now.getTime();
    
    if (diff <= 0) return 'Expired';
    
    const minutes = Math.floor(diff / 60000);
    const seconds = Math.floor((diff % 60000) / 1000);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  }, [session.expires_at]);

  const connectionStatusColor = wsConnection.isConnected ? '#28a745' : 
                               wsConnection.isConnecting ? '#ffc107' : '#dc3545';

  return (
    <div className="attendance-dashboard">
      {/* Header */}
      <div className="dashboard-header">
        <div className="session-info">
          <h2>{session.name}</h2>
          {session.subject && <p className="subject">{session.subject}</p>}
          <div className="session-status">
            <span className={`status-badge ${session.status}`}>
              {session.status.toUpperCase()}
            </span>
            <span className="time-remaining">
              ⏰ {timeRemaining}
            </span>
          </div>
        </div>
        
        <div className="connection-status">
          <div className="connection-indicator">
            <div 
              className="status-dot" 
              style={{ backgroundColor: connectionStatusColor }}
            ></div>
            <span className="status-text">
              {wsConnection.isConnected ? 'Live' : 
               wsConnection.isConnecting ? 'Connecting...' : 'Disconnected'}
            </span>
          </div>
          {wsConnection.error && (
            <button 
              className="reconnect-button"
              onClick={wsConnection.reconnect}
            >
              Reconnect
            </button>
          )}
        </div>
      </div>

      {/* Metrics Cards */}
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-value">{realtimeState.sessionMetrics.totalJoins}</div>
          <div className="metric-label">Total Joins</div>
          <div className="metric-change">
            +{realtimeState.sessionMetrics.joinsPerMinute} last minute
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-value">{realtimeState.sessionMetrics.uniqueStudents}</div>
          <div className="metric-label">Unique Students</div>
          {session.max_students && (
            <div className="metric-change">
              of {session.max_students} expected
            </div>
          )}
        </div>

        {realtimeState.sessionMetrics.participationRate && (
          <div className="metric-card">
            <div className="metric-value">
              {Math.round(realtimeState.sessionMetrics.participationRate)}%
            </div>
            <div className="metric-label">Participation Rate</div>
            <div className={`metric-change ${
              realtimeState.sessionMetrics.participationRate >= 80 ? 'positive' : 
              realtimeState.sessionMetrics.participationRate >= 60 ? 'neutral' : 'negative'
            }`}>
              {realtimeState.sessionMetrics.participationRate >= 80 ? 'Excellent' :
               realtimeState.sessionMetrics.participationRate >= 60 ? 'Good' : 'Low'}
            </div>
          </div>
        )}

        <div className="metric-card">
          <div className="metric-value">
            {realtimeState.sessionMetrics.averageJoinTime.toFixed(1)}s
          </div>
          <div className="metric-label">Avg Join Time</div>
          <div className="metric-change">
            Peak: {realtimeState.sessionMetrics.peakJoinTime || 'N/A'}
          </div>
        </div>
      </div>

      {/* Time Range Filter */}
      <div className="dashboard-controls">
        <div className="time-range-filter">
          <span className="filter-label">Show joins from:</span>
          <div className="filter-buttons">
            {(['1m', '5m', '15m', 'all'] as const).map(range => (
              <button
                key={range}
                className={`filter-button ${selectedTimeRange === range ? 'active' : ''}`}
                onClick={() => setSelectedTimeRange(range)}
              >
                {range === 'all' ? 'All Time' : range}
              </button>
            ))}
          </div>
        </div>

        <div className="notifications-toggle">
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={showNotifications}
              onChange={(e) => setShowNotifications(e.target.checked)}
            />
            <span>Show Notifications</span>
          </label>
        </div>
      </div>

      {/* Student Joins List */}
      <div className="student-joins-section">
        <h3>
          Recent Student Joins 
          <span className="join-count">({filteredStudentJoins.length})</span>
        </h3>
        
        {filteredStudentJoins.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon">👥</span>
            <p>No students have joined yet</p>
            <p className="empty-subtitle">
              Share the QR code or verification code to get started
            </p>
          </div>
        ) : (
          <div className="joins-list">
            {filteredStudentJoins.map((join) => (
              <div 
                key={join.id} 
                className={`join-item ${join.isRecent ? 'recent' : ''}`}
              >
                <div className="student-info">
                  <div className="student-name">{join.studentName}</div>
                  <div className="join-details">
                    <span className="join-method">{join.joinMethod.replace('_', ' ')}</span>
                    <span className="join-time">
                      {join.joinedAt.toLocaleTimeString()}
                    </span>
                  </div>
                </div>
                <div className="join-status">
                  {join.isRecent && <span className="new-badge">New</span>}
                  <span className="join-icon">✅</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Notifications */}
      {showNotifications && (
        <StudentJoinNotification
          notifications={realtimeState.notifications}
          onDismiss={(id) => realtimeService.removeNotification(id)}
          onClearAll={() => realtimeService.clearNotifications()}
        />
      )}

      {/* WebSocket Error Display */}
      {wsConnection.error && (
        <div className="error-banner">
          <span className="error-icon">⚠️</span>
          <span className="error-message">{wsConnection.error}</span>
          <button 
            className="error-action"
            onClick={wsConnection.reconnect}
          >
            Retry
          </button>
        </div>
      )}
    </div>
  );
};