import React, { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { 
  getSystemStats, 
  getRecentUsers, 
  getActiveClassesAdmin, 
  getAllUsers, 
  getAllClassesAdmin,
  createUser,
  updateUser,
  toggleUserStatus,
  searchUsers,
  exportUsers,
  exportClasses,
  endClassSession,
  getClassSession
} from '../services/api';
import { SystemStats, User, AdminClassSession } from '../types/api';
import './AdminDashboard.css';

type AdminView = 'dashboard' | 'users' | 'classes' | 'reports' | 'settings';

export const AdminDashboard: React.FC = () => {
  const { user } = useAuth();
  const [currentView, setCurrentView] = useState<AdminView>('dashboard');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');
  
  // Real data from API
  const [systemStats, setSystemStats] = useState<SystemStats | null>(null);
  const [recentUsers, setRecentUsers] = useState<User[]>([]);
  const [activeClasses, setActiveClasses] = useState<AdminClassSession[]>([]);
  const [allUsers, setAllUsers] = useState<User[]>([]);
  const [allClasses, setAllClasses] = useState<AdminClassSession[]>([]);
  
  // User management state
  const [showUserModal, setShowUserModal] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [userFilters, setUserFilters] = useState({
    role: '',
    status: '',
    search: ''
  });
  const [userFormData, setUserFormData] = useState({
    full_name: '',
    username: '',
    email: '',
    password: '',
    role: 'student',
    is_active: true
  });
  
  // Class management state
  const [selectedClass, setSelectedClass] = useState<AdminClassSession | null>(null);
  const [showClassDetailsModal, setShowClassDetailsModal] = useState(false);

  // Load dashboard data
  const loadDashboardData = async () => {
    setLoading(true);
    setError('');
    try {
      const [statsData, usersData, classesData] = await Promise.all([
        getSystemStats(),
        getRecentUsers(10),
        getActiveClassesAdmin(10)
      ]);
      
      setSystemStats(statsData);
      setRecentUsers(usersData);
      setActiveClasses(classesData);
    } catch (err: any) {
      setError(err.message || 'Failed to load dashboard data');
      console.error('Dashboard data load error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Load user management data
  const loadUsersData = async (role?: string, isActive?: boolean) => {
    setLoading(true);
    setError('');
    try {
      const usersData = await getAllUsers(role, isActive, 50, 0);
      setAllUsers(usersData);
    } catch (err: any) {
      setError(err.message || 'Failed to load users data');
      console.error('Users data load error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Load classes management data
  const loadClassesData = async (statusFilter?: string) => {
    setLoading(true);
    setError('');
    try {
      const classesData = await getAllClassesAdmin(statusFilter, 50, 0);
      setAllClasses(classesData);
    } catch (err: any) {
      setError(err.message || 'Failed to load classes data');
      console.error('Classes data load error:', err);
    } finally {
      setLoading(false);
    }
  };

  // User management functions
  const handleAddUser = () => {
    setEditingUser(null);
    setUserFormData({
      full_name: '',
      username: '',
      email: '',
      password: '',
      role: 'student',
      is_active: true
    });
    setShowUserModal(true);
  };

  const handleEditUser = (user: User) => {
    setEditingUser(user);
    setUserFormData({
      full_name: user.full_name,
      username: user.username,
      email: user.email,
      password: '', // Don't pre-fill password
      role: user.role,
      is_active: user.is_active
    });
    setShowUserModal(true);
  };

  const handleSaveUser = async () => {
    setError('');
    try {
      if (editingUser) {
        // Update existing user
        const updateData = { ...userFormData };
        if (!updateData.password) {
          delete updateData.password; // Don't update password if empty
        }
        await updateUser(editingUser.id, updateData);
      } else {
        // Create new user
        await createUser(userFormData);
      }
      setShowUserModal(false);
      await loadUsersData(userFilters.role, userFilters.status ? userFilters.status === 'active' : undefined);
    } catch (err: any) {
      setError(err.message || 'Failed to save user');
    }
  };

  const handleToggleUserStatus = async (userId: number) => {
    setError('');
    try {
      await toggleUserStatus(userId);
      await loadUsersData(userFilters.role, userFilters.status ? userFilters.status === 'active' : undefined);
    } catch (err: any) {
      setError(err.message || 'Failed to toggle user status');
    }
  };

  const handleSearchUsers = async () => {
    setError('');
    try {
      const isActiveFilter = userFilters.status ? userFilters.status === 'active' : undefined;
      const usersData = await searchUsers(userFilters.search, userFilters.role, isActiveFilter, 50, 0);
      setAllUsers(usersData);
    } catch (err: any) {
      setError(err.message || 'Failed to search users');
    }
  };

  const handleExportUsers = async () => {
    setError('');
    try {
      const isActiveFilter = userFilters.status ? userFilters.status === 'active' : undefined;
      await exportUsers('csv', userFilters.role, isActiveFilter);
    } catch (err: any) {
      setError(err.message || 'Failed to export users');
    }
  };

  const handleFilterChange = (filterType: string, value: string) => {
    const newFilters = { ...userFilters, [filterType]: value };
    setUserFilters(newFilters);
    
    // Auto-search when filters change
    if (filterType !== 'search') {
      const isActiveFilter = newFilters.status ? newFilters.status === 'active' : undefined;
      searchUsers(newFilters.search, newFilters.role, isActiveFilter, 50, 0)
        .then(setAllUsers)
        .catch(err => setError(err.message));
    }
  };

  // Class management functions
  const handleViewClassDetails = async (classItem: AdminClassSession) => {
    setSelectedClass(classItem);
    setShowClassDetailsModal(true);
  };

  const handleEndClass = async (classId: number) => {
    setError('');
    try {
      if (window.confirm('Are you sure you want to end this class? This action cannot be undone.')) {
        await endClassSession(classId);
        await loadClassesData(); // Refresh the classes list
      }
    } catch (err: any) {
      setError(err.message || 'Failed to end class');
    }
  };

  const handleRefreshClasses = () => {
    loadClassesData();
  };

  const handleExportClasses = async () => {
    setError('');
    try {
      await exportClasses('csv');
    } catch (err: any) {
      setError(err.message || 'Failed to export classes');
    }
  };

  // Load initial data
  useEffect(() => {
    loadDashboardData();
  }, []);

  // Load data when view changes
  useEffect(() => {
    switch (currentView) {
      case 'dashboard':
        loadDashboardData();
        break;
      case 'users':
        loadUsersData();
        break;
      case 'classes':
        loadClassesData();
        break;
    }
  }, [currentView]);

  // Format date
  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString() + ' ' + 
           new Date(dateString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  // Dashboard Overview
  const renderDashboard = () => (
    <div className="admin-overview">
      <div className="welcome-section">
        <h2>System Overview</h2>
        <p>Monitor and manage your attendance system</p>
      </div>

      {/* System Statistics */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon">👥</div>
          <div className="stat-content">
            <div className="stat-number">{systemStats?.total_users || 0}</div>
            <div className="stat-label">Total Users</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">👨‍🏫</div>
          <div className="stat-content">
            <div className="stat-number">{systemStats?.total_teachers || 0}</div>
            <div className="stat-label">Teachers</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">👨‍🎓</div>
          <div className="stat-content">
            <div className="stat-number">{systemStats?.total_students || 0}</div>
            <div className="stat-label">Students</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">📚</div>
          <div className="stat-content">
            <div className="stat-number">{systemStats?.active_classes || 0}</div>
            <div className="stat-label">Active Classes</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">✅</div>
          <div className="stat-content">
            <div className="stat-number">{systemStats?.total_attendance_records || 0}</div>
            <div className="stat-label">Total Records</div>
          </div>
        </div>
        
        <div className="stat-card">
          <div className="stat-icon">📈</div>
          <div className="stat-content">
            <div className="stat-number">{systemStats?.attendance_rate || 0}%</div>
            <div className="stat-label">Attendance Rate</div>
          </div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className="quick-actions">
        <h3>Quick Actions</h3>
        <div className="action-grid">
          <button 
            className="action-card primary"
            onClick={() => setCurrentView('users')}
          >
            <div className="action-icon">👥</div>
            <div className="action-content">
              <h4>Manage Users</h4>
              <p>Add, edit, or deactivate users</p>
            </div>
          </button>
          
          <button 
            className="action-card secondary"
            onClick={() => setCurrentView('classes')}
          >
            <div className="action-icon">📚</div>
            <div className="action-content">
              <h4>Monitor Classes</h4>
              <p>View active classes and attendance</p>
            </div>
          </button>
          
          <button 
            className="action-card secondary"
            onClick={() => setCurrentView('reports')}
          >
            <div className="action-icon">📊</div>
            <div className="action-content">
              <h4>Generate Reports</h4>
              <p>View system analytics and reports</p>
            </div>
          </button>
          
          <button 
            className="action-card secondary"
            onClick={() => setCurrentView('settings')}
          >
            <div className="action-icon">⚙️</div>
            <div className="action-content">
              <h4>System Settings</h4>
              <p>Configure system preferences</p>
            </div>
          </button>
        </div>
      </div>

      {/* Recent Activity */}
      <div className="dashboard-row">
        <div className="recent-users">
          <h3>Recent Users</h3>
          <div className="users-list">
            {recentUsers.map(user => (
              <div key={user.id} className="user-item">
                <div className="user-info">
                  <h4>{user.full_name}</h4>
                  <p className="user-email">{user.email}</p>
                  <p className="user-role">{user.role}</p>
                </div>
                <div className="user-status">
                  <span className={`status-badge ${user.is_active ? 'active' : 'inactive'}`}>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </span>
                  {user.last_login && (
                    <p className="last-login">Last: {formatDate(user.last_login)}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="active-classes">
          <h3>Active Classes</h3>
          <div className="classes-list">
            {activeClasses.map(classItem => (
              <div key={classItem.id} className="class-item">
                <div className="class-info">
                  <h4>{classItem.name}</h4>
                  <p className="teacher-name">{classItem.teacher_name}</p>
                  <p className="class-time">{formatDate(classItem.start_time)}</p>
                </div>
                <div className="class-stats">
                  <span className="student-count">👥 {classItem.present_count}</span>
                  <span className={`status-badge ${classItem.status}`}>
                    {classItem.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );

  // User Management
  const renderUsers = () => (
    <div className="users-management">
      <div className="section-header">
        <h2>User Management</h2>
        <div className="header-actions">
          <button className="btn-primary" onClick={handleAddUser}>Add New User</button>
          <button className="btn-secondary" onClick={handleExportUsers}>Export Users</button>
        </div>
      </div>

      <div className="users-filters">
        <div className="filter-group">
          <label>Role:</label>
          <select 
            value={userFilters.role} 
            onChange={(e) => handleFilterChange('role', e.target.value)}
          >
            <option value="">All Roles</option>
            <option value="teacher">Teachers</option>
            <option value="student">Students</option>
            <option value="admin">Administrators</option>
          </select>
        </div>
        <div className="filter-group">
          <label>Status:</label>
          <select 
            value={userFilters.status} 
            onChange={(e) => handleFilterChange('status', e.target.value)}
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <div className="filter-group">
          <input 
            type="text" 
            placeholder="Search users..." 
            className="search-input"
            value={userFilters.search}
            onChange={(e) => handleFilterChange('search', e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSearchUsers()}
          />
          <button className="btn-search" onClick={handleSearchUsers}>Search</button>
        </div>
      </div>

      <div className="users-table">
        <div className="table-header">
          <div className="col-name">Name</div>
          <div className="col-email">Email</div>
          <div className="col-role">Role</div>
          <div className="col-status">Status</div>
          <div className="col-last-login">Last Login</div>
          <div className="col-actions">Actions</div>
        </div>
        
        {allUsers.map(user => (
          <div key={user.id} className="table-row">
            <div className="col-name">{user.full_name}</div>
            <div className="col-email">{user.email}</div>
            <div className="col-role">
              <span className={`role-badge ${user.role}`}>
                {user.role}
              </span>
            </div>
            <div className="col-status">
              <span className={`status-badge ${user.is_active ? 'active' : 'inactive'}`}>
                {user.is_active ? 'Active' : 'Inactive'}
              </span>
            </div>
            <div className="col-last-login">
              {user.last_login ? formatDate(user.last_login) : 'Never'}
            </div>
            <div className="col-actions">
              <button className="btn-edit" onClick={() => handleEditUser(user)}>Edit</button>
              <button className="btn-toggle" onClick={() => handleToggleUserStatus(user.id)}>
                {user.is_active ? 'Deactivate' : 'Activate'}
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* User Modal */}
      {showUserModal && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h3>{editingUser ? 'Edit User' : 'Add New User'}</h3>
              <button className="modal-close" onClick={() => setShowUserModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>Full Name:</label>
                <input
                  type="text"
                  value={userFormData.full_name}
                  onChange={(e) => setUserFormData({...userFormData, full_name: e.target.value})}
                  placeholder="Enter full name"
                />
              </div>
              <div className="form-group">
                <label>Username:</label>
                <input
                  type="text"
                  value={userFormData.username}
                  onChange={(e) => setUserFormData({...userFormData, username: e.target.value})}
                  placeholder="Enter username"
                />
              </div>
              <div className="form-group">
                <label>Email:</label>
                <input
                  type="email"
                  value={userFormData.email}
                  onChange={(e) => setUserFormData({...userFormData, email: e.target.value})}
                  placeholder="Enter email address"
                />
              </div>
              <div className="form-group">
                <label>Password:</label>
                <input
                  type="password"
                  value={userFormData.password}
                  onChange={(e) => setUserFormData({...userFormData, password: e.target.value})}
                  placeholder={editingUser ? "Leave blank to keep current password" : "Enter password"}
                />
              </div>
              <div className="form-group">
                <label>Role:</label>
                <select
                  value={userFormData.role}
                  onChange={(e) => setUserFormData({...userFormData, role: e.target.value})}
                >
                  <option value="student">Student</option>
                  <option value="teacher">Teacher</option>
                  <option value="admin">Administrator</option>
                </select>
              </div>
              <div className="form-group">
                <label>
                  <input
                    type="checkbox"
                    checked={userFormData.is_active}
                    onChange={(e) => setUserFormData({...userFormData, is_active: e.target.checked})}
                  />
                  Active User
                </label>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setShowUserModal(false)}>Cancel</button>
              <button className="btn-primary" onClick={handleSaveUser}>
                {editingUser ? 'Update User' : 'Create User'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // Class Management
  const renderClasses = () => (
    <div className="classes-management">
      <div className="section-header">
        <h2>Class Monitoring</h2>
        <div className="header-actions">
          <button className="btn-secondary" onClick={handleRefreshClasses}>Refresh</button>
          <button className="btn-secondary" onClick={handleExportClasses}>Export Data</button>
        </div>
      </div>

      <div className="classes-grid">
        {allClasses.map(classItem => (
          <div key={classItem.id} className="class-card">
            <div className="class-header">
              <h3>{classItem.name}</h3>
              <span className={`status-badge ${classItem.status}`}>
                {classItem.status}
              </span>
            </div>
            <div className="class-details">
              <p><strong>Teacher:</strong> {classItem.teacher_name}</p>
              <p><strong>Students:</strong> {classItem.present_count}</p>
              <p><strong>Started:</strong> {formatDate(classItem.start_time)}</p>
            </div>
            <div className="class-actions">
              <button className="btn-view" onClick={() => handleViewClassDetails(classItem)}>
                View Details
              </button>
              {classItem.status === 'active' && (
                <button className="btn-end" onClick={() => handleEndClass(classItem.id)}>
                  End Class
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Class Details Modal */}
      {showClassDetailsModal && selectedClass && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h3>Class Details: {selectedClass.name}</h3>
              <button className="modal-close" onClick={() => setShowClassDetailsModal(false)}>×</button>
            </div>
            <div className="modal-body">
              <div className="class-details-expanded">
                <div className="detail-row">
                  <strong>Teacher:</strong> {selectedClass.teacher_name}
                </div>
                <div className="detail-row">
                  <strong>Status:</strong> 
                  <span className={`status-badge ${selectedClass.status}`}>
                    {selectedClass.status}
                  </span>
                </div>
                <div className="detail-row">
                  <strong>Started:</strong> {formatDate(selectedClass.start_time)}
                </div>
                {selectedClass.end_time && (
                  <div className="detail-row">
                    <strong>Ended:</strong> {formatDate(selectedClass.end_time)}
                  </div>
                )}
                <div className="detail-row">
                  <strong>Present Students:</strong> {selectedClass.present_count}
                </div>
                {selectedClass.qr_code && (
                  <div className="detail-row">
                    <strong>QR Code:</strong>
                    <img src={selectedClass.qr_code} alt="QR Code" style={{maxWidth: '200px', marginTop: '10px'}} />
                  </div>
                )}
                {selectedClass.verification_code && (
                  <div className="detail-row">
                    <strong>Verification Code:</strong> 
                    <code style={{background: '#f0f0f0', padding: '5px', borderRadius: '3px'}}>
                      {selectedClass.verification_code}
                    </code>
                  </div>
                )}
                {selectedClass.share_link && (
                  <div className="detail-row">
                    <strong>Share Link:</strong>
                    <a href={selectedClass.share_link} target="_blank" rel="noopener noreferrer">
                      {selectedClass.share_link}
                    </a>
                  </div>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setShowClassDetailsModal(false)}>
                Close
              </button>
              {selectedClass.status === 'active' && (
                <button className="btn-danger" onClick={() => {
                  handleEndClass(selectedClass.id);
                  setShowClassDetailsModal(false);
                }}>
                  End Class
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // Reports
  const renderReports = () => (
    <div className="reports-section">
      <div className="section-header">
        <h2>System Reports</h2>
      </div>

      <div className="reports-grid">
        <div className="report-card">
          <h3>📊 Attendance Summary</h3>
          <p>Overall attendance statistics and trends</p>
          <button className="btn-generate">Generate Report</button>
        </div>
        
        <div className="report-card">
          <h3>👥 User Activity</h3>
          <p>User login patterns and system usage</p>
          <button className="btn-generate">Generate Report</button>
        </div>
        
        <div className="report-card">
          <h3>📚 Class Performance</h3>
          <p>Individual class attendance rates</p>
          <button className="btn-generate">Generate Report</button>
        </div>
        
        <div className="report-card">
          <h3>📈 System Usage</h3>
          <p>System performance and usage metrics</p>
          <button className="btn-generate">Generate Report</button>
        </div>
      </div>
    </div>
  );

  // Settings
  const renderSettings = () => (
    <div className="settings-section">
      <div className="section-header">
        <h2>System Settings</h2>
      </div>

      <div className="settings-grid">
        <div className="setting-group">
          <h3>General Settings</h3>
          <div className="setting-item">
            <label>System Name</label>
            <input type="text" value="Student Attendance System" />
          </div>
          <div className="setting-item">
            <label>Default Session Duration (minutes)</label>
            <input type="number" value="60" />
          </div>
          <div className="setting-item">
            <label>Allow Late Join by Default</label>
            <input type="checkbox" defaultChecked />
          </div>
        </div>

        <div className="setting-group">
          <h3>Security Settings</h3>
          <div className="setting-item">
            <label>Session Timeout (minutes)</label>
            <input type="number" value="30" />
          </div>
          <div className="setting-item">
            <label>Require Email Verification</label>
            <input type="checkbox" />
          </div>
          <div className="setting-item">
            <label>Enable Two-Factor Authentication</label>
            <input type="checkbox" />
          </div>
        </div>

        <div className="setting-group">
          <h3>Notification Settings</h3>
          <div className="setting-item">
            <label>Email Notifications</label>
            <input type="checkbox" defaultChecked />
          </div>
          <div className="setting-item">
            <label>SMS Notifications</label>
            <input type="checkbox" />
          </div>
          <div className="setting-item">
            <label>System Alerts</label>
            <input type="checkbox" defaultChecked />
          </div>
        </div>

        <div className="setting-group">
          <h3>Data & Privacy</h3>
          <div className="setting-item">
            <label>Data Retention Period (days)</label>
            <input type="number" value="365" />
          </div>
          <div className="setting-item">
            <label>FERPA Compliance Mode</label>
            <input type="checkbox" defaultChecked />
          </div>
          <div className="setting-item">
            <label>Auto-Export Reports</label>
            <input type="checkbox" />
          </div>
        </div>
      </div>

      <div className="settings-actions">
        <button className="btn-primary">Save Settings</button>
        <button className="btn-secondary">Reset to Defaults</button>
      </div>
    </div>
  );

  return (
    <div className="admin-dashboard">
      {/* Navigation */}
      <div className="dashboard-nav">
        <div className="nav-header">
          <h1>Admin Panel</h1>
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
            className={`nav-item ${currentView === 'users' ? 'active' : ''}`}
            onClick={() => setCurrentView('users')}
          >
            <span className="nav-icon">👥</span>
            Users
          </button>
          <button 
            className={`nav-item ${currentView === 'classes' ? 'active' : ''}`}
            onClick={() => setCurrentView('classes')}
          >
            <span className="nav-icon">📚</span>
            Classes
          </button>
          <button 
            className={`nav-item ${currentView === 'reports' ? 'active' : ''}`}
            onClick={() => setCurrentView('reports')}
          >
            <span className="nav-icon">📊</span>
            Reports
          </button>
          <button 
            className={`nav-item ${currentView === 'settings' ? 'active' : ''}`}
            onClick={() => setCurrentView('settings')}
          >
            <span className="nav-icon">⚙️</span>
            Settings
          </button>
        </nav>
      </div>

      {/* Main Content */}
      <main className="dashboard-content">
        {/* Loading State */}
        {loading && (
          <div className="loading-state">
            <div className="loading-spinner"></div>
            <p>Loading data...</p>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="error-state">
            <p className="error-message">{error}</p>
            <button onClick={() => {
              setError('');
              switch (currentView) {
                case 'dashboard':
                  loadDashboardData();
                  break;
                case 'users':
                  loadUsersData();
                  break;
                case 'classes':
                  loadClassesData();
                  break;
              }
            }}>
              Retry
            </button>
          </div>
        )}

        {/* Content */}
        {!loading && !error && (
          <>
            {currentView === 'dashboard' && renderDashboard()}
            {currentView === 'users' && renderUsers()}
            {currentView === 'classes' && renderClasses()}
            {currentView === 'reports' && renderReports()}
            {currentView === 'settings' && renderSettings()}
          </>
        )}
      </main>
    </div>
  );
};