import React from 'react';
import { useAuth } from '../hooks/useAuth';
import './Navigation.css';

interface NavigationProps {
  onShowLogin: () => void;
  onShowRegister: () => void;
}

export const Navigation: React.FC<NavigationProps> = ({ onShowLogin, onShowRegister }) => {
  const { isAuthenticated, user, logout } = useAuth();

  return (
    <nav className="navigation">
      <div className="nav-container">
        <div className="nav-brand">
          <h1>Student Attendance System</h1>
        </div>
        
        <div className="nav-actions">
          {isAuthenticated && user ? (
            <div className="user-menu">
              <span className="welcome-text">
                Welcome, {user.full_name}
                <span className="user-role">({user.role})</span>
              </span>
              <button onClick={logout} className="logout-button">
                Sign Out
              </button>
            </div>
          ) : (
            <div className="auth-buttons">
              <button onClick={onShowLogin} className="login-button">
                Sign In
              </button>
              <button onClick={onShowRegister} className="register-button">
                Sign Up
              </button>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};