import React, { useState, useEffect } from 'react';
import { ClassSessionResponse } from '../types/api';
import { getShareLink } from '../services/api';
import './ShareLinkManager.css';

interface ShareLinkManagerProps {
  session: ClassSessionResponse;
  className?: string;
}

interface ShareOption {
  id: string;
  name: string;
  icon: string;
  action: (url: string, text: string) => void;
  available: boolean;
}

export const ShareLinkManager: React.FC<ShareLinkManagerProps> = ({
  session,
  className = ''
}) => {
  const [shareData, setShareData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>('');
  const [copied, setCopied] = useState<string>('');

  useEffect(() => {
    const fetchShareData = async () => {
      try {
        const data = await getShareLink(session.id);
        setShareData(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load share data');
      } finally {
        setLoading(false);
      }
    };

    fetchShareData();
  }, [session.id]);

  const handleCopy = async (text: string, type: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(type);
      setTimeout(() => setCopied(''), 2000);
    } catch (err) {
      // Fallback for older browsers
      const textArea = document.createElement('textarea');
      textArea.value = text;
      textArea.style.position = 'fixed';
      textArea.style.left = '-999999px';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      try {
        document.execCommand('copy');
        setCopied(type);
        setTimeout(() => setCopied(''), 2000);
      } catch (fallbackErr) {
        console.error('Copy failed:', fallbackErr);
      } finally {
        document.body.removeChild(textArea);
      }
    }
  };

  const shareOptions: ShareOption[] = [
    {
      id: 'whatsapp',
      name: 'WhatsApp',
      icon: '💬',
      available: true,
      action: (url, text) => {
        const whatsappUrl = `https://wa.me/?text=${encodeURIComponent(`${text}\n\n${url}`)}`;
        window.open(whatsappUrl, '_blank');
      }
    },
    {
      id: 'email',
      name: 'Email',
      icon: '📧',
      available: true,
      action: (url, text) => {
        const subject = encodeURIComponent(`Join ${session.class_name} - Attendance Session`);
        const body = encodeURIComponent(`${text}\n\nJoin link: ${url}\n\nVerification code: ${session.verification_code}`);
        window.location.href = `mailto:?subject=${subject}&body=${body}`;
      }
    },
    {
      id: 'sms',
      name: 'SMS',
      icon: '💬',
      available: true,
      action: (url, text) => {
        const smsText = encodeURIComponent(`${text}\n${url}\nCode: ${session.verification_code}`);
        window.location.href = `sms:?body=${smsText}`;
      }
    },
    {
      id: 'native',
      name: 'Share',
      icon: '📤',
      available: 'share' in navigator,
      action: async (url, text) => {
        try {
          await navigator.share({
            title: `Join ${session.class_name}`,
            text: text,
            url: url
          });
        } catch (err) {
          console.error('Native share failed:', err);
        }
      }
    }
  ];

  const shareText = `Join the attendance session for "${session.class_name}"${session.subject ? ` (${session.subject})` : ''}`;

  if (loading) {
    return (
      <div className={`share-link-manager ${className}`}>
        <div className="loading-state">
          <div className="spinner"></div>
          <span>Loading sharing options...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`share-link-manager ${className}`}>
        <div className="error-state">
          <span className="error-icon">⚠️</span>
          <span>{error}</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`share-link-manager ${className}`}>
      <div className="share-header">
        <h3>Share Session</h3>
        <p>Send this link to students to join the attendance session</p>
      </div>

      {/* Web Link */}
      <div className="share-item">
        <div className="share-item-header">
          <span className="share-icon">🌐</span>
          <span className="share-title">Web Link</span>
          <button
            className="copy-button"
            onClick={() => handleCopy(shareData?.share_link || session.share_link, 'web')}
            title="Copy web link"
          >
            {copied === 'web' ? '✅' : '📋'}
          </button>
        </div>
        <div className="link-preview">
          {shareData?.share_link || session.share_link}
        </div>
      </div>

      {/* Deep Link */}
      <div className="share-item">
        <div className="share-item-header">
          <span className="share-icon">📱</span>
          <span className="share-title">App Deep Link</span>
          <button
            className="copy-button"
            onClick={() => handleCopy(shareData?.deep_link || `attendance://join/${session.id}?code=${session.verification_code}`, 'deep')}
            title="Copy deep link"
          >
            {copied === 'deep' ? '✅' : '📋'}
          </button>
        </div>
        <div className="link-preview">
          {shareData?.deep_link || `attendance://join/${session.id}?code=${session.verification_code}`}
        </div>
        <div className="link-description">
          Opens directly in the attendance app if installed
        </div>
      </div>

      {/* Quick Share Options */}
      <div className="quick-share">
        <h4>Quick Share</h4>
        <div className="share-buttons">
          {shareOptions
            .filter(option => option.available)
            .map(option => (
              <button
                key={option.id}
                className="share-button"
                onClick={() => option.action(shareData?.share_link || session.share_link, shareText)}
                title={`Share via ${option.name}`}
              >
                <span className="share-button-icon">{option.icon}</span>
                <span className="share-button-text">{option.name}</span>
              </button>
            ))
          }
        </div>
      </div>

      {/* Session Info */}
      <div className="session-info">
        <div className="info-item">
          <strong>Class:</strong> {session.class_name}
        </div>
        {session.subject && (
          <div className="info-item">
            <strong>Subject:</strong> {session.subject}
          </div>
        )}
        <div className="info-item">
          <strong>Code:</strong> {session.verification_code}
        </div>
        <div className="info-item">
          <strong>Expires:</strong> {new Date(session.expires_at).toLocaleString()}
        </div>
      </div>

      {/* Usage Instructions */}
      <div className="usage-tips">
        <h4>💡 Sharing Tips</h4>
        <ul>
          <li><strong>WhatsApp/SMS:</strong> Best for quick sharing with individual students</li>
          <li><strong>Email:</strong> Include QR code image for better accessibility</li>
          <li><strong>Deep Link:</strong> Opens app directly on mobile devices</li>
          <li><strong>Web Link:</strong> Works in any browser as fallback</li>
        </ul>
      </div>

      {/* Accessibility Note */}
      <div className="accessibility-note">
        <p>📞 <strong>Accessibility:</strong> Students can also join by calling the verification code hotline or using voice commands in supported apps.</p>
      </div>
    </div>
  );
};