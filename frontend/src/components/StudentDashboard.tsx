import React, { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { getMyAttendance, checkInWithCode, checkInWithQR, getMyEnrolledClasses, getActiveSessionsForStudent } from '../services/api';
import './StudentDashboard.css';

interface AttendanceRecord {
  id: number;
  class_session_id: number;
  class_name: string;
  subject?: string;
  teacher_name?: string;
  status: 'present' | 'absent' | 'late' | 'excused';
  check_in_time?: string;
  check_out_time?: string;
  verification_method?: string;
  is_late?: boolean;
  late_minutes?: number;
  created_at: string;
}

interface StudentStats {
  total_classes: number;
  attended_classes: number;
  late_count: number;
  attendance_rate: number;
}

interface EnrolledClass {
  id: number;
  name: string;
  subject?: string;
  teacher_name: string;
  status: string;
  start_time: string;
  end_time?: string;
  verification_code?: string;
  is_active_session: boolean;
  requires_checkin: boolean;
  last_attendance_status?: string;
  last_check_in_time?: string;
  created_at: string;
  location?: string;
  description?: string;
}

interface ActiveSession {
  id: number;
  name: string;
  subject?: string;
  teacher_name: string;
  start_time: string;
  end_time?: string;
  verification_code: string;
  is_newly_started: boolean;
  session_age_minutes: number;
  location?: string;
  allow_late_join: boolean;
  attendance_record_id: number;
}

type StudentView = 'dashboard' | 'join-class' | 'check-in' | 'class-checkin' | 'attendance-history' | 'my-classes' | 'profile';

export const StudentDashboard: React.FC = () => {
  const { user } = useAuth();
  const [currentView, setCurrentView] = useState<StudentView>('dashboard');
  const [attendanceRecords, setAttendanceRecords] = useState<AttendanceRecord[]>([]);
  const [enrolledClasses, setEnrolledClasses] = useState<EnrolledClass[]>([]);
  const [activeSessions, setActiveSessions] = useState<ActiveSession[]>([]);
  const [selectedClass, setSelectedClass] = useState<EnrolledClass | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [joinCode, setJoinCode] = useState('');
  const [joinSuccess, setJoinSuccess] = useState<string>('');

  // Load attendance data
  useEffect(() => {
    loadAttendanceHistory();
    loadEnrolledClasses();
    loadActiveSessions();
    
    // Set up periodic refresh for active sessions (every 30 seconds)
    const interval = setInterval(() => {
      loadActiveSessions();
    }, 30000);
    
    return () => clearInterval(interval);
  }, []);

  const loadAttendanceHistory = async () => {
    try {
      setLoading(true);
      const records = await getMyAttendance();
      setAttendanceRecords(records);
      setError('');
    } catch (err) {
      setError('Failed to load attendance history');
      console.error('Failed to load attendance:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadEnrolledClasses = async () => {
    try {
      const classes = await getMyEnrolledClasses();
      setEnrolledClasses(classes);
    } catch (err) {
      console.error('Failed to load enrolled classes:', err);
      // Don't show error for this as it's a background operation
    }
  };

  const loadActiveSessions = async () => {
    try {
      const sessions = await getActiveSessionsForStudent();
      setActiveSessions(sessions);
    } catch (err) {
      console.error('Failed to load active sessions:', err);
      // Don't show error for this as it's a background operation
    }
  };

  // Calculate student statistics
  const calculateStats = (): StudentStats => {
    const totalClasses = attendanceRecords.length;
    const attendedClasses = attendanceRecords.filter(r => 
      r.status === 'present' || r.status === 'late'
    ).length;
    const lateCount = attendanceRecords.filter(r => r.is_late).length;
    const attendanceRate = totalClasses > 0 ? (attendedClasses / totalClasses) * 100 : 0;

    return {
      total_classes: totalClasses,
      attended_classes: attendedClasses,
      late_count: lateCount,
      attendance_rate: Math.round(attendanceRate)
    };
  };

  const stats = calculateStats();

  // Join class with verification code
  const handleJoinWithCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!joinCode.trim()) {
      setError('Please enter a verification code');
      return;
    }

    try {
      setLoading(true);
      setError('');
      
      console.log('Attempting to join with code:', joinCode.trim());
      const result = await checkInWithCode(joinCode.trim());
      console.log('Join result:', result);
      
      setJoinSuccess(`Successfully joined ${result.class_name}!`);
      setJoinCode('');
      
      // Refresh all data
      await Promise.all([
        loadAttendanceHistory(),
        loadEnrolledClasses(),
        loadActiveSessions()
      ]);
      
      // Clear success message after 5 seconds
      setTimeout(() => setJoinSuccess(''), 5000);
      
    } catch (err: any) {
      console.error('Failed to join class:', err);
      
      // Provide more detailed error messages
      let errorMessage = 'Failed to join class';
      if (err.message) {
        errorMessage = err.message;
      }
      
      // Check for specific error patterns
      if (err.message?.includes('Not authenticated')) {
        errorMessage = 'Please log in first to join a class';
      } else if (err.message?.includes('Invalid verification code')) {
        errorMessage = 'Invalid verification code. Please check and try again.';
      } else if (err.message?.includes('Class session not found')) {
        errorMessage = 'No active class found with this code. Please verify the code with your teacher.';
      }
      
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  };

  // Quick check-in for active session
  const handleQuickCheckIn = async (session: ActiveSession) => {
    try {
      setLoading(true);
      setError('');
      
      const result = await checkInWithCode(session.verification_code);
      setJoinSuccess(`Successfully checked in to ${result.class_name}!`);
      
      // Refresh all data
      await Promise.all([
        loadAttendanceHistory(),
        loadEnrolledClasses(),
        loadActiveSessions()
      ]);
      
      // Clear success message after 5 seconds
      setTimeout(() => setJoinSuccess(''), 5000);
      
    } catch (err: any) {
      setError(err.message || 'Failed to check in');
    } finally {
      setLoading(false);
    }
  };

  // Format date for display
  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { 
      hour: '2-digit', 
      minute: '2-digit' 
    });
  };

  // Get status color
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'present': return '#28a745';
      case 'late': return '#ffc107';
      case 'absent': return '#dc3545';
      case 'excused': return '#17a2b8';
      default: return '#6c757d';
    }
  };

  const renderDashboard = () => (
    <div className="student-overview">
      <div className="welcome-section">
        <h2>Welcome back, {user?.full_name}!</h2>
        <p>Track your attendance and join classes</p>
      </div>

      {/* Active Session Notifications */}
      {activeSessions.length > 0 && (
        <div className="active-sessions-alert">
          <h3>🔔 Active Sessions Requiring Check-in</h3>
          {activeSessions.map(session => (
            <div key={session.id} className="active-session-card">
              <div className="session-info">
                <h4>{session.name}</h4>
                {session.subject && <p className="subject">{session.subject}</p>}
                <p className="teacher">👨‍🏫 {session.teacher_name}</p>
                <p className="time">
                  🕒 Started {session.session_age_minutes} minutes ago
                  {session.is_newly_started && <span className="new-badge">NEW</span>}
                </p>
                {session.location && <p className="location">📍 {session.location}</p>}
              </div>
              <button 
                className="quick-checkin-btn"
                onClick={() => handleQuickCheckIn(session)}
                disabled={loading}
              >
                {loading ? 'Checking in...' : '✅ Quick Check-in'}
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Statistics Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon">📚</div>
          <div className="stat-content">
            <div className="stat-number">{stats.total_classes}</div>
            <div className="stat-label">Total Classes</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">✅</div>
          <div className="stat-content">
            <div className="stat-number">{stats.attended_classes}</div>
            <div className="stat-label">Attended</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">📈</div>
          <div className="stat-content">
            <div className="stat-number">{stats.attendance_rate}%</div>
            <div className="stat-label">Attendance Rate</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">⏰</div>
          <div className="stat-content">
            <div className="stat-number">{stats.late_count}</div>
            <div className="stat-label">Times Late</div>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="quick-actions">
        <h3>Quick Actions</h3>
        {enrolledClasses.length === 0 ? (
          // No classes - emphasize joining a class
          <div className="action-grid">
            <button 
              className="action-card primary featured"
              onClick={() => setCurrentView('join-class')}
            >
              <div className="action-icon">🎯</div>
              <div className="action-content">
                <h4>Join Your First Class</h4>
                <p>Enter verification code from teacher</p>
                <span className="action-highlight">Start here!</span>
              </div>
            </button>
            
            <button 
              className="action-card secondary"
              onClick={() => setCurrentView('my-classes')}
            >
              <div className="action-icon">📚</div>
              <div className="action-content">
                <h4>My Classes</h4>
                <p>No classes yet</p>
              </div>
            </button>
            
            <button 
              className="action-card secondary"
              onClick={() => setCurrentView('attendance-history')}
            >
              <div className="action-icon">📋</div>
              <div className="action-content">
                <h4>View History</h4>
                <p>No history yet</p>
              </div>
            </button>
          </div>
        ) : (
          // Has classes - normal layout
          <div className="action-grid">
            <button 
              className="action-card primary"
              onClick={() => setCurrentView('my-classes')}
            >
              <div className="action-icon">📚</div>
              <div className="action-content">
                <h4>My Classes</h4>
                <p>View your {enrolledClasses.length} class{enrolledClasses.length !== 1 ? 'es' : ''}</p>
              </div>
            </button>
            
            <button 
              className="action-card secondary"
              onClick={() => setCurrentView('join-class')}
            >
              <div className="action-icon">🎯</div>
              <div className="action-content">
                <h4>Join Another Class</h4>
                <p>Enter code to join a class</p>
              </div>
            </button>
            
            <button 
              className="action-card secondary"
              onClick={() => setCurrentView('attendance-history')}
            >
              <div className="action-icon">📋</div>
              <div className="action-content">
                <h4>View History</h4>
                <p>Check your attendance records</p>
              </div>
            </button>
          </div>
        )}
      </div>

      {/* Recent Attendance */}
      <div className="recent-attendance">
        <h3>Recent Attendance</h3>
        {attendanceRecords.length === 0 ? (
          <div className="empty-state">
            <span className="empty-icon">📚</span>
            <p>No attendance records yet</p>
            <p className="empty-subtitle">Join your first class to get started!</p>
          </div>
        ) : (
          <div className="attendance-list">
            {attendanceRecords.slice(0, 5).map(record => (
              <div key={record.id} className="attendance-item">
                <div className="class-info">
                  <h4>{record.class_name}</h4>
                  {record.subject && <p className="subject">{record.subject}</p>}
                  <p className="date">{formatDate(record.created_at)}</p>
                </div>
                <div className="attendance-status">
                  <span 
                    className="status-badge"
                    style={{ backgroundColor: getStatusColor(record.status) }}
                  >
                    {record.status.toUpperCase()}
                  </span>
                  {record.is_late && (
                    <span className="late-indicator">
                      Late by {record.late_minutes}min
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  const renderJoinClass = () => (
    <div className="join-class-section">
      <div className="section-header">
        <h2>Join New Class</h2>
        <p>Enter the enrollment code to join a new class for the first time</p>
      </div>

      {/* Test information for development */}
      <div className="test-info">
        <h4>🧪 For Testing:</h4>
        <p>Available test verification codes (click to use):</p>
        <ul className="test-codes">
          <li><code onClick={() => setJoinCode('616386')}>616386</code> - Mathematics</li>
          <li><code onClick={() => setJoinCode('638683')}>638683</code> - Test Class</li>
          <li><code onClick={() => setJoinCode('744452')}>744452</code> - English Literature</li>
          <li><code onClick={() => setJoinCode('620986')}>620986</code> - Test QR Class</li>
          <li><code onClick={() => setJoinCode('050511')}>050511</code> - Test Math Class</li>
        </ul>
      </div>

      {joinSuccess && (
        <div className="success-message">
          <span className="success-icon">✅</span>
          {joinSuccess}
        </div>
      )}

      {error && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          {error}
        </div>
      )}

      <form onSubmit={handleJoinWithCode} className="join-form">
        <div className="form-group">
          <label htmlFor="joinCode">Enrollment Code</label>
          <input
            id="joinCode"
            type="text"
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value)}
            placeholder="Enter 6-digit enrollment code"
            maxLength={6}
            className="code-input"
          />
        </div>
        
        <button 
          type="submit" 
          className="join-button"
          disabled={loading || !joinCode.trim()}
        >
          {loading ? 'Joining...' : 'Join Class'}
        </button>
      </form>

      <div className="join-alternatives">
        <p>Alternative ways to join a new class:</p>
        <ul>
          <li>📱 Scan enrollment QR code provided by teacher</li>
          <li>🔗 Click on class invitation link</li>
          <li>📧 Use invitation email from your teacher</li>
        </ul>
        <div className="join-note">
          <p><strong>Note:</strong> Use "Join New Class" only when enrolling in a class for the first time. For daily attendance, use the "Check In" feature instead.</p>
        </div>
      </div>
    </div>
  );

  const renderCheckIn = () => (
    <div className="check-in-section">
      <div className="section-header">
        <h2>Check In to Class</h2>
        <p>Enter the verification code to mark your attendance in an active class session</p>
      </div>

      {/* Show active sessions if any */}
      {activeSessions.length > 0 && (
        <div className="active-sessions">
          <h3>🔴 Active Class Sessions</h3>
          <p>You have ongoing classes that require check-in:</p>
          {activeSessions.map(session => (
            <div key={session.id} className="active-session-card">
              <div className="session-info">
                <h4>{session.name}</h4>
                <p>Teacher: {session.teacher_name}</p>
                <p>Started: {formatDate(session.start_time)}</p>
                {session.verification_code && (
                  <div className="quick-checkin">
                    <code onClick={() => setJoinCode(session.verification_code!)}>
                      {session.verification_code}
                    </code>
                    <span>← Click to use this code</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Test information for development */}
      <div className="test-info">
        <h4>🧪 For Testing:</h4>
        <p>Available test verification codes (click to use):</p>
        <ul className="test-codes">
          <li><code onClick={() => setJoinCode('616386')}>616386</code> - Mathematics</li>
          <li><code onClick={() => setJoinCode('638683')}>638683</code> - Test Class</li>
          <li><code onClick={() => setJoinCode('744452')}>744452</code> - English Literature</li>
          <li><code onClick={() => setJoinCode('620986')}>620986</code> - Test QR Class</li>
          <li><code onClick={() => setJoinCode('050511')}>050511</code> - Test Math Class</li>
        </ul>
      </div>

      {joinSuccess && (
        <div className="success-message">
          <span className="success-icon">✅</span>
          {joinSuccess}
        </div>
      )}

      {error && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          {error}
        </div>
      )}

      <form onSubmit={handleJoinWithCode} className="check-in-form">
        <div className="form-group">
          <label htmlFor="checkInCode">Verification Code</label>
          <input
            id="checkInCode"
            type="text"
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value)}
            placeholder="Enter 6-digit code"
            maxLength={6}
            className="code-input"
          />
        </div>
        
        <button 
          type="submit" 
          className="check-in-button"
          disabled={loading || !joinCode.trim()}
        >
          {loading ? 'Checking In...' : 'Check In'}
        </button>
      </form>

      <div className="check-in-info">
        <h4>About Check-In:</h4>
        <ul>
          <li>✅ Use this to mark your attendance in classes you're already enrolled in</li>
          <li>⏰ Check-in as soon as class starts to avoid being marked late</li>
          <li>🔄 You can check-in multiple times during the session</li>
          <li>📱 Alternative: Scan the QR code displayed by your teacher</li>
        </ul>
      </div>
    </div>
  );

  const renderClassCheckIn = (classItem: EnrolledClass) => (
    <div className="class-check-in-section">
      <div className="section-header">
        <button 
          className="back-button"
          onClick={() => setCurrentView('my-classes')}
        >
          ← Back to My Classes
        </button>
        <h2>Check In to {classItem.name}</h2>
        <p>Enter the verification code provided by your teacher for this class session</p>
      </div>

      <div className="class-info-card">
        <h3>{classItem.name}</h3>
        <div className="class-details">
          {classItem.subject && <p>📖 {classItem.subject}</p>}
          <p>👨‍🏫 {classItem.teacher_name}</p>
          {classItem.location && <p>📍 {classItem.location}</p>}
        </div>
        <div className="class-status">
          <span className={`status-badge ${classItem.status}`}>
            {classItem.status.toUpperCase()}
          </span>
        </div>
      </div>

      {/* Show last attendance if available */}
      {classItem.last_attendance_status && (
        <div className="last-attendance">
          <h4>Previous Attendance:</h4>
          <div className="attendance-info">
            <span 
              className="status-badge"
              style={{ backgroundColor: getStatusColor(classItem.last_attendance_status) }}
            >
              {classItem.last_attendance_status.toUpperCase()}
            </span>
            {classItem.last_check_in_time && (
              <p>Last checked in: {formatDate(classItem.last_check_in_time)}</p>
            )}
          </div>
        </div>
      )}

      {joinSuccess && (
        <div className="success-message">
          <span className="success-icon">✅</span>
          {joinSuccess}
        </div>
      )}

      {error && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          {error}
        </div>
      )}

      <form onSubmit={handleJoinWithCode} className="class-check-in-form">
        <div className="form-group">
          <label htmlFor="classCheckInCode">Verification Code for {classItem.name}</label>
          <input
            id="classCheckInCode"
            type="text"
            value={joinCode}
            onChange={(e) => setJoinCode(e.target.value)}
            placeholder="Enter 6-digit verification code"
            maxLength={6}
            className="code-input"
          />
        </div>
        
        <button 
          type="submit" 
          className="check-in-button primary"
          disabled={loading || !joinCode.trim()}
        >
          {loading ? 'Checking In...' : `✅ Check In to ${classItem.name}`}
        </button>
      </form>

      <div className="check-in-instructions">
        <h4>How to check in:</h4>
        <ul>
          <li>✅ Get the current verification code from your teacher's screen</li>
          <li>⏰ Enter the code as soon as possible to avoid being marked late</li>
          <li>📱 Alternatively, scan the QR code if your teacher displays it</li>
          <li>🔄 You can check in multiple times during the same class session</li>
        </ul>
        
        <div className="note">
          <p><strong>Note:</strong> Each class session has a unique verification code. Make sure you're using the code for today's session of {classItem.name}.</p>
        </div>
      </div>
    </div>
  );

  const renderAttendanceHistory = () => (
    <div className="attendance-history-section">
      <div className="section-header">
        <h2>Attendance History</h2>
        <p>Your complete attendance record</p>
      </div>

      {loading && <div className="loading">Loading attendance history...</div>}

      {attendanceRecords.length === 0 && !loading ? (
        <div className="empty-state">
          <span className="empty-icon">📚</span>
          <p>No attendance records found</p>
          <p className="empty-subtitle">Join a class to start building your attendance history</p>
        </div>
      ) : (
        <div className="attendance-table">
          <div className="table-header">
            <div className="col-class">Class</div>
            <div className="col-date">Date</div>
            <div className="col-status">Status</div>
            <div className="col-method">Method</div>
          </div>
          
          {attendanceRecords.map(record => (
            <div key={record.id} className="table-row">
              <div className="col-class">
                <div className="class-name">{record.class_name}</div>
                {record.subject && <div className="class-subject">{record.subject}</div>}
              </div>
              <div className="col-date">
                {formatDate(record.created_at)}
              </div>
              <div className="col-status">
                <span 
                  className="status-badge"
                  style={{ backgroundColor: getStatusColor(record.status) }}
                >
                  {record.status.toUpperCase()}
                </span>
                {record.is_late && (
                  <div className="late-info">Late by {record.late_minutes}min</div>
                )}
              </div>
              <div className="col-method">
                {record.verification_method?.replace('_', ' ') || 'Unknown'}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  const renderMyClasses = () => (
    <div className="my-classes-section">
      <div className="section-header">
        <h2>My Classes</h2>
        <p>Classes you have joined or enrolled in</p>
      </div>

      {enrolledClasses.length === 0 ? (
        <div className="empty-state">
          <span className="empty-icon">📚</span>
          <h3>No classes found</h3>
          <p className="empty-subtitle">You haven't joined any classes yet. Get started by joining a class!</p>
          
          <div className="quick-join-section">
            <h4>How to join a class:</h4>
            <ol className="join-instructions">
              <li>Get the 6-digit verification code from your teacher</li>
              <li>Click "Join Class" below or use the navigation menu</li>
              <li>Enter the verification code</li>
              <li>Your class will appear here once joined!</li>
            </ol>
            
            <button 
              className="join-class-button primary"
              onClick={() => setCurrentView('join-class')}
            >
              🎯 Join a Class Now
            </button>
            
            <div className="alternative-methods">
              <h4>Alternative ways to join:</h4>
              <ul>
                <li>📱 Scan QR code from your teacher's screen</li>
                <li>🔗 Click on shared class link</li>
                <li>📧 Use invitation email link</li>
              </ul>
            </div>
          </div>
        </div>
      ) : (
        <div className="classes-grid">
          {enrolledClasses.map(classItem => (
            <div key={classItem.id} className="class-card">
              <div className="class-header">
                <h3>{classItem.name}</h3>
                <div className="class-status">
                  <span className={`status-badge ${classItem.status}`}>
                    {classItem.status.toUpperCase()}
                  </span>
                  {classItem.requires_checkin && (
                    <span className="checkin-required">⚠️ Check-in Required</span>
                  )}
                </div>
              </div>
              
              <div className="class-details">
                {classItem.subject && (
                  <p className="subject">📖 {classItem.subject}</p>
                )}
                <p className="teacher">👨‍🏫 {classItem.teacher_name}</p>
                {classItem.location && (
                  <p className="location">📍 {classItem.location}</p>
                )}
                <p className="date">
                  🕒 {formatDate(classItem.start_time)}
                </p>
              </div>

              <div className="class-attendance-status">
                {classItem.last_attendance_status && (
                  <div className="attendance-info">
                    <span 
                      className="status-badge"
                      style={{ backgroundColor: getStatusColor(classItem.last_attendance_status) }}
                    >
                      Last: {classItem.last_attendance_status.toUpperCase()}
                    </span>
                    {classItem.last_check_in_time && (
                      <p className="check-in-time">
                        Checked in: {formatDate(classItem.last_check_in_time)}
                      </p>
                    )}
                  </div>
                )}
              </div>

              <div className="class-actions">
                <button
                  className="check-in-btn primary"
                  onClick={() => {
                    setSelectedClass(classItem);
                    setCurrentView('class-checkin');
                  }}
                >
                  ✅ Check In to This Class
                </button>
                
                {classItem.requires_checkin && classItem.verification_code && (
                  <button
                    className="quick-action-btn secondary"
                    onClick={() => handleQuickCheckIn({
                      id: classItem.id,
                      name: classItem.name,
                      subject: classItem.subject,
                      teacher_name: classItem.teacher_name,
                      start_time: classItem.start_time,
                      end_time: classItem.end_time,
                      verification_code: classItem.verification_code,
                      is_newly_started: false,
                      session_age_minutes: 0,
                      location: classItem.location,
                      allow_late_join: true,
                      attendance_record_id: 0
                    })}
                    disabled={loading}
                >
                  {loading ? 'Checking in...' : '✅ Check In Now'}
                </button>
              )}
            </div>
          </div>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <div className="student-dashboard">
      {/* Navigation */}
      <div className="dashboard-nav">
        <div className="nav-header">
          <h1>Student Portal</h1>
          <div className="user-info">
            <span className="user-name">{user?.full_name}</span>
            <span className="user-role">({user?.role})</span>
          </div>
        </div>
        
        <nav className="nav-menu">
          <button 
            className={`nav-item ${currentView === 'dashboard' ? 'active' : ''}`}
            onClick={() => setCurrentView('dashboard')}
          >
            <span className="nav-icon">🏠</span>
            Dashboard
          </button>
          <button 
            className={`nav-item ${currentView === 'my-classes' ? 'active' : ''}`}
            onClick={() => setCurrentView('my-classes')}
          >
            <span className="nav-icon">📚</span>
            My Classes
          </button>
          <button 
            className={`nav-item ${currentView === 'join-class' ? 'active' : ''}`}
            onClick={() => setCurrentView('join-class')}
          >
            <span className="nav-icon">🎯</span>
            Join Class
          </button>
          <button 
            className={`nav-item ${currentView === 'check-in' ? 'active' : ''}`}
            onClick={() => setCurrentView('check-in')}
          >
            <span className="nav-icon">✅</span>
            Check In
          </button>
          <button 
            className={`nav-item ${currentView === 'attendance-history' ? 'active' : ''}`}
            onClick={() => setCurrentView('attendance-history')}
          >
            <span className="nav-icon">📋</span>
            Attendance History
          </button>
        </nav>
      </div>

      {/* Main Content */}
      <main className="dashboard-content">
        {currentView === 'dashboard' && renderDashboard()}
        {currentView === 'my-classes' && renderMyClasses()}
        {currentView === 'join-class' && renderJoinClass()}
        {currentView === 'check-in' && renderCheckIn()}
        {currentView === 'class-checkin' && selectedClass && renderClassCheckIn(selectedClass)}
        {currentView === 'attendance-history' && renderAttendanceHistory()}
      </main>
    </div>
  );
};

export default StudentDashboard;