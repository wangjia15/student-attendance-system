import React, { useState, useEffect, useMemo } from 'react';
import { ClassSessionResponse } from '../types/api';
import { useClassSessionWebSocket } from '../hooks/useWebSocket';
import { realtimeService, RealtimeState, StudentJoinEvent } from '../services/realtime';
import { StudentJoinNotification } from './StudentJoinNotification';
import { QRCodeGenerator } from './QRCodeGenerator';
import { VerificationCodeDisplay } from './VerificationCodeDisplay';
import { getClassMembers } from '../services/api';
import { UserResponse } from '../types/api';
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
  const [enrolledStudents, setEnrolledStudents] = useState<UserResponse[]>([]);
  const [loadingStudents, setLoadingStudents] = useState(true);

  // WebSocket connection for live updates
  const wsConnection = useClassSessionWebSocket(
    session.id.toString(),
    session.jwt_token || '', // Use JWT token from session
    true // Enable connection
  );

  // Fetch enrolled students
  useEffect(() => {
    const loadEnrolledStudents = async () => {
      try {
        setLoadingStudents(true);
        const students = await getClassMembers(session.id);
        setEnrolledStudents(students);
      } catch (error) {
        console.error('Failed to load enrolled students:', error);
        setEnrolledStudents([]);
      } finally {
        setLoadingStudents(false);
      }
    };

    loadEnrolledStudents();
  }, [session.id]);

  // Subscribe to realtime service updates
  useEffect(() => {
    const unsubscribe = realtimeService.subscribe(setRealtimeState);
    
    // Initialize with current session stats using actual enrolled students count
    realtimeService.initialize({
      class_session_id: session.id,
      total_students: session.max_students || enrolledStudents.length,
      present_students: session.student_count || enrolledStudents.length,
      late_students: 0,
      absent_students: Math.max(0, (session.max_students || enrolledStudents.length) - (session.student_count || enrolledStudents.length)),
      last_updated: new Date().toISOString()
    });

    return unsubscribe;
  }, [session, enrolledStudents.length]);

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
          <div className="metric-value">{session.student_count || enrolledStudents.length}</div>
          <div className="metric-label">Enrolled Students</div>
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

      {/* QR Code and Verification Code Section */}
      <div className="attendance-codes-section">
        <div className="codes-grid">
          <div className="qr-code-panel">
            <QRCodeGenerator 
              session={session}
              onUpdate={onSessionUpdate}
              className="dashboard-qr"
            />
          </div>
          <div className="verification-code-panel">
            <VerificationCodeDisplay 
              session={session}
              onUpdate={onSessionUpdate}
              className="dashboard-verification"
            />
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

      {/* Enrolled Students List */}
      <div className="student-joins-section">
        <h3>
          Enrolled Students 
          <span className="join-count">({enrolledStudents.length})</span>
          {loadingStudents && <span className="loading-indicator">Loading...</span>}
        </h3>
        
        {enrolledStudents.length === 0 && !loadingStudents ? (
          <div className="empty-state">
            <span className="empty-icon">👥</span>
            <p>No students have joined yet</p>
            <p className="empty-subtitle">
              Share the QR code or verification code to get started
            </p>
          </div>
        ) : (
          <div className="joins-list">
            {enrolledStudents.map((student) => (
              <div 
                key={student.id} 
                className="join-item enrolled"
              >
                <div className="student-info">
                  <div className="student-name">{student.full_name || student.username}</div>
                  <div className="join-details">
                    <span className="student-email">{student.email}</span>
                    <span className="join-status-text">Enrolled</span>
                  </div>
                </div>
                <div className="join-status">
                  <span className="join-icon">✅</span>
                </div>
              </div>
            ))}
          </div>
        )}
        
        {filteredStudentJoins.length > 0 && (
          <>
            <h4 className="recent-joins-header">Recent Real-time Joins</h4>
            <div className="joins-list">
              {filteredStudentJoins.map((join) => (
                <div 
                  key={join.id} 
                  className={`join-item realtime ${join.isRecent ? 'recent' : ''}`}
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
          </>
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