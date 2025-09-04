// AttendanceStatus Display Component with Real-time Updates
import React, { useEffect, useState, useMemo } from 'react';
import {
  AttendanceStatusProps,
  AttendanceRecord,
  ClassAttendanceStatus,
  AttendanceAlert,
  StudentAttendancePattern
} from '../types/attendance';
import { AttendanceStatus as Status } from '../types/api';
import { 
  useAttendanceStore, 
  useAttendanceStatus, 
  useMyAttendance, 
  useAttendanceLoading, 
  useAttendanceErrors 
} from '../store/attendance';

// Styled component styles (inline for simplicity, could be moved to CSS file)
const styles = {
  container: {
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", sans-serif',
    maxWidth: '800px',
    margin: '0 auto',
    padding: '1rem',
  },
  card: {
    background: 'white',
    borderRadius: '12px',
    padding: '1.5rem',
    marginBottom: '1rem',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
    border: '1px solid #e9ecef',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '1.5rem',
    paddingBottom: '1rem',
    borderBottom: '1px solid #e9ecef',
  },
  title: {
    margin: 0,
    color: '#333',
    fontSize: '1.5rem',
    fontWeight: 600,
  },
  badge: {
    padding: '0.5rem 1rem',
    borderRadius: '20px',
    fontSize: '0.875rem',
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
    gap: '1rem',
    marginBottom: '1.5rem',
  },
  statCard: {
    background: '#f8f9fa',
    padding: '1rem',
    borderRadius: '8px',
    textAlign: 'center' as const,
    border: '1px solid #dee2e6',
  },
  statValue: {
    fontSize: '2rem',
    fontWeight: 'bold',
    margin: '0 0 0.5rem 0',
  },
  statLabel: {
    color: '#6c757d',
    fontSize: '0.875rem',
    fontWeight: 500,
    margin: 0,
  },
  list: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
  },
  listItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '0.75rem',
    marginBottom: '0.5rem',
    background: '#f8f9fa',
    borderRadius: '8px',
    border: '1px solid #dee2e6',
  },
  studentInfo: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
  },
  statusIcon: {
    width: '12px',
    height: '12px',
    borderRadius: '50%',
    display: 'inline-block',
  },
  timeInfo: {
    fontSize: '0.875rem',
    color: '#6c757d',
  },
  loadingSpinner: {
    display: 'inline-block',
    width: '20px',
    height: '20px',
    border: '3px solid #f3f3f3',
    borderTop: '3px solid #007bff',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
  },
  errorMessage: {
    background: '#f8d7da',
    color: '#721c24',
    padding: '0.75rem 1rem',
    borderRadius: '8px',
    border: '1px solid #f5c6cb',
    marginBottom: '1rem',
  },
  refreshButton: {
    background: '#007bff',
    color: 'white',
    border: 'none',
    borderRadius: '6px',
    padding: '0.5rem 1rem',
    cursor: 'pointer',
    fontSize: '0.875rem',
    fontWeight: 500,
    transition: 'background 0.2s ease',
  },
  alertCard: {
    padding: '1rem',
    borderRadius: '8px',
    marginBottom: '0.5rem',
    border: '1px solid',
    display: 'flex',
    alignItems: 'flex-start',
    gap: '0.75rem',
  },
  alertIcon: {
    fontSize: '1.2rem',
    marginTop: '0.1rem',
  },
  alertContent: {
    flex: 1,
  },
  alertTitle: {
    margin: '0 0 0.25rem 0',
    fontSize: '0.875rem',
    fontWeight: 600,
  },
  alertMessage: {
    margin: 0,
    fontSize: '0.875rem',
    lineHeight: 1.4,
  },
  emptyState: {
    textAlign: 'center' as const,
    padding: '2rem',
    color: '#6c757d',
  },
  emptyIcon: {
    fontSize: '3rem',
    marginBottom: '1rem',
    opacity: 0.5,
  },
};

// CSS animation for loading spinner
const spinKeyframes = `
  @keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
  }
`;

// Inject CSS animation
if (typeof document !== 'undefined') {
  const styleSheet = document.createElement('style');
  styleSheet.type = 'text/css';
  styleSheet.innerText = spinKeyframes;
  document.head.appendChild(styleSheet);
}

export const AttendanceStatus: React.FC<AttendanceStatusProps> = ({
  classId,
  studentId,
  showDetails = true,
  showHistory = false,
  refreshInterval = 30000, // 30 seconds
}) => {
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  
  // Store hooks
  const {
    loadClassStatus,
    loadClassReport,
    loadMyAttendance,
    loadAlerts,
    subscribeToUpdates,
    unsubscribeFromUpdates,
  } = useAttendanceStore();
  
  const classStatus = useAttendanceStatus(classId);
  const myAttendance = useMyAttendance();
  const loading = useAttendanceLoading();
  const errors = useAttendanceErrors();

  // Local state for component-specific data
  const [alerts, setAlerts] = useState<AttendanceAlert[]>([]);
  const [classReport, setClassReport] = useState<any>(null);

  // Auto-refresh effect
  useEffect(() => {
    const interval = setInterval(() => {
      if (classId) {
        loadClassStatus(classId);
        setLastRefresh(new Date());
      }
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [classId, refreshInterval, loadClassStatus]);

  // Subscribe to real-time updates
  useEffect(() => {
    if (classId) {
      subscribeToUpdates(classId);
      loadClassStatus(classId);
      
      if (showDetails) {
        loadClassReport(classId).then(setClassReport);
      }
      
      if (studentId) {
        loadAlerts(classId).then(setAlerts);
      }
    }

    if (showHistory) {
      loadMyAttendance();
    }

    return () => {
      if (classId) {
        unsubscribeFromUpdates(classId);
      }
    };
  }, [classId, studentId, showDetails, showHistory, subscribeToUpdates, unsubscribeFromUpdates, loadClassStatus, loadClassReport, loadMyAttendance, loadAlerts]);

  // Utility functions
  const getStatusColor = (status: Status): string => {
    switch (status) {
      case Status.PRESENT:
        return '#28a745';
      case Status.LATE:
        return '#ffc107';
      case Status.ABSENT:
        return '#dc3545';
      case Status.EXCUSED:
        return '#6c757d';
      default:
        return '#007bff';
    }
  };

  const getStatusBadgeStyle = (status: Status) => ({
    ...styles.badge,
    backgroundColor: getStatusColor(status),
    color: status === Status.LATE ? '#000' : '#fff',
  });

  const getAlertStyle = (severity: 'low' | 'medium' | 'high') => {
    const baseStyle = styles.alertCard;
    switch (severity) {
      case 'high':
        return { ...baseStyle, backgroundColor: '#f8d7da', borderColor: '#f5c6cb', color: '#721c24' };
      case 'medium':
        return { ...baseStyle, backgroundColor: '#fff3cd', borderColor: '#ffeaa7', color: '#856404' };
      case 'low':
        return { ...baseStyle, backgroundColor: '#d1ecf1', borderColor: '#b6d4db', color: '#0c5460' };
      default:
        return { ...baseStyle, backgroundColor: '#f8f9fa', borderColor: '#dee2e6', color: '#495057' };
    }
  };

  const formatTime = (timestamp: string): string => {
    return new Date(timestamp).toLocaleTimeString();
  };

  const formatDate = (timestamp: string): string => {
    return new Date(timestamp).toLocaleDateString();
  };

  const calculateAttendanceRate = (status: ClassAttendanceStatus): number => {
    if (status.total_enrolled === 0) return 0;
    return Math.round(((status.present_count + status.late_count) / status.total_enrolled) * 100);
  };

  // Filter attendance records for current student
  const filteredAttendance = useMemo(() => {
    if (!showHistory) return [];
    return myAttendance.slice(0, 10); // Show last 10 records
  }, [myAttendance, showHistory]);

  // Render loading state
  if (loading.status && !classStatus) {
    return (
      <div style={styles.container}>
        <div style={styles.card}>
          <div style={{ textAlign: 'center', padding: '2rem' }}>
            <div style={styles.loadingSpinner}></div>
            <p style={{ marginTop: '1rem', color: '#6c757d' }}>Loading attendance status...</p>
          </div>
        </div>
      </div>
    );
  }

  // Render error state
  if (errors.status && !classStatus) {
    return (
      <div style={styles.container}>
        <div style={styles.errorMessage}>
          {errors.status}
        </div>
        <button
          style={styles.refreshButton}
          onClick={() => classId && loadClassStatus(classId)}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Main Status Card */}
      {classStatus && (
        <div style={styles.card}>
          <div style={styles.header}>
            <h2 style={styles.title}>{classStatus.class_name}</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <div style={getStatusBadgeStyle(Status.PRESENT)}>
                {calculateAttendanceRate(classStatus)}% Present
              </div>
              <button
                style={styles.refreshButton}
                onClick={() => classId && loadClassStatus(classId)}
                disabled={loading.status}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#0056b3')}
                onMouseLeave={(e) => (e.currentTarget.style.background = '#007bff')}
              >
                {loading.status ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
          </div>

          {/* Statistics Grid */}
          <div style={styles.statsGrid}>
            <div style={styles.statCard}>
              <div style={{ ...styles.statValue, color: getStatusColor(Status.PRESENT) }}>
                {classStatus.present_count}
              </div>
              <p style={styles.statLabel}>Present</p>
            </div>
            <div style={styles.statCard}>
              <div style={{ ...styles.statValue, color: getStatusColor(Status.LATE) }}>
                {classStatus.late_count}
              </div>
              <p style={styles.statLabel}>Late</p>
            </div>
            <div style={styles.statCard}>
              <div style={{ ...styles.statValue, color: getStatusColor(Status.ABSENT) }}>
                {classStatus.absent_count}
              </div>
              <p style={styles.statLabel}>Absent</p>
            </div>
            <div style={styles.statCard}>
              <div style={{ ...styles.statValue, color: getStatusColor(Status.EXCUSED) }}>
                {classStatus.excused_count}
              </div>
              <p style={styles.statLabel}>Excused</p>
            </div>
          </div>

          <div style={{ fontSize: '0.875rem', color: '#6c757d', textAlign: 'center' }}>
            Last updated: {formatTime(classStatus.last_updated)} • 
            Total enrolled: {classStatus.total_enrolled} • 
            Checked in: {classStatus.checked_in_count}
          </div>
        </div>
      )}

      {/* Alerts */}
      {alerts.length > 0 && (
        <div style={styles.card}>
          <h3 style={{ ...styles.title, fontSize: '1.25rem', marginBottom: '1rem' }}>
            Attendance Alerts
          </h3>
          {alerts.map((alert, index) => (
            <div key={index} style={getAlertStyle(alert.severity)}>
              <div style={styles.alertIcon}>
                {alert.severity === 'high' ? '🚨' : alert.severity === 'medium' ? '⚠️' : 'ℹ️'}
              </div>
              <div style={styles.alertContent}>
                <div style={styles.alertTitle}>{alert.type.replace('_', ' ').toUpperCase()}</div>
                <p style={styles.alertMessage}>{alert.message}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Detailed Class Report */}
      {showDetails && classReport && (
        <div style={styles.card}>
          <h3 style={{ ...styles.title, fontSize: '1.25rem', marginBottom: '1rem' }}>
            Class Details
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
            <div>
              <p style={styles.statLabel}>Teacher</p>
              <p style={{ margin: '0.25rem 0', fontWeight: 500 }}>{classReport.teacher_name}</p>
            </div>
            <div>
              <p style={styles.statLabel}>Duration</p>
              <p style={{ margin: '0.25rem 0', fontWeight: 500 }}>
                {classReport.duration_minutes ? `${classReport.duration_minutes} minutes` : 'Ongoing'}
              </p>
            </div>
            <div>
              <p style={styles.statLabel}>Start Time</p>
              <p style={{ margin: '0.25rem 0', fontWeight: 500 }}>
                {formatTime(classReport.start_time)}
              </p>
            </div>
            <div>
              <p style={styles.statLabel}>End Time</p>
              <p style={{ margin: '0.25rem 0', fontWeight: 500 }}>
                {classReport.end_time ? formatTime(classReport.end_time) : 'Not ended'}
              </p>
            </div>
          </div>
          
          {classReport.subject && (
            <div>
              <p style={styles.statLabel}>Subject</p>
              <p style={{ margin: '0.25rem 0 1rem 0', fontWeight: 500 }}>{classReport.subject}</p>
            </div>
          )}
        </div>
      )}

      {/* My Attendance History */}
      {showHistory && filteredAttendance.length > 0 && (
        <div style={styles.card}>
          <h3 style={{ ...styles.title, fontSize: '1.25rem', marginBottom: '1rem' }}>
            My Recent Attendance
          </h3>
          <ul style={styles.list}>
            {filteredAttendance.map((record) => (
              <li key={record.id} style={styles.listItem}>
                <div style={styles.studentInfo}>
                  <span 
                    style={{ 
                      ...styles.statusIcon, 
                      backgroundColor: getStatusColor(record.status) 
                    }}
                  ></span>
                  <div>
                    <div style={{ fontWeight: 500 }}>{record.class_name}</div>
                    <div style={styles.timeInfo}>
                      {record.subject && `${record.subject} • `}
                      {formatDate(record.created_at)}
                    </div>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ 
                    ...styles.badge, 
                    ...getStatusBadgeStyle(record.status),
                    fontSize: '0.75rem',
                    padding: '0.25rem 0.5rem'
                  }}>
                    {record.status}
                  </div>
                  {record.check_in_time && (
                    <div style={styles.timeInfo}>
                      {formatTime(record.check_in_time)}
                      {record.is_late && ` (${record.late_minutes}m late)`}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Empty State */}
      {!classStatus && !loading.status && !errors.status && (
        <div style={styles.card}>
          <div style={styles.emptyState}>
            <div style={styles.emptyIcon}>📊</div>
            <h3>No Attendance Data</h3>
            <p>No attendance information available for this class.</p>
          </div>
        </div>
      )}
    </div>
  );
};