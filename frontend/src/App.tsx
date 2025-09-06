import React, { useState } from 'react'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { Navigation } from './components/Navigation'
import { LoginForm } from './components/LoginForm'
import { RegisterForm } from './components/RegisterForm'
import { AttendanceDashboard } from './components/AttendanceDashboard'
import './App.css'

// Mock data for development
const mockSession = {
  id: '1',
  name: 'Computer Science 101',
  code: 'CS101A',
  teacher_id: 'teacher1',
  status: 'active' as const,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  expires_at: new Date(Date.now() + 3600000).toISOString(), // 1 hour from now
  qr_code: 'sample-qr-code',
  join_link: 'http://localhost:3000/join/CS101A',
  verification_code: '123456',
  student_count: 0,
  attendance_data: []
}

type ViewMode = 'dashboard' | 'login' | 'register';

function AppContent() {
  const { isAuthenticated, isLoading } = useAuth();
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard');
  const [session] = useState(mockSession);

  if (isLoading) {
    return (
      <div className="App">
        <div className="loading">Loading...</div>
      </div>
    );
  }

  const handleShowLogin = () => setViewMode('login');
  const handleShowRegister = () => setViewMode('register');
  const handleShowDashboard = () => setViewMode('dashboard');

  return (
    <div className="App">
      <Navigation 
        onShowLogin={handleShowLogin}
        onShowRegister={handleShowRegister}
      />
      
      <main>
        {!isAuthenticated ? (
          <>
            {viewMode === 'login' && (
              <LoginForm onSwitchToRegister={handleShowRegister} />
            )}
            {viewMode === 'register' && (
              <RegisterForm onSwitchToLogin={handleShowLogin} />
            )}
            {viewMode === 'dashboard' && (
              <div className="welcome-message">
                <h2>Welcome to Student Attendance System</h2>
                <p>Please sign in or create an account to access the attendance dashboard.</p>
                <div className="welcome-actions">
                  <button onClick={handleShowLogin} className="primary-button">
                    Sign In
                  </button>
                  <button onClick={handleShowRegister} className="secondary-button">
                    Sign Up
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <AttendanceDashboard 
            session={session}
            onSessionUpdate={(updates) => console.log('Session updated:', updates)}
          />
        )}
      </main>
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}

export default App