// Enhanced Student Check-In Component with State Management
import React, { useState, useEffect, useRef } from 'react';
import {
  StudentCheckInProps,
  CheckInMethod,
  StudentCheckInResponse,
  CheckInValidation
} from '../types/attendance';
import { AttendanceStatus } from '../types/api';
import { useAttendanceStore, useCurrentSession, useAttendanceLoading, useAttendanceErrors, useOfflineStatus } from '../store/attendance';
import './StudentJoinInterface.css'; // Reuse existing styles

interface StudentCheckInState {
  method: CheckInMethod;
  qrToken: string;
  verificationCode: string;
  isValidating: boolean;
  validation: CheckInValidation | null;
  showSuccess: boolean;
  lastResponse: StudentCheckInResponse | null;
}

export const StudentCheckIn: React.FC<StudentCheckInProps> = ({
  classId,
  onSuccess,
  onError,
  mode = 'full'
}) => {
  // Zustand store hooks
  const { 
    checkInWithQR, 
    checkInWithCode, 
    loadClassStatus, 
    subscribeToUpdates,
    unsubscribeFromUpdates,
    clearError 
  } = useAttendanceStore();
  
  const currentSession = useCurrentSession();
  const loading = useAttendanceLoading();
  const errors = useAttendanceErrors();
  const offline = useOfflineStatus();

  // Local state
  const [state, setState] = useState<StudentCheckInState>({
    method: mode === 'qr-only' ? 'qr_code' : mode === 'code-only' ? 'verification_code' : 'verification_code',
    qrToken: '',
    verificationCode: '',
    isValidating: false,
    validation: null,
    showSuccess: false,
    lastResponse: null,
  });

  const validationTimeoutRef = useRef<NodeJS.Timeout>();

  // Auto-detect from URL parameters
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    const code = urlParams.get('code');
    
    if (token && (mode === 'full' || mode === 'qr-only')) {
      setState(prev => ({ ...prev, qrToken: token, method: 'qr_code' }));
      // Auto-join if we have a token
      handleCheckIn('qr_code', token);
    } else if (code && (mode === 'full' || mode === 'code-only')) {
      setState(prev => ({ ...prev, verificationCode: code, method: 'verification_code' }));
    }

    // Subscribe to real-time updates if classId is provided
    if (classId) {
      subscribeToUpdates(classId);
      loadClassStatus(classId);
    }

    return () => {
      if (classId) {
        unsubscribeFromUpdates(classId);
      }
      if (validationTimeoutRef.current) {
        clearTimeout(validationTimeoutRef.current);
      }
    };
  }, [classId, mode, subscribeToUpdates, unsubscribeFromUpdates, loadClassStatus]);

  // Real-time validation
  useEffect(() => {
    if (validationTimeoutRef.current) {
      clearTimeout(validationTimeoutRef.current);
    }

    if (state.method === 'verification_code' && state.verificationCode.length === 6) {
      setState(prev => ({ ...prev, isValidating: true }));
      
      validationTimeoutRef.current = setTimeout(async () => {
        try {
          // In a real implementation, this would call a validation endpoint
          const validation: CheckInValidation = {
            isValid: /^\d{6}$/.test(state.verificationCode),
            canCheckIn: true,
            isLate: false,
            lateMinutes: 0,
            errors: /^\d{6}$/.test(state.verificationCode) ? [] : ['Code must be 6 digits'],
            warnings: [],
          };

          setState(prev => ({ ...prev, validation, isValidating: false }));
        } catch (error) {
          setState(prev => ({ 
            ...prev, 
            validation: {
              isValid: false,
              canCheckIn: false,
              isLate: false,
              lateMinutes: 0,
              errors: ['Validation failed'],
              warnings: [],
            },
            isValidating: false 
          }));
        }
      }, 500);
    }
  }, [state.verificationCode, state.method]);

  const handleCheckIn = async (method: CheckInMethod = state.method, data?: string) => {
    clearError('checkIn');
    setState(prev => ({ ...prev, showSuccess: false, lastResponse: null }));

    try {
      let response: StudentCheckInResponse;

      if (method === 'qr_code') {
        const token = data || state.qrToken;
        if (!token.trim()) {
          throw new Error('QR code token is required');
        }
        response = await checkInWithQR(token);
      } else {
        const code = data || state.verificationCode;
        if (!code.trim()) {
          throw new Error('Verification code is required');
        }
        if (code.length !== 6) {
          throw new Error('Verification code must be 6 digits');
        }
        response = await checkInWithCode(code);
      }

      // Show success state
      setState(prev => ({ 
        ...prev, 
        showSuccess: true, 
        lastResponse: response 
      }));

      // Call success callback
      if (onSuccess) {
        onSuccess(response);
      }

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Check-in failed';
      if (onError) {
        onError(errorMessage);
      }
    }
  };

  const handleCodeInputChange = (value: string) => {
    const numericValue = value.replace(/\D/g, '').slice(0, 6);
    setState(prev => ({ 
      ...prev, 
      verificationCode: numericValue, 
      validation: null 
    }));
    clearError('checkIn');
  };

  const handleQRTokenChange = (value: string) => {
    setState(prev => ({ ...prev, qrToken: value }));
    clearError('checkIn');
  };

  const getStatusColor = (status: AttendanceStatus) => {
    switch (status) {
      case AttendanceStatus.PRESENT:
        return '#28a745';
      case AttendanceStatus.LATE:
        return '#ffc107';
      case AttendanceStatus.ABSENT:
        return '#dc3545';
      case AttendanceStatus.EXCUSED:
        return '#6c757d';
      default:
        return '#007bff';
    }
  };

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString();
  };

  // Show success state
  if (state.showSuccess && state.lastResponse) {
    return (
      <div className="join-success">
        <div className="success-icon">✓</div>
        <h2>Check-in Successful!</h2>
        <p className="success-message">{state.lastResponse.message}</p>
        <div className="success-details">
          <p><strong>Class:</strong> {state.lastResponse.class_name}</p>
          <p>
            <strong>Status:</strong> 
            <span style={{ color: getStatusColor(state.lastResponse.attendance_status), marginLeft: '0.5rem' }}>
              {state.lastResponse.attendance_status.toUpperCase()}
            </span>
          </p>
          {state.lastResponse.is_late && (
            <p style={{ color: '#ffc107' }}>
              <strong>Late by:</strong> {state.lastResponse.late_minutes} minutes
            </p>
          )}
          <p className="timestamp">
            Checked in at: {formatTime(state.lastResponse.join_time)}
          </p>
          {offline.isOffline && (
            <p style={{ color: '#ffc107' }}>
              ⚠️ Checked in offline - will sync when connected
            </p>
          )}
        </div>
        <button
          type="button"
          className="join-button"
          style={{ marginTop: '1rem', background: '#6c757d' }}
          onClick={() => setState(prev => ({ ...prev, showSuccess: false }))}
        >
          Check In Again
        </button>
      </div>
    );
  }

  // Show current session if already checked in
  if (currentSession && !state.showSuccess) {
    return (
      <div className="join-success">
        <div className="success-icon">📋</div>
        <h2>Already Checked In</h2>
        <div className="success-details">
          <p><strong>Class:</strong> {currentSession.name}</p>
          <p>
            <strong>Status:</strong> 
            <span style={{ color: getStatusColor(currentSession.status), marginLeft: '0.5rem' }}>
              {currentSession.status.toUpperCase()}
            </span>
          </p>
          {currentSession.isLate && (
            <p style={{ color: '#ffc107' }}>
              <strong>Late by:</strong> {currentSession.lateMinutes} minutes
            </p>
          )}
          {currentSession.checkInTime && (
            <p className="timestamp">
              Checked in at: {formatTime(currentSession.checkInTime)}
            </p>
          )}
        </div>
        <button
          type="button"
          className="join-button"
          style={{ marginTop: '1rem', background: '#6c757d' }}
          onClick={() => setState(prev => ({ ...prev, showSuccess: false, lastResponse: null }))}
        >
          Check In to Another Class
        </button>
      </div>
    );
  }

  return (
    <div className="student-join-interface">
      <div className="join-header">
        <h2>Check In to Class</h2>
        <p className="subtitle">Choose your check-in method</p>
        {offline.isOffline && (
          <div className="error-message" style={{ background: '#fff3cd', color: '#856404', border: '1px solid #ffeaa7' }}>
            <span className="error-icon">⚠️</span>
            You're offline. Check-ins will be saved and synced when reconnected.
          </div>
        )}
      </div>

      {/* Method Selection - only show if mode is 'full' */}
      {mode === 'full' && (
        <div className="method-selection">
          <button
            type="button"
            className={`method-button ${state.method === 'verification_code' ? 'active' : ''}`}
            onClick={() => setState(prev => ({ ...prev, method: 'verification_code' }))}
          >
            🔢 Enter Code
          </button>
          <button
            type="button"
            className={`method-button ${state.method === 'qr_code' ? 'active' : ''}`}
            onClick={() => setState(prev => ({ ...prev, method: 'qr_code' }))}
          >
            🔗 QR Token
          </button>
        </div>
      )}

      {/* Verification Code Method */}
      {(state.method === 'verification_code' && (mode === 'full' || mode === 'code-only')) && (
        <div className="join-method">
          <div className="code-input-section">
            <label htmlFor="verificationCode">Enter 6-digit code:</label>
            <input
              id="verificationCode"
              type="text"
              value={state.verificationCode}
              onChange={(e) => handleCodeInputChange(e.target.value)}
              placeholder="000000"
              maxLength={6}
              className="code-input"
              autoComplete="off"
            />
            <div className="code-digits">
              {Array.from({ length: 6 }, (_, i) => (
                <div
                  key={i}
                  className={`digit ${state.verificationCode[i] ? 'filled' : ''} ${
                    state.validation?.errors.length && state.verificationCode.length === 6 ? 'error' : ''
                  }`}
                >
                  {state.verificationCode[i] || ''}
                </div>
              ))}
            </div>
            
            {/* Validation feedback */}
            {state.isValidating && (
              <p style={{ color: '#6c757d', textAlign: 'center', margin: '0.5rem 0' }}>
                Validating...
              </p>
            )}
            
            {state.validation && state.validation.errors.length > 0 && (
              <div className="error-message">
                <span className="error-icon">⚠️</span>
                {state.validation.errors[0]}
              </div>
            )}
            
            {state.validation && state.validation.warnings.length > 0 && (
              <div className="error-message" style={{ background: '#fff3cd', color: '#856404', border: '1px solid #ffeaa7' }}>
                <span className="error-icon">⚠️</span>
                {state.validation.warnings[0]}
              </div>
            )}
          </div>
          
          <button
            type="button"
            className="join-button"
            onClick={() => handleCheckIn('verification_code')}
            disabled={
              loading.checkIn || 
              state.verificationCode.length !== 6 || 
              state.isValidating ||
              (state.validation && !state.validation.canCheckIn)
            }
          >
            {loading.checkIn ? 'Checking In...' : 'Check In'}
          </button>
        </div>
      )}

      {/* QR Token Method */}
      {(state.method === 'qr_code' && (mode === 'full' || mode === 'qr-only')) && (
        <div className="join-method">
          <div className="qr-input-section">
            <label htmlFor="qrToken">QR Code Token:</label>
            <textarea
              id="qrToken"
              value={state.qrToken}
              onChange={(e) => handleQRTokenChange(e.target.value)}
              placeholder="Paste the token from QR code or link"
              rows={3}
              className="qr-input"
            />
          </div>
          <button
            type="button"
            className="join-button"
            onClick={() => handleCheckIn('qr_code')}
            disabled={loading.checkIn || !state.qrToken.trim()}
          >
            {loading.checkIn ? 'Checking In...' : 'Check In'}
          </button>
        </div>
      )}

      {/* Error Display */}
      {errors.checkIn && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          {errors.checkIn}
        </div>
      )}

      {/* Instructions */}
      <div className="join-instructions">
        <h3>How to check in:</h3>
        <ul>
          {(mode === 'full' || mode === 'code-only') && (
            <li><strong>Enter Code:</strong> Type the 6-digit verification code shared by your teacher</li>
          )}
          {(mode === 'full' || mode === 'qr-only') && (
            <li><strong>QR Token:</strong> Paste the token from a QR code or shared link</li>
          )}
          <li><strong>Late Check-in:</strong> You can still check in after class starts, but it will be marked as late</li>
          <li><strong>Offline:</strong> Check-ins work offline and will sync automatically when reconnected</li>
        </ul>
      </div>

      {/* Offline Pending Operations */}
      {offline.pendingOperations.length > 0 && (
        <div className="join-instructions" style={{ background: '#fff3cd', borderLeftColor: '#ffc107' }}>
          <h3>Pending Operations:</h3>
          <p>You have {offline.pendingOperations.length} check-in(s) waiting to sync when you're back online.</p>
        </div>
      )}
    </div>
  );
};