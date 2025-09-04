import React, { useState, useEffect } from 'react';
import { MobileClassCreation, useMobileClassCreation } from './MobileClassCreation';
import { TeacherAttendanceDashboard } from './TeacherAttendanceDashboard';
import { StudentCheckIn } from './StudentCheckIn';
import { ClassSessionResponse } from '../types/api';
import { deepLinkHandler, DeepLinkData } from '../utils/deepLinking';
import './MobileApp.css';

interface MobileAppProps {
  initialView?: 'create' | 'join' | 'dashboard';
  classId?: string;
  code?: string;
  token?: string;
}

type AppView = 'welcome' | 'create' | 'join' | 'dashboard' | 'success';

export const MobileApp: React.FC<MobileAppProps> = ({
  initialView = 'welcome',
  classId,
  code,
  token
}) => {
  const [currentView, setCurrentView] = useState<AppView>(initialView);
  const [currentSession, setCurrentSession] = useState<ClassSessionResponse | null>(null);
  const [joinData, setJoinData] = useState<{ classId?: string; code?: string; token?: string }>({
    classId,
    code,
    token
  });

  const { isMobile, orientation, isOnline, canShare } = useMobileClassCreation();

  // Handle deep links
  useEffect(() => {
    const handleDeepLink = (data: DeepLinkData) => {
      console.log('Deep link received:', data);
      
      switch (data.type) {
        case 'join_class':
          setJoinData({
            classId: data.classId,
            code: data.code,
            token: data.token
          });
          setCurrentView('join');
          break;
          
        case 'view_session':
          setJoinData({ classId: data.classId });
          setCurrentView('dashboard');
          break;
          
        case 'create_class':
          setCurrentView('create');
          break;
          
        default:
          // Unknown deep link, stay on current view or go to welcome
          if (currentView === 'welcome') {
            // Already on welcome, no action needed
          }
          break;
      }
    };

    const unsubscribe = deepLinkHandler.onDeepLink(handleDeepLink);
    return unsubscribe;
  }, [currentView]);

  // Handle successful class creation
  const handleSessionCreated = (session: ClassSessionResponse) => {
    setCurrentSession(session);
    setCurrentView('success');
  };

  // Handle successful student join
  const handleJoinSuccess = (response: any) => {
    console.log('Student joined successfully:', response);
    setCurrentView('success');
  };

  // Handle navigation
  const handleNavigation = (view: AppView, data?: any) => {
    setCurrentView(view);
    if (data) {
      if (data.classId || data.code || data.token) {
        setJoinData(data);
      }
      if (data.session) {
        setCurrentSession(data.session);
      }
    }
  };

  // Handle sharing created session
  const handleShare = async (session: ClassSessionResponse) => {
    const shareUrl = `${window.location.origin}/join/${session.id}?code=${session.verification_code}`;
    const shareData = {
      title: `Join ${session.name}`,
      text: `Join my class "${session.name}" - Use code: ${session.verification_code}`,
      url: shareUrl
    };

    if (canShare) {
      try {
        await navigator.share(shareData);
      } catch (error) {
        if (error instanceof Error && error.name !== 'AbortError') {
          // Fallback to clipboard
          navigator.clipboard?.writeText(`${shareData.text}\n${shareData.url}`);
        }
      }
    } else {
      // Fallback to clipboard
      navigator.clipboard?.writeText(`${shareData.text}\n${shareData.url}`);
    }
  };

  // Render current view
  const renderCurrentView = () => {
    switch (currentView) {
      case 'welcome':
        return (
          <div className="welcome-view">
            <div className="welcome-content">
              <div className="app-logo">
                <span className="logo-icon">📋</span>
                <h1>Attendance System</h1>
                <p>Create classes and track attendance instantly</p>
              </div>
              
              <div className="welcome-actions">
                <button
                  className="action-button primary"
                  onClick={() => setCurrentView('create')}
                >
                  <span className="action-icon">➕</span>
                  Create New Class
                </button>
                
                <button
                  className="action-button secondary"
                  onClick={() => setCurrentView('join')}
                >
                  <span className="action-icon">🎯</span>
                  Join Existing Class
                </button>
                
                <button
                  className="action-button tertiary"
                  onClick={() => setCurrentView('dashboard')}
                >
                  <span className="action-icon">📊</span>
                  View Dashboard
                </button>
              </div>

              {!isOnline && (
                <div className="offline-notice">
                  <span className="offline-icon">📴</span>
                  <p>You're offline. Some features may be limited.</p>
                </div>
              )}
            </div>
          </div>
        );

      case 'create':
        return (
          <MobileClassCreation
            onSessionCreated={handleSessionCreated}
            onCancel={() => setCurrentView('welcome')}
          />
        );

      case 'join':
        return (
          <div className="join-view">
            <div className="view-header">
              <button 
                className="back-button"
                onClick={() => setCurrentView('welcome')}
              >
                ← Back
              </button>
              <h2>Join Class</h2>
            </div>
            <StudentCheckIn
              initialClassId={joinData.classId}
              initialCode={joinData.code}
              initialToken={joinData.token}
              onJoinSuccess={handleJoinSuccess}
            />
          </div>
        );

      case 'dashboard':
        return (
          <div className="dashboard-view">
            <div className="view-header">
              <button 
                className="back-button"
                onClick={() => setCurrentView('welcome')}
              >
                ← Back
              </button>
              <h2>Dashboard</h2>
            </div>
            <TeacherAttendanceDashboard />
          </div>
        );

      case 'success':
        return (
          <div className="success-view">
            <div className="success-content">
              <div className="success-icon">✅</div>
              <h2>Success!</h2>
              
              {currentSession ? (
                <div className="session-details">
                  <p>Class "{currentSession.name}" created successfully!</p>
                  <div className="session-info">
                    <div className="info-item">
                      <strong>Class Code:</strong>
                      <span className="code-display">{currentSession.verification_code}</span>
                    </div>
                    <div className="info-item">
                      <strong>Students can join at:</strong>
                      <span className="url-display">
                        {window.location.origin}/join/{currentSession.id}
                      </span>
                    </div>
                  </div>
                  
                  <div className="success-actions">
                    {canShare && (
                      <button
                        className="action-button primary"
                        onClick={() => handleShare(currentSession)}
                      >
                        📤 Share Class
                      </button>
                    )}
                    
                    <button
                      className="action-button secondary"
                      onClick={() => handleNavigation('dashboard', { session: currentSession })}
                    >
                      📊 View Dashboard
                    </button>
                    
                    <button
                      className="action-button tertiary"
                      onClick={() => setCurrentView('welcome')}
                    >
                      🏠 Back to Home
                    </button>
                  </div>
                </div>
              ) : (
                <div className="join-success">
                  <p>You've successfully joined the class!</p>
                  <button
                    className="action-button primary"
                    onClick={() => setCurrentView('welcome')}
                  >
                    🏠 Back to Home
                  </button>
                </div>
              )}
            </div>
          </div>
        );

      default:
        return <div>Unknown view</div>;
    }
  };

  return (
    <div className={`mobile-app ${orientation} ${isMobile ? 'mobile' : 'desktop'}`}>
      {renderCurrentView()}
    </div>
  );
};

// Utility function to initialize the mobile app with URL parameters
export const initializeMobileApp = (): MobileAppProps => {
  const urlParams = new URLSearchParams(window.location.search);
  const pathname = window.location.pathname;
  
  // Parse URL for initial state
  let initialView: 'create' | 'join' | 'dashboard' = 'welcome';
  let classId: string | undefined;
  let code: string | undefined;
  let token: string | undefined;
  
  // Check pathname for view determination
  if (pathname.includes('/create')) {
    initialView = 'create';
  } else if (pathname.includes('/join/')) {
    initialView = 'join';
    const pathParts = pathname.split('/');
    classId = pathParts[pathParts.indexOf('join') + 1];
  } else if (pathname.includes('/dashboard')) {
    initialView = 'dashboard';
    const pathParts = pathname.split('/');
    classId = pathParts[pathParts.indexOf('dashboard') + 1];
  }
  
  // Get parameters
  code = urlParams.get('code') || undefined;
  token = urlParams.get('token') || undefined;
  
  return {
    initialView,
    classId,
    code,
    token
  };
};