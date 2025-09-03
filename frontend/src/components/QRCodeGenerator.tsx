import React, { useState, useEffect, useRef } from 'react';
import { ClassSessionResponse } from '../types/api';
import { regenerateQRCode } from '../services/api';
import './QRCodeGenerator.css';

interface QRCodeGeneratorProps {
  session: ClassSessionResponse;
  onUpdate?: (updatedSession: Partial<ClassSessionResponse>) => void;
  className?: string;
}

export const QRCodeGenerator: React.FC<QRCodeGeneratorProps> = ({
  session,
  onUpdate,
  className = ''
}) => {
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [error, setError] = useState<string>('');
  const [showFullScreen, setShowFullScreen] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState<string>('');
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Calculate time remaining
  const [timeRemaining, setTimeRemaining] = useState<string>('');
  
  useEffect(() => {
    const updateTimeRemaining = () => {
      const now = new Date();
      const expires = new Date(session.expires_at);
      const diff = expires.getTime() - now.getTime();
      
      if (diff <= 0) {
        setTimeRemaining('Expired');
        return;
      }
      
      const minutes = Math.floor(diff / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      setTimeRemaining(`${minutes}:${seconds.toString().padStart(2, '0')}`);
    };

    updateTimeRemaining();
    const interval = setInterval(updateTimeRemaining, 1000);
    
    return () => clearInterval(interval);
  }, [session.expires_at]);

  // Generate download URL for QR code
  useEffect(() => {
    if (session.qr_code_data) {
      setDownloadUrl(session.qr_code_data);
    }
  }, [session.qr_code_data]);

  const handleRegenerate = async () => {
    setIsRegenerating(true);
    setError('');

    try {
      const result = await regenerateQRCode(session.id);
      if (onUpdate) {
        onUpdate({
          qr_code_data: result.qr_code_data,
          jwt_token: result.jwt_token
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate QR code');
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleDownload = () => {
    if (!downloadUrl) return;
    
    const link = document.createElement('a');
    link.download = `qr-code-${session.class_name.replace(/\s+/g, '-')}-${session.id}.png`;
    link.href = downloadUrl;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleShare = async () => {
    if (navigator.share && session.qr_code_data) {
      try {
        // Convert base64 to blob for sharing
        const response = await fetch(session.qr_code_data);
        const blob = await response.blob();
        const file = new File([blob], `${session.class_name}-qr-code.png`, { type: 'image/png' });

        await navigator.share({
          title: `Join ${session.class_name}`,
          text: `Scan this QR code to join the attendance session for ${session.class_name}`,
          files: [file]
        });
      } catch (err) {
        // Fallback to copying link
        handleCopyLink();
      }
    } else {
      handleCopyLink();
    }
  };

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(session.share_link);
      // Could add a toast notification here
      alert('Link copied to clipboard!');
    } catch (err) {
      console.error('Failed to copy link:', err);
    }
  };

  const handleFullScreen = () => {
    setShowFullScreen(true);
  };

  const closeFullScreen = () => {
    setShowFullScreen(false);
  };

  return (
    <div className={`qr-code-generator ${className}`}>
      <div className="qr-header">
        <h3>QR Code for Attendance</h3>
        <div className="time-remaining">
          <span className="label">Expires in:</span>
          <span className={`time ${timeRemaining === 'Expired' ? 'expired' : ''}`}>
            {timeRemaining}
          </span>
        </div>
      </div>

      <div className="qr-code-container">
        {session.qr_code_data ? (
          <>
            <div className="qr-code-image" onClick={handleFullScreen}>
              <img 
                src={session.qr_code_data} 
                alt={`QR Code for ${session.class_name}`}
                className="qr-image"
              />
              <div className="qr-overlay">
                <span>Tap to enlarge</span>
              </div>
            </div>
            
            <div className="class-info">
              <div className="class-name">{session.class_name}</div>
              {session.subject && <div className="subject">{session.subject}</div>}
              <div className="session-id">ID: {session.id}</div>
            </div>
          </>
        ) : (
          <div className="qr-loading">
            <div className="loading-spinner"></div>
            <span>Generating QR code...</span>
          </div>
        )}
      </div>

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      <div className="qr-actions">
        <button 
          className="action-button secondary"
          onClick={handleRegenerate}
          disabled={isRegenerating}
        >
          {isRegenerating ? 'Regenerating...' : '🔄 Regenerate'}
        </button>
        
        <button 
          className="action-button secondary"
          onClick={handleDownload}
          disabled={!session.qr_code_data}
        >
          📥 Download
        </button>
        
        <button 
          className="action-button primary"
          onClick={handleShare}
          disabled={!session.qr_code_data}
        >
          📤 Share
        </button>
      </div>

      <div className="scan-instructions">
        <p>📱 Students can scan with:</p>
        <ul>
          <li>Camera app (iOS/Android)</li>
          <li>QR code scanner apps</li>
          <li>Attendance app camera</li>
        </ul>
      </div>

      {/* Full Screen Modal */}
      {showFullScreen && (
        <div className="fullscreen-modal" onClick={closeFullScreen}>
          <div className="fullscreen-content" onClick={(e) => e.stopPropagation()}>
            <button className="close-button" onClick={closeFullScreen}>
              ✕
            </button>
            <img 
              src={session.qr_code_data} 
              alt={`QR Code for ${session.class_name}`}
              className="fullscreen-qr"
            />
            <div className="fullscreen-info">
              <h3>{session.class_name}</h3>
              {session.subject && <p>{session.subject}</p>}
              <p>Show this QR code to students to join the session</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};