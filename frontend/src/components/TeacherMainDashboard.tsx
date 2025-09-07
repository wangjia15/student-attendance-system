import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../hooks/useAuth';
import { ClassCreationForm } from './ClassCreationForm';
import TeacherAttendanceDashboard from './TeacherAttendanceDashboard';
import { AttendanceDashboard } from './AttendanceDashboard';
import { ClassSessionResponse, UserResponse } from '../types/api';
import { getClassSessions, getClassMembers } from '../services/api';
import './TeacherMainDashboard.css';

type DashboardView = 'overview' | 'create-class' | 'manage-class' | 'attendance-dashboard' | 'reports' | 'settings';

interface ActiveClass extends ClassSessionResponse {
  last_activity?: string;
  student_count?: number;
}

export const TeacherMainDashboard: React.FC = () => {
  const { user } = useAuth();
  const [currentView, setCurrentView] = useState<DashboardView>('overview');
  const [activeClasses, setActiveClasses] = useState<ActiveClass[]>([]);
  const [selectedClass, setSelectedClass] = useState<ActiveClass | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [classStudents, setClassStudents] = useState<UserResponse[]>([]);
  const [loadingStudents, setLoadingStudents] = useState(false);

  // Load user's active classes
  useEffect(() => {
    const loadClasses = async () => {
      try {
        setLoading(true);
        const classes = await getClassSessions();
        setActiveClasses(classes);
        setError('');
      } catch (err) {
        setError('Failed to load your classes. Please refresh the page.');
        console.error('Failed to load classes:', err);
      } finally {
        setLoading(false);
      }
    };

    if (user?.role === 'teacher') {
      loadClasses();
    }
  }, [user]);

  // Handle successful class creation
  const handleClassCreated = (newClass: ClassSessionResponse) => {
    setActiveClasses(prev => [newClass, ...prev]);
    setSelectedClass(newClass);
    setCurrentView('attendance-dashboard');
  };

  // Load students for selected class
  const loadClassStudents = async (classId: number) => {
    try {
      setLoadingStudents(true);
      const students = await getClassMembers(classId);
      setClassStudents(students);
    } catch (error) {
      console.error('Failed to load class students:', error);
      setClassStudents([]);
    } finally {
      setLoadingStudents(false);
    }
  };

  // Handle class selection for management
  const handleClassSelect = (classItem: ActiveClass) => {
    setSelectedClass(classItem);
    setCurrentView('manage-class');
    // Load students when a class is selected for management
    loadClassStudents(classItem.id);
  };

  // Navigation functions
  const goToOverview = () => {
    setCurrentView('overview');
    setSelectedClass(null);
  };

  const goToCreateClass = () => {
    setCurrentView('create-class');
  };

  const goToReports = () => {
    setCurrentView('reports');
  };

  const goToSettings = () => {
    setCurrentView('settings');
  };

  const goToAttendanceDashboard = (classItem: ActiveClass) => {
    setSelectedClass(classItem);
    setCurrentView('attendance-dashboard');
  };

  // Stable callback for session updates
  const handleSessionUpdate = useCallback((updates: Partial<ClassSessionResponse>) => {
    if (selectedClass) {
      setSelectedClass(prev => prev ? { ...prev, ...updates } : null);
      setActiveClasses(prev => 
        prev.map(c => c.id === selectedClass.id ? { ...c, ...updates } : c)
      );
    }
  }, [selectedClass]);

  // Stats calculation
  const totalClasses = activeClasses.length;
  const activeClassCount = activeClasses.filter(c => c.status === 'active').length;
  const totalStudents = activeClasses.reduce((sum, c) => sum + (c.student_count || 0), 0);

  if (loading) {
    return (
      <div className="teacher-dashboard loading">
        <div className="loading-spinner">
          <div className="spinner"></div>
          <p>Loading your dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="teacher-main-dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <div className="header-content">
          <div className="user-info">
            <h1>Welcome, {user?.full_name}</h1>
            <p className="user-role">Teacher Dashboard</p>
          </div>
          
          {currentView !== 'overview' && (
            <nav className="breadcrumb">
              <button onClick={goToOverview} className="breadcrumb-link">
                Dashboard
              </button>
              <span className="breadcrumb-separator">›</span>
              <span className="breadcrumb-current">
                {currentView === 'create-class' && 'Create Class'}
                {currentView === 'manage-class' && `Manage ${selectedClass?.name}`}
                {currentView === 'attendance-dashboard' && `Attendance - ${selectedClass?.name}`}
                {currentView === 'reports' && 'Reports & Analytics'}
                {currentView === 'settings' && 'Settings'}
              </span>
            </nav>
          )}
        </div>
      </header>

      {/* Main Content */}
      <main className="dashboard-content">
        {currentView === 'overview' && (
          <div className="overview-section">
            {/* Quick Stats */}
            <div className="stats-grid">
              <div className="stat-card">
                <div className="stat-icon">📚</div>
                <div className="stat-content">
                  <div className="stat-number">{totalClasses}</div>
                  <div className="stat-label">Total Classes</div>
                </div>
              </div>
              
              <div className="stat-card">
                <div className="stat-icon">✅</div>
                <div className="stat-content">
                  <div className="stat-number">{activeClassCount}</div>
                  <div className="stat-label">Active Sessions</div>
                </div>
              </div>
              
              <div className="stat-card">
                <div className="stat-icon">👥</div>
                <div className="stat-content">
                  <div className="stat-number">{totalStudents}</div>
                  <div className="stat-label">Total Students</div>
                </div>
              </div>
            </div>

            {/* Quick Actions */}
            <div className="quick-actions">
              <h2>Quick Actions</h2>
              <div className="action-grid">
                <button 
                  className="action-card primary"
                  onClick={goToCreateClass}
                >
                  <div className="action-icon">➕</div>
                  <div className="action-content">
                    <h3>Create New Class</h3>
                    <p>Set up a new attendance session</p>
                  </div>
                </button>
                
                <button 
                  className="action-card secondary"
                  onClick={goToReports}
                >
                  <div className="action-icon">📊</div>
                  <div className="action-content">
                    <h3>View Reports</h3>
                    <p>Analyze attendance patterns</p>
                  </div>
                </button>
                
                <button 
                  className="action-card secondary"
                  onClick={goToSettings}
                >
                  <div className="action-icon">⚙️</div>
                  <div className="action-content">
                    <h3>Settings</h3>
                    <p>Configure preferences</p>
                  </div>
                </button>
              </div>
            </div>

            {/* Active Classes */}
            <div className="classes-section">
              <div className="section-header">
                <h2>Your Classes</h2>
                <button 
                  className="create-class-btn"
                  onClick={goToCreateClass}
                >
                  + New Class
                </button>
              </div>
              
              {error && (
                <div className="error-message">
                  <span className="error-icon">⚠️</span>
                  {error}
                </div>
              )}
              
              {activeClasses.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-icon">📋</div>
                  <h3>No Classes Yet</h3>
                  <p>Create your first class to start tracking attendance</p>
                  <button 
                    className="empty-action-btn"
                    onClick={goToCreateClass}
                  >
                    Create Your First Class
                  </button>
                </div>
              ) : (
                <div className="classes-grid">
                  {activeClasses.map((classItem) => (
                    <div 
                      key={classItem.id} 
                      className={`class-card ${classItem.status}`}
                    >
                      <div className="class-header">
                        <h3>{classItem.name}</h3>
                        <span className={`status-badge ${classItem.status}`}>
                          {classItem.status.toUpperCase()}
                        </span>
                      </div>
                      
                      <div className="class-details">
                        {classItem.subject && (
                          <p className="class-subject">{classItem.subject}</p>
                        )}
                        <div className="class-meta">
                          <span className="student-count">
                            👥 {classItem.student_count || 0} students
                          </span>
                          <span className="class-time">
                            🕒 {new Date(classItem.created_at).toLocaleDateString()}
                          </span>
                        </div>
                      </div>
                      
                      <div className="class-actions">
                        {classItem.status === 'active' ? (
                          <button 
                            className="action-btn primary"
                            onClick={() => goToAttendanceDashboard(classItem)}
                          >
                            Take Attendance
                          </button>
                        ) : (
                          <button 
                            className="action-btn secondary"
                            onClick={() => handleClassSelect(classItem)}
                          >
                            View Details
                          </button>
                        )}
                        
                        <button 
                          className="action-btn outline"
                          onClick={() => handleClassSelect(classItem)}
                        >
                          Manage
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {currentView === 'create-class' && (
          <div className="create-class-section">
            <ClassCreationForm
              onSessionCreated={handleClassCreated}
              onCancel={goToOverview}
            />
          </div>
        )}

        {currentView === 'manage-class' && selectedClass && (
          <div className="manage-class-section">
            <div className="manage-header">
              <h2>Manage Class: {selectedClass.name}</h2>
              <div className="manage-actions">
                <button 
                  className="action-btn primary"
                  onClick={() => goToAttendanceDashboard(selectedClass)}
                >
                  Take Attendance
                </button>
                <button 
                  className="action-btn outline"
                  onClick={() => {/* TODO: Edit class */}}
                >
                  Edit Class
                </button>
              </div>
            </div>
            
            <div className="class-details-panel">
              <div className="detail-section">
                <h3>Class Information</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Name:</label>
                    <span>{selectedClass.name}</span>
                  </div>
                  <div className="detail-item">
                    <label>Subject:</label>
                    <span>{selectedClass.subject || 'N/A'}</span>
                  </div>
                  <div className="detail-item">
                    <label>Status:</label>
                    <span className={`status-badge ${selectedClass.status}`}>
                      {selectedClass.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="detail-item">
                    <label>Created:</label>
                    <span>{new Date(selectedClass.created_at).toLocaleString()}</span>
                  </div>
                </div>
              </div>
              
              {selectedClass.status === 'active' && (
                <div className="detail-section">
                  <h3>Session Details</h3>
                  <div className="session-info">
                    <div className="session-codes">
                      <div className="code-item">
                        <label>Join Code:</label>
                        <code className="join-code">{selectedClass.verification_code}</code>
                      </div>
                      {selectedClass.join_link && (
                        <div className="code-item">
                          <label>Join Link:</label>
                          <a 
                            href={selectedClass.join_link} 
                            target="_blank" 
                            rel="noopener noreferrer"
                            className="join-link"
                          >
                            {selectedClass.join_link}
                          </a>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}
              
              {/* Students List Section */}
              <div className="detail-section">
                <div className="section-header">
                  <h3>Enrolled Students</h3>
                  <span className="student-count-badge">
                    {loadingStudents ? '...' : classStudents.length} students
                  </span>
                </div>
                
                {loadingStudents ? (
                  <div className="loading-students">
                    <div className="loading-spinner"></div>
                    <p>Loading students...</p>
                  </div>
                ) : classStudents.length === 0 ? (
                  <div className="no-students">
                    <div className="no-students-icon">👥</div>
                    <h4>No Students Enrolled</h4>
                    <p>No students have joined this class yet. Share the verification code or QR code to get students enrolled.</p>
                    {selectedClass?.status === 'active' && (
                      <div className="join-info">
                        <p><strong>Join Code:</strong> <code>{selectedClass.verification_code}</code></p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="students-list">
                    {classStudents.map((student, index) => (
                      <div key={student.id} className="student-item">
                        <div className="student-avatar">
                          {(student.full_name || student.username).charAt(0).toUpperCase()}
                        </div>
                        <div className="student-info">
                          <div className="student-name">
                            {student.full_name || student.username}
                          </div>
                          <div className="student-email">{student.email}</div>
                        </div>
                        <div className="student-status">
                          <span className={`status-indicator ${student.is_active ? 'active' : 'inactive'}`}>
                            {student.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                        <div className="student-actions">
                          <button 
                            className="action-btn-small view-attendance"
                            onClick={() => {/* TODO: View student attendance history */}}
                          >
                            View Attendance
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                
                {!loadingStudents && classStudents.length > 0 && (
                  <div className="students-actions">
                    <button 
                      className="action-btn secondary"
                      onClick={() => loadClassStudents(selectedClass!.id)}
                    >
                      🔄 Refresh List
                    </button>
                    <button 
                      className="action-btn outline"
                      onClick={() => {/* TODO: Export student list */}}
                    >
                      📊 Export List
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {currentView === 'attendance-dashboard' && selectedClass && (
          <div className="attendance-section">
            {selectedClass.status === 'active' ? (
              <AttendanceDashboard 
                session={selectedClass}
                onSessionUpdate={handleSessionUpdate}
              />
            ) : (
              <div className="inactive-session">
                <h3>Session Not Active</h3>
                <p>This class session is not currently active.</p>
                <button 
                  className="action-btn primary"
                  onClick={() => {/* TODO: Reactivate session */}}
                >
                  Reactivate Session
                </button>
              </div>
            )}
          </div>
        )}

        {currentView === 'reports' && (
          <div className="reports-section">
            <div className="reports-header">
              <h2>Reports & Analytics</h2>
              <p>Analyze attendance patterns and generate reports</p>
            </div>

            <div className="report-cards">
              <div className="report-card">
                <div className="report-icon">📊</div>
                <h3>Attendance Summary</h3>
                <p>Overall attendance statistics for all classes</p>
                <div className="report-stats">
                  <div className="stat">
                    <span className="stat-number">{totalClasses}</span>
                    <span className="stat-label">Total Classes</span>
                  </div>
                  <div className="stat">
                    <span className="stat-number">{totalStudents}</span>
                    <span className="stat-label">Students</span>
                  </div>
                </div>
                <button className="report-btn">Generate Report</button>
              </div>

              <div className="report-card">
                <div className="report-icon">📈</div>
                <h3>Attendance Trends</h3>
                <p>View attendance trends over time</p>
                <div className="trend-chart">
                  <div className="chart-placeholder">
                    📈 Trend analysis coming soon...
                  </div>
                </div>
                <button className="report-btn">View Trends</button>
              </div>

              <div className="report-card">
                <div className="report-icon">👥</div>
                <h3>Student Performance</h3>
                <p>Individual student attendance records</p>
                <div className="performance-list">
                  <div className="performance-item">
                    <span>Average attendance rate: 85%</span>
                  </div>
                  <div className="performance-item">
                    <span>Most active class: {activeClasses[0]?.name || 'N/A'}</span>
                  </div>
                </div>
                <button className="report-btn">View Details</button>
              </div>

              <div className="report-card">
                <div className="report-icon">📋</div>
                <h3>Export Data</h3>
                <p>Export attendance data in various formats</p>
                <div className="export-options">
                  <button className="export-btn">📄 Export CSV</button>
                  <button className="export-btn">📊 Export Excel</button>
                  <button className="export-btn">📑 Export PDF</button>
                </div>
              </div>
            </div>
          </div>
        )}

        {currentView === 'settings' && (
          <div className="settings-section">
            <div className="settings-header">
              <h2>Settings</h2>
              <p>Configure your preferences and account settings</p>
            </div>

            <div className="settings-panels">
              <div className="settings-panel">
                <h3>Profile Settings</h3>
                <div className="setting-group">
                  <label>Display Name</label>
                  <input 
                    type="text" 
                    value={user?.full_name || ''} 
                    className="setting-input"
                    readOnly
                  />
                </div>
                <div className="setting-group">
                  <label>Email</label>
                  <input 
                    type="email" 
                    value={user?.email || ''} 
                    className="setting-input"
                    readOnly
                  />
                </div>
                <div className="setting-group">
                  <label>Username</label>
                  <input 
                    type="text" 
                    value={user?.username || ''} 
                    className="setting-input"
                    readOnly
                  />
                </div>
                <button className="setting-btn">Update Profile</button>
              </div>

              <div className="settings-panel">
                <h3>Class Preferences</h3>
                <div className="setting-group">
                  <label>
                    <input type="checkbox" defaultChecked />
                    Allow late join by default
                  </label>
                </div>
                <div className="setting-group">
                  <label>
                    <input type="checkbox" defaultChecked />
                    Require verification code
                  </label>
                </div>
                <div className="setting-group">
                  <label>Default class duration</label>
                  <select className="setting-select">
                    <option value="30">30 minutes</option>
                    <option value="45" selected>45 minutes</option>
                    <option value="60">60 minutes</option>
                    <option value="90">90 minutes</option>
                  </select>
                </div>
                <button className="setting-btn">Save Preferences</button>
              </div>

              <div className="settings-panel">
                <h3>Notifications</h3>
                <div className="setting-group">
                  <label>
                    <input type="checkbox" defaultChecked />
                    Email notifications for new student joins
                  </label>
                </div>
                <div className="setting-group">
                  <label>
                    <input type="checkbox" defaultChecked />
                    SMS notifications for class reminders
                  </label>
                </div>
                <div className="setting-group">
                  <label>
                    <input type="checkbox" />
                    Weekly attendance reports
                  </label>
                </div>
                <button className="setting-btn">Update Notifications</button>
              </div>

              <div className="settings-panel">
                <h3>Security</h3>
                <div className="setting-group">
                  <label>Change Password</label>
                  <button className="setting-btn secondary">Change Password</button>
                </div>
                <div className="setting-group">
                  <label>Two-Factor Authentication</label>
                  <button className="setting-btn secondary">Enable 2FA</button>
                </div>
                <div className="setting-group">
                  <label>Active Sessions</label>
                  <button className="setting-btn secondary">Manage Sessions</button>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};