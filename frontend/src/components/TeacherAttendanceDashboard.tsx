import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { 
  AttendanceStatus, 
  ClassAttendanceStatus, 
  AttendanceRecord, 
  ClassAttendanceReport,
  AttendanceAlert,
  BulkAttendanceOperation 
} from '../types/attendance';
import { 
  ConnectionState,
  StudentJoinedData,
  AttendanceUpdateData,
  StatsUpdateData,
  SystemNotificationData
} from '../services/websocket';
import { useRealtime } from '../hooks/useRealtime';
import { useRealtimeStore, useConnectionState, useLiveStats, useNotifications, useActivityFeed } from '../store/realtime';
import useAttendanceStore from '../store/attendance';
import AttendanceOverride from './AttendanceOverride';
import AttendancePatterns from './AttendancePatterns';

interface TeacherAttendanceDashboardProps {
  classSessionId: number;
  teacherToken: string;
  autoRefreshInterval?: number;
  showPatterns?: boolean;
  showBulkOperations?: boolean;
}

interface DashboardAlert {
  id: string;
  type: 'success' | 'warning' | 'error' | 'info';
  message: string;
  timestamp: Date;
  dismissible: boolean;
}

const TeacherAttendanceDashboard: React.FC<TeacherAttendanceDashboardProps> = ({
  classSessionId,
  teacherToken,
  autoRefreshInterval = 30000,
  showPatterns = true,
  showBulkOperations = true
}) => {
  // Local state for UI
  const [classReport, setClassReport] = useState<ClassAttendanceReport | null>(null);
  const [selectedStudents, setSelectedStudents] = useState<Set<number>>(new Set());
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('table');
  const [filterStatus, setFilterStatus] = useState<AttendanceStatus | 'all'>('all');
  const [sortBy, setSortBy] = useState<'name' | 'status' | 'checkin_time'>('name');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [showOverrideModal, setShowOverrideModal] = useState(false);
  const [showPatternsModal, setShowPatternsModal] = useState(false);
  const [activeOperation, setActiveOperation] = useState<string | null>(null);
  
  // Real-time store state
  const { connectionState, isConnected, connectionError } = useConnectionState();
  const liveStats = useLiveStats(classSessionId.toString());
  const { notifications, unreadNotifications } = useNotifications();
  const activityFeed = useActivityFeed();
  
  // Zustand store actions
  const { loadClassReport, loadAlerts } = useAttendanceStore();
  
  // Real-time store actions
  const realtimeStore = useRealtimeStore();

  // Real-time event handlers
  const realtimeHandlers = useMemo(() => ({
    onStudentJoined: (data: StudentJoinedData) => {
      console.log('Student joined:', data);
      // Refresh class data to get updated attendance
      loadClassData();
    },
    
    onAttendanceUpdate: (data: AttendanceUpdateData) => {
      console.log('Attendance updated:', data);
      // Refresh the class report to get updated data
      loadClassData();
    },
    
    onStatsUpdate: (data: StatsUpdateData) => {
      console.log('Stats updated:', data);
      // Stats are automatically handled by the store
    },
    
    onSystemNotification: (data: SystemNotificationData) => {
      console.log('System notification:', data);
      // Notifications are automatically handled by the store
    },
    
    onConnectionChange: (connected: boolean, state: ConnectionState) => {
      console.log('Connection state changed:', state);
    },
    
    onError: (error: string) => {
      console.error('Real-time connection error:', error);
    }
  }), [loadClassData]);

  // Initialize real-time connection
  const realtime = useRealtime(
    {
      classId: classSessionId.toString(),
      token: teacherToken,
      autoConnect: true,
    },
    realtimeHandlers
  );

  // Load class data
  const loadClassData = useCallback(async () => {
    try {
      const report = await loadClassReport(classSessionId);
      setClassReport(report);
    } catch (error) {
      console.error('Failed to load class data:', error);
    }
  }, [classSessionId, loadClassReport]);

  // Load initial data on mount
  useEffect(() => {
    loadClassData();
    loadAlerts(classSessionId);
  }, [loadClassData, loadAlerts, classSessionId]);

  // Auto-refresh data
  useEffect(() => {
    if (autoRefreshInterval > 0) {
      const interval = setInterval(() => {
        if (!isConnected) {
          loadClassData();
        }
      }, autoRefreshInterval);
      
      return () => clearInterval(interval);
    }
  }, [autoRefreshInterval, isConnected, loadClassData]);

  // Filter and sort students
  const filteredAndSortedStudents = useMemo(() => {
    if (!classReport?.records) return [];
    
    let filtered = classReport.records;
    
    // Filter by status
    if (filterStatus !== 'all') {
      filtered = filtered.filter(record => record.status === filterStatus);
    }
    
    // Sort
    filtered.sort((a, b) => {
      let comparison = 0;
      
      switch (sortBy) {
        case 'name':
          comparison = (a.student_name || '').localeCompare(b.student_name || '');
          break;
        case 'status':
          comparison = a.status.localeCompare(b.status);
          break;
        case 'checkin_time':
          const timeA = a.check_in_time ? new Date(a.check_in_time).getTime() : 0;
          const timeB = b.check_in_time ? new Date(b.check_in_time).getTime() : 0;
          comparison = timeA - timeB;
          break;
      }
      
      return sortOrder === 'asc' ? comparison : -comparison;
    });
    
    return filtered;
  }, [classReport?.records, filterStatus, sortBy, sortOrder]);

  // Handle student selection
  const handleStudentSelect = useCallback((studentId: number, selected: boolean) => {
    setSelectedStudents(prev => {
      const newSet = new Set(prev);
      if (selected) {
        newSet.add(studentId);
      } else {
        newSet.delete(studentId);
      }
      return newSet;
    });
  }, []);

  const handleSelectAll = useCallback((selected: boolean) => {
    if (selected) {
      const allIds = filteredAndSortedStudents.map(record => record.id);
      setSelectedStudents(new Set(allIds));
    } else {
      setSelectedStudents(new Set());
    }
  }, [filteredAndSortedStudents]);

  // Handle bulk operations
  const handleBulkOperation = useCallback((operation: BulkAttendanceOperation, reason: string) => {
    if (selectedStudents.size === 0) return;
    
    const operationId = `bulk_${Date.now()}`;
    setActiveOperation(operationId);
    
    // Add a system notification for the bulk operation start
    realtimeStore.addSystemNotification({
      message: `Starting bulk ${operation} for ${selectedStudents.size} students...`,
      type: 'info',
      timestamp: new Date().toISOString()
    });
  }, [selectedStudents, realtimeStore]);

  // Get current stats (live or from report)
  const currentStats = liveStats || (classReport ? {
    class_id: classReport.class_session_id.toString(),
    session_id: classReport.class_session_id.toString(),
    total_students: classReport.stats.total_students,
    present_count: classReport.stats.present_count,
    late_count: classReport.stats.late_count,
    absent_count: classReport.stats.absent_count,
    attendance_rate: classReport.stats.attendance_rate,
    recent_joins: [],
    updated_at: new Date().toISOString()
  } : null);
  
  // Calculate derived stats
  const derivedStats = currentStats ? {
    total_enrolled: currentStats.total_students,
    checked_in_count: currentStats.present_count + currentStats.late_count,
    present_count: currentStats.present_count,
    late_count: currentStats.late_count,
    absent_count: currentStats.absent_count,
    excused_count: currentStats.absent_count, // Assuming absent includes excused for now
    attendance_rate: currentStats.attendance_rate
  } : null;

  if (!classReport) {
    return (
      <div className="teacher-dashboard loading">
        <div className="loading-spinner">
          <div className="spinner"></div>
          <p>Loading attendance data...</p>
        </div>
        <style jsx>{`
          .teacher-dashboard.loading {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 400px;
          }
          .loading-spinner {
            text-align: center;
          }
          .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #007bff;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
          }
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    );
  }

  return (
    <div className="teacher-dashboard">
      {/* Connection Status */}
      <div className={`connection-status ${isConnected ? 'connected' : 'disconnected'}`}>
        <span className="status-indicator"></span>
        {isConnected ? 'Live Updates Active' : connectionState === ConnectionState.CONNECTING ? 'Connecting...' : 'Offline Mode'}
        {connectionError && (
          <span className="connection-error" title={connectionError}>⚠️</span>
        )}
      </div>

      {/* System Notifications */}
      {unreadNotifications.length > 0 && (
        <div className="system-notifications">
          {unreadNotifications.slice(0, 3).map(notification => (
            <div key={notification.id} className={`alert alert-${notification.type}`}>
              <span className="alert-message">{notification.message}</span>
              <span className="alert-time">{new Date(notification.timestamp).toLocaleTimeString()}</span>
              <button 
                className="alert-dismiss" 
                onClick={() => realtimeStore.markNotificationAsRead(notification.id)}
              >
                ×
              </button>
            </div>
          ))}
          {unreadNotifications.length > 3 && (
            <div className="alert alert-info">
              <span className="alert-message">
                {unreadNotifications.length - 3} more notifications...
              </span>
              <button 
                className="alert-dismiss" 
                onClick={() => realtimeStore.markAllNotificationsAsRead()}
              >
                Mark all as read
              </button>
            </div>
          )}
        </div>
      )}

      {/* Class Header */}
      <div className="class-header">
        <h1>{classReport.class_name}</h1>
        <div className="class-info">
          <span>Subject: {classReport.subject || 'N/A'}</span>
          <span>Teacher: {classReport.teacher_name}</span>
          <span>Started: {new Date(classReport.start_time).toLocaleString()}</span>
        </div>
      </div>

      {/* Statistics Cards */}
      {derivedStats && (
        <div className="stats-cards">
          <div className="stat-card">
            <h3>Total Enrolled</h3>
            <div className="stat-value">{derivedStats.total_enrolled}</div>
          </div>
          <div className="stat-card">
            <h3>Checked In</h3>
            <div className="stat-value">{derivedStats.checked_in_count}</div>
          </div>
          <div className="stat-card">
            <h3>Present</h3>
            <div className="stat-value present">{derivedStats.present_count}</div>
          </div>
          <div className="stat-card">
            <h3>Late</h3>
            <div className="stat-value late">{derivedStats.late_count}</div>
          </div>
          <div className="stat-card">
            <h3>Absent</h3>
            <div className="stat-value absent">{derivedStats.absent_count}</div>
          </div>
          <div className="stat-card">
            <h3>Attendance Rate</h3>
            <div className="stat-value">{Math.round(derivedStats.attendance_rate * 100)}%</div>
          </div>
          {liveStats && (
            <div className="stat-card live-indicator">
              <h3>Live Updates</h3>
              <div className="stat-value" style={{ color: '#28a745', fontSize: '16px' }}>
                {isConnected ? '✅ Active' : '❌ Inactive'}
              </div>
              <div style={{ fontSize: '12px', color: '#666' }}>
                Last: {new Date(currentStats.updated_at).toLocaleTimeString()}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Action Bar */}
      <div className="action-bar">
        <div className="view-controls">
          <button 
            className={viewMode === 'table' ? 'active' : ''} 
            onClick={() => setViewMode('table')}
          >
            Table View
          </button>
          <button 
            className={viewMode === 'grid' ? 'active' : ''} 
            onClick={() => setViewMode('grid')}
          >
            Grid View
          </button>
        </div>

        <div className="filter-controls">
          <select 
            value={filterStatus} 
            onChange={(e) => setFilterStatus(e.target.value as any)}
          >
            <option value="all">All Students</option>
            <option value="PRESENT">Present</option>
            <option value="LATE">Late</option>
            <option value="ABSENT">Absent</option>
            <option value="EXCUSED">Excused</option>
          </select>

          <select 
            value={sortBy} 
            onChange={(e) => setSortBy(e.target.value as any)}
          >
            <option value="name">Sort by Name</option>
            <option value="status">Sort by Status</option>
            <option value="checkin_time">Sort by Check-in Time</option>
          </select>

          <button 
            onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
          >
            {sortOrder === 'asc' ? '↑' : '↓'}
          </button>
        </div>

        <div className="action-buttons">
          {showBulkOperations && (
            <button 
              className="btn btn-primary"
              onClick={() => setShowOverrideModal(true)}
              disabled={selectedStudents.size === 0}
            >
              Override Selected ({selectedStudents.size})
            </button>
          )}
          
          {showPatterns && (
            <button 
              className="btn btn-secondary"
              onClick={() => setShowPatternsModal(true)}
            >
              View Patterns
            </button>
          )}
          
          <button 
            className="btn btn-outline"
            onClick={loadClassData}
            disabled={!!activeOperation}
          >
            {activeOperation ? 'Processing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Student List */}
      <div className={`student-list ${viewMode}`}>
        {viewMode === 'table' ? (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  {showBulkOperations && (
                    <th>
                      <input
                        type="checkbox"
                        checked={selectedStudents.size === filteredAndSortedStudents.length && filteredAndSortedStudents.length > 0}
                        onChange={(e) => handleSelectAll(e.target.checked)}
                      />
                    </th>
                  )}
                  <th>Student</th>
                  <th>Status</th>
                  <th>Check-in Time</th>
                  <th>Late (min)</th>
                  <th>Override</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredAndSortedStudents.map(record => (
                  <tr key={record.id} className={`status-${record.status.toLowerCase()}`}>
                    {showBulkOperations && (
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedStudents.has(record.id)}
                          onChange={(e) => handleStudentSelect(record.id, e.target.checked)}
                        />
                      </td>
                    )}
                    <td>{record.student_name}</td>
                    <td>
                      <span className={`status-badge status-${record.status.toLowerCase()}`}>
                        {record.status}
                      </span>
                    </td>
                    <td>
                      {record.check_in_time ? new Date(record.check_in_time).toLocaleTimeString() : '-'}
                    </td>
                    <td>{record.late_minutes || 0}</td>
                    <td>
                      {record.is_manual_override && (
                        <span className="override-indicator" title={`Overridden by ${record.override_teacher_name}: ${record.override_reason}`}>
                          ✏️
                        </span>
                      )}
                    </td>
                    <td>
                      <button 
                        className="btn-sm btn-outline"
                        onClick={() => {
                          // Open individual override modal
                          setSelectedStudents(new Set([record.id]));
                          setShowOverrideModal(true);
                        }}
                      >
                        Edit
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="grid-container">
            {filteredAndSortedStudents.map(record => (
              <div key={record.id} className={`student-card status-${record.status.toLowerCase()}`}>
                {showBulkOperations && (
                  <input
                    type="checkbox"
                    className="student-select"
                    checked={selectedStudents.has(record.id)}
                    onChange={(e) => handleStudentSelect(record.id, e.target.checked)}
                  />
                )}
                <div className="student-name">{record.student_name}</div>
                <div className={`student-status status-${record.status.toLowerCase()}`}>
                  {record.status}
                </div>
                {record.check_in_time && (
                  <div className="checkin-time">
                    {new Date(record.check_in_time).toLocaleTimeString()}
                  </div>
                )}
                {record.late_minutes > 0 && (
                  <div className="late-minutes">Late: {record.late_minutes}min</div>
                )}
                {record.is_manual_override && (
                  <div className="override-indicator">✏️ Override</div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Real-time Activity Feed */}
      {activityFeed.length > 0 && (
        <div className="activity-section">
          <h3>Recent Activity</h3>
          <div className="activity-list">
            {activityFeed.slice(0, 5).map((activity) => (
              <div key={activity.id} className={`activity-item activity-${activity.type}`}>
                <div className="activity-content">
                  <span className="activity-type">{activity.type.replace('_', ' ')}</span>
                  <span className="activity-data">
                    {activity.type === 'student_joined' && activity.data.student_name}
                    {activity.type === 'attendance_update' && `${activity.data.student_id} status updated`}
                    {activity.type === 'session_update' && 'Session updated'}
                    {activity.type === 'system_notification' && activity.data.message}
                  </span>
                </div>
                <div className="activity-time">
                  {new Date(activity.timestamp).toLocaleTimeString()}
                </div>
              </div>
            ))}
            {activityFeed.length > 5 && (
              <div className="activity-more">
                {activityFeed.length - 5} more activities...
              </div>
            )}
          </div>
        </div>
      )}

      {/* Modals */}
      {showOverrideModal && (
        <AttendanceOverride
          classSessionId={classSessionId}
          selectedStudentIds={Array.from(selectedStudents)}
          onClose={() => {
            setShowOverrideModal(false);
            setSelectedStudents(new Set());
          }}
          onSuccess={() => {
            loadClassData();
            setSelectedStudents(new Set());
          }}
        />
      )}

      {showPatternsModal && (
        <AttendancePatterns
          classSessionId={classSessionId}
          alerts={[]} // Using empty array for now, can be replaced with attendance store alerts
          onClose={() => setShowPatternsModal(false)}
        />
      )}

      <style jsx>{`
        .teacher-dashboard {
          padding: 20px;
          max-width: 1400px;
          margin: 0 auto;
        }

        .connection-status {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 20px;
          padding: 8px 12px;
          border-radius: 4px;
          font-size: 14px;
          font-weight: 500;
        }

        .connection-status.connected {
          background-color: #d4edda;
          color: #155724;
          border: 1px solid #c3e6cb;
        }

        .connection-status.disconnected {
          background-color: #f8d7da;
          color: #721c24;
          border: 1px solid #f5c6cb;
        }

        .status-indicator {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background-color: currentColor;
        }

        .conflict-warning {
          background-color: #fff3cd;
          color: #856404;
          border: 1px solid #ffeaa7;
          border-radius: 4px;
          padding: 12px;
          margin-bottom: 20px;
        }

        .system-notifications {
          margin-bottom: 20px;
        }
        
        .connection-error {
          margin-left: 8px;
          color: #dc3545;
          cursor: help;
        }

        .alert {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 12px;
          border-radius: 4px;
          margin-bottom: 8px;
          font-size: 14px;
        }

        .alert-success {
          background-color: #d4edda;
          color: #155724;
          border: 1px solid #c3e6cb;
        }

        .alert-warning {
          background-color: #fff3cd;
          color: #856404;
          border: 1px solid #ffeaa7;
        }

        .alert-error {
          background-color: #f8d7da;
          color: #721c24;
          border: 1px solid #f5c6cb;
        }

        .alert-info {
          background-color: #d1ecf1;
          color: #0c5460;
          border: 1px solid #bee5eb;
        }

        .alert-dismiss {
          background: none;
          border: none;
          font-size: 18px;
          cursor: pointer;
          color: inherit;
        }

        .class-header h1 {
          margin: 0 0 8px 0;
          font-size: 28px;
          color: #333;
        }

        .class-info {
          display: flex;
          gap: 20px;
          color: #666;
          font-size: 14px;
        }

        .stats-cards {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 20px;
          margin: 30px 0;
        }

        .stat-card {
          background: white;
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 20px;
          text-align: center;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .stat-card h3 {
          margin: 0 0 10px 0;
          font-size: 14px;
          color: #666;
          text-transform: uppercase;
        }

        .stat-value {
          font-size: 32px;
          font-weight: bold;
          color: #333;
        }

        .stat-value.present { color: #28a745; }
        .stat-value.late { color: #ffc107; }
        .stat-value.absent { color: #dc3545; }

        .action-bar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin: 20px 0;
          flex-wrap: wrap;
          gap: 20px;
        }

        .view-controls, .filter-controls, .action-buttons {
          display: flex;
          gap: 10px;
        }

        .btn, .btn-sm, .btn-outline, .btn-primary, .btn-secondary {
          padding: 8px 16px;
          border: 1px solid #ddd;
          border-radius: 4px;
          background: white;
          cursor: pointer;
          font-size: 14px;
          transition: all 0.2s;
        }

        .btn-sm {
          padding: 4px 8px;
          font-size: 12px;
        }

        .btn-primary {
          background: #007bff;
          color: white;
          border-color: #007bff;
        }

        .btn-secondary {
          background: #6c757d;
          color: white;
          border-color: #6c757d;
        }

        .btn:hover, .btn-outline:hover {
          background: #f8f9fa;
        }

        .btn-primary:hover {
          background: #0056b3;
        }

        .btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .btn.active {
          background: #007bff;
          color: white;
        }

        .student-list.table .table-container {
          background: white;
          border: 1px solid #ddd;
          border-radius: 8px;
          overflow: hidden;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        table {
          width: 100%;
          border-collapse: collapse;
        }

        th, td {
          padding: 12px;
          text-align: left;
          border-bottom: 1px solid #eee;
        }

        th {
          background: #f8f9fa;
          font-weight: 600;
        }

        .status-badge {
          padding: 4px 8px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 500;
          text-transform: uppercase;
        }

        .status-present { background: #d4edda; color: #155724; }
        .status-late { background: #fff3cd; color: #856404; }
        .status-absent { background: #f8d7da; color: #721c24; }
        .status-excused { background: #d1ecf1; color: #0c5460; }

        .override-indicator {
          cursor: help;
        }

        .student-list.grid .grid-container {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 20px;
        }

        .student-card {
          background: white;
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 16px;
          position: relative;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
          transition: transform 0.2s;
        }

        .student-card:hover {
          transform: translateY(-2px);
        }

        .student-select {
          position: absolute;
          top: 8px;
          right: 8px;
        }

        .student-name {
          font-weight: 600;
          margin-bottom: 8px;
        }

        .student-status {
          padding: 4px 8px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 500;
          text-transform: uppercase;
          display: inline-block;
          margin-bottom: 8px;
        }

        .checkin-time {
          font-size: 14px;
          color: #666;
        }

        .late-minutes {
          font-size: 12px;
          color: #856404;
          font-weight: 500;
        }

        .activity-section {
          margin-top: 40px;
        }

        .activity-section h3 {
          margin-bottom: 20px;
          color: #333;
        }

        .activity-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px;
          border-left: 4px solid #007bff;
          background: #f8f9fa;
          margin-bottom: 8px;
          border-radius: 4px;
        }

        .activity-student_joined { border-left-color: #28a745; }
        .activity-attendance_update { border-left-color: #ffc107; }
        .activity-session_update { border-left-color: #17a2b8; }
        .activity-system_notification { border-left-color: #6c757d; }

        .activity-content {
          display: flex;
          gap: 12px;
        }

        .activity-type {
          font-weight: 600;
          text-transform: capitalize;
          font-size: 12px;
        }

        .activity-data {
          color: #333;
          font-size: 14px;
        }

        .activity-time {
          font-size: 12px;
          color: #666;
        }

        .activity-more {
          text-align: center;
          color: #666;
          font-size: 14px;
          padding: 8px;
        }
        
        .live-indicator {
          background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
          border: 2px solid #28a745;
        }

        @media (max-width: 768px) {
          .action-bar {
            flex-direction: column;
            align-items: stretch;
          }

          .view-controls, .filter-controls, .action-buttons {
            justify-content: center;
          }

          .stats-cards {
            grid-template-columns: repeat(2, 1fr);
          }

          .student-list.grid .grid-container {
            grid-template-columns: 1fr;
          }

          table {
            font-size: 14px;
          }

          th, td {
            padding: 8px;
          }
        }
      `}</style>
    </div>
  );
};

export default TeacherAttendanceDashboard;