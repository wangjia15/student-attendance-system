import React, { useState, useEffect } from 'react';
import { 
  StudentJoinRequest, 
  VerificationCodeJoinRequest, 
  StudentJoinResponse, 
  AttendanceStatus 
} from '../types/api';
import { joinClassWithQR, joinClassWithCode } from '../services/api';
import './StudentJoinInterface.css';

interface StudentJoinInterfaceProps {
  onJoinSuccess: (response: StudentJoinResponse) => void;
  onCancel?: () => void;
  initialCode?: string; // Pre-filled from URL params
}

type JoinMethod = 'qr' | 'code' | 'scan';

export const StudentJoinInterface: React.FC<StudentJoinInterfaceProps> = ({
  onJoinSuccess,
  onCancel,
  initialCode
}) => {
  const [joinMethod, setJoinMethod] = useState<JoinMethod>('scan');
  const [verificationCode, setVerificationCode] = useState(initialCode || '');
  const [qrToken, setQrToken] = useState('');
  const [isJoining, setIsJoining] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  // Auto-detect QR code from URL if available
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('token');
    const code = urlParams.get('code');
    
    if (token) {
      setQrToken(token);
      setJoinMethod('qr');
      // Auto-join if we have a token
      handleJoinWithQR(token);
    } else if (code) {
      setVerificationCode(code);
      setJoinMethod('code');
    }
  }, []);

  const handleJoinWithQR = async (token: string = qrToken) => {
    if (!token.trim()) {
      setError('QR code token is required');
      return;
    }

    setIsJoining(true);
    setError('');

    try {
      const response = await joinClassWithQR({ jwt_token: token });
      setSuccessMessage(response.message);
      onJoinSuccess(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join class');
    } finally {
      setIsJoining(false);
    }
  };

  const handleJoinWithCode = async () => {
    if (!verificationCode.trim()) {
      setError('Verification code is required');
      return;
    }

    if (verificationCode.length !== 6) {
      setError('Verification code must be 6 digits');
      return;
    }

    setIsJoining(true);
    setError('');

    try {
      const response = await joinClassWithCode({ 
        verification_code: verificationCode 
      });
      setSuccessMessage(response.message);
      onJoinSuccess(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to join class');
    } finally {
      setIsJoining(false);
    }
  };

  const handleCodeInputChange = (value: string) => {
    // Only allow numbers and limit to 6 digits
    const numericValue = value.replace(/\D/g, '').slice(0, 6);
    setVerificationCode(numericValue);
    setError('');
  };

  const handleScanQRCode = () => {
    // In a real app, this would open camera for QR scanning
    // For now, we'll show a placeholder
    setError('Camera scanning not implemented yet. Please enter code manually or use QR from another device.');
  };

  const getAttendanceStatusColor = (status: AttendanceStatus) => {
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

  if (successMessage) {
    return (
      <div className="join-success">
        <div className="success-icon">✓</div>
        <h2>Successfully Joined!</h2>
        <p className="success-message">{successMessage}</p>
        <div className="success-details">
          <p>You are now checked in to this class.</p>
          <p className="timestamp">
            Joined at: {new Date().toLocaleTimeString()}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="student-join-interface">
      <div className="join-header">
        <h2>Join Class</h2>
        <p className="subtitle">Choose how you'd like to join the attendance session</p>
      </div>

      {/* Method Selection */}
      <div className="method-selection">
        <button
          type="button"
          className={`method-button ${joinMethod === 'scan' ? 'active' : ''}`}
          onClick={() => setJoinMethod('scan')}
        >
          📷 Scan QR Code
        </button>
        <button
          type="button"
          className={`method-button ${joinMethod === 'code' ? 'active' : ''}`}
          onClick={() => setJoinMethod('code')}
        >
          🔢 Enter Code
        </button>
        <button
          type="button"
          className={`method-button ${joinMethod === 'qr' ? 'active' : ''}`}
          onClick={() => setJoinMethod('qr')}
        >
          🔗 From Link
        </button>
      </div>

      {/* Join Methods */}
      {joinMethod === 'scan' && (
        <div className="join-method">
          <div className="scan-placeholder">
            <div className="camera-icon">📷</div>
            <p>Position the QR code within the frame</p>
            <button
              type="button"
              className="scan-button"
              onClick={handleScanQRCode}
            >
              Start Camera
            </button>
          </div>
        </div>
      )}

      {joinMethod === 'code' && (
        <div className="join-method">
          <div className="code-input-section">
            <label htmlFor="verificationCode">Enter 6-digit code:</label>
            <input
              id="verificationCode"
              type="text"
              value={verificationCode}
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
                  className={`digit ${verificationCode[i] ? 'filled' : ''}`}
                >
                  {verificationCode[i] || ''}
                </div>
              ))}
            </div>
          </div>
          <button
            type="button"
            className="join-button"
            onClick={handleJoinWithCode}
            disabled={isJoining || verificationCode.length !== 6}
          >
            {isJoining ? 'Joining...' : 'Join Class'}
          </button>
        </div>
      )}

      {joinMethod === 'qr' && (
        <div className="join-method">
          <div className="qr-input-section">
            <label htmlFor="qrToken">QR Code Token:</label>
            <textarea
              id="qrToken"
              value={qrToken}
              onChange={(e) => {
                setQrToken(e.target.value);
                setError('');
              }}
              placeholder="Paste the token from QR code or link"
              rows={3}
              className="qr-input"
            />
          </div>
          <button
            type="button"
            className="join-button"
            onClick={() => handleJoinWithQR()}
            disabled={isJoining || !qrToken.trim()}
          >
            {isJoining ? 'Joining...' : 'Join Class'}
          </button>
        </div>
      )}

      {/* Error Display */}
      {error && (
        <div className="error-message">
          <span className="error-icon">⚠️</span>
          {error}
        </div>
      )}

      {/* Instructions */}
      <div className="join-instructions">
        <h3>How to join:</h3>
        <ul>
          <li><strong>Scan QR Code:</strong> Use your camera to scan the QR code displayed by your teacher</li>
          <li><strong>Enter Code:</strong> Type the 6-digit verification code shared by your teacher</li>
          <li><strong>From Link:</strong> If you received a share link, the code will be automatically filled</li>
        </ul>
      </div>

      {/* Cancel Button */}
      {onCancel && (
        <button
          type="button"
          className="cancel-button"
          onClick={onCancel}
          disabled={isJoining}
        >
          Cancel
        </button>
      )}
    </div>
  );
};