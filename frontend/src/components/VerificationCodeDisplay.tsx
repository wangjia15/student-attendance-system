import React, { useState, useEffect } from 'react';
import { ClassSessionResponse } from '../types/api';
import { regenerateVerificationCode } from '../services/api';
import './VerificationCodeDisplay.css';

interface VerificationCodeDisplayProps {
  session: ClassSessionResponse;
  onUpdate?: (updatedSession: Partial<ClassSessionResponse>) => void;
  className?: string;
}

export const VerificationCodeDisplay: React.FC<VerificationCodeDisplayProps> = ({
  session,
  onUpdate,
  className = ''
}) => {
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [error, setError] = useState<string>('');
  const [copied, setCopied] = useState(false);
  const [showCode, setShowCode] = useState(true);

  // Format verification code with spacing for readability
  const formatCode = (code: string): string => {
    return code.replace(/(\d{3})(\d{3})/, '$1 $2');
  };

  const handleRegenerate = async () => {
    setIsRegenerating(true);
    setError('');

    try {
      const result = await regenerateVerificationCode(session.id);
      if (onUpdate) {
        onUpdate({
          verification_code: result.verification_code,
          share_link: result.share_link
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to regenerate code');
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleCopyCode = async () => {
    try {
      await navigator.clipboard.writeText(session.verification_code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy code:', err);
      // Fallback for browsers that don't support clipboard API
      try {
        const textArea = document.createElement('textarea');
        textArea.value = session.verification_code;
        textArea.style.position = 'fixed';
        textArea.style.left = '-999999px';
        textArea.style.top = '-999999px';
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        textArea.remove();
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch (fallbackErr) {
        console.error('Fallback copy also failed:', fallbackErr);
      }
    }
  };

  const toggleCodeVisibility = () => {
    setShowCode(!showCode);
  };

  const handleAnnounceCode = () => {
    if ('speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(
        `The attendance code is ${session.verification_code.split('').join(' ')}`
      );
      utterance.rate = 0.8;
      speechSynthesis.speak(utterance);
    }
  };

  return (
    <div className={`verification-code-display ${className}`}>
      <div className="code-header">
        <h3>6-Digit Verification Code</h3>
        <div className="code-actions-header">
          <button
            className="toggle-visibility"
            onClick={toggleCodeVisibility}
            aria-label={showCode ? 'Hide code' : 'Show code'}
            title={showCode ? 'Hide code' : 'Show code'}
          >
            {showCode ? '👁️' : '🙈'}
          </button>
        </div>
      </div>

      <div className="code-container">
        <div className={`verification-code ${showCode ? 'visible' : 'hidden'}`}>
          <div className="code-display" onClick={handleCopyCode}>
            {showCode ? (
              <span className="code-digits" aria-label={`Verification code: ${session.verification_code}`}>
                {formatCode(session.verification_code)}
              </span>
            ) : (
              <span className="code-hidden">••• •••</span>
            )}
            <div className="tap-hint">Tap to copy</div>
          </div>
        </div>

        {copied && (
          <div className="copy-feedback">
            ✅ Code copied to clipboard!
          </div>
        )}
      </div>

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      <div className="code-actions">
        <button
          className="action-button secondary"
          onClick={handleRegenerate}
          disabled={isRegenerating}
        >
          {isRegenerating ? 'Regenerating...' : '🔄 New Code'}
        </button>

        <button
          className="action-button secondary"
          onClick={handleCopyCode}
          disabled={!showCode}
        >
          {copied ? '✅ Copied' : '📋 Copy'}
        </button>

        <button
          className="action-button secondary"
          onClick={handleAnnounceCode}
          disabled={!showCode || !('speechSynthesis' in window)}
          title="Announce code using text-to-speech"
        >
          🔊 Speak
        </button>
      </div>

      <div className="usage-instructions">
        <h4>For Students:</h4>
        <ol>
          <li>Open the attendance app or website</li>
          <li>Select "Join with Code"</li>
          <li>Enter this 6-digit code: <strong>{showCode ? session.verification_code : '••••••'}</strong></li>
          <li>Tap "Join Session"</li>
        </ol>
      </div>

      <div className="accessibility-features">
        <h4>Accessibility Options:</h4>
        <div className="feature-list">
          <div className="feature-item">
            <span className="feature-icon">🔊</span>
            <span>Text-to-speech code announcement</span>
          </div>
          <div className="feature-item">
            <span className="feature-icon">📱</span>
            <span>Large, high-contrast display</span>
          </div>
          <div className="feature-item">
            <span className="feature-icon">👁️</span>
            <span>Show/hide code privacy toggle</span>
          </div>
          <div className="feature-item">
            <span className="feature-icon">⌨️</span>
            <span>Keyboard navigation support</span>
          </div>
        </div>
      </div>

      <div className="security-note">
        <p>🔐 <strong>Security:</strong> This code expires with the session and cannot be reused after the class ends.</p>
      </div>
    </div>
  );
};