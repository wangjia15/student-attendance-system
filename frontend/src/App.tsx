import React, { useState } from 'react'
import { AuthProvider, useAuth } from './hooks/useAuth'
import { Navigation } from './components/Navigation'
import { LoginForm } from './components/LoginForm'
import { RegisterForm } from './components/RegisterForm'
import { StudentDashboard } from './components/StudentDashboard'
import { TeacherMainDashboard } from './components/TeacherMainDashboard'
import { AdminDashboard } from './components/AdminDashboard'
import './App.css'


type ViewMode = 'dashboard' | 'login' | 'register';

function AppContent() {
  const { isAuthenticated, isLoading, user } = useAuth();
  const [viewMode, setViewMode] = useState<ViewMode>('dashboard');

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
          // Show different dashboard based on user role
          user?.role === 'teacher' ? (
            <TeacherMainDashboard />
          ) : user?.role === 'admin' ? (
            <AdminDashboard />
          ) : (
            // For students, show the student dashboard
            <StudentDashboard />
          )
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