import React, { useState, useEffect, useCallback } from 'react';
import { ClassCreationForm } from './ClassCreationForm';
import { PWAInstallPrompt, usePWAInstall } from './PWAInstallPrompt';
import { ClassSessionResponse } from '../types/api';
import { deepLinkHandler, useDeepLink } from '../utils/deepLinking';
import './MobileClassCreation.css';

interface MobileClassCreationProps {
  onSessionCreated: (session: ClassSessionResponse) => void;
  onCancel?: () => void;
  initialTemplate?: string;
}

export const MobileClassCreation: React.FC<MobileClassCreationProps> = ({
  onSessionCreated,
  onCancel,
  initialTemplate
}) => {
  const [showPWAPrompt, setShowPWAPrompt] = useState(false);
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  const [showQuickAccess, setShowQuickAccess] = useState(false);
  const [orientation, setOrientation] = useState<'portrait' | 'landscape'>('portrait');
  const [installPromptDismissed, setInstallPromptDismissed] = useState(false);
  
  const { isInstalled, isInstallable, promptInstall } = usePWAInstall();

  // Handle network status changes
  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  // Handle orientation changes
  useEffect(() => {
    const handleOrientationChange = () => {
      setOrientation(window.innerHeight > window.innerWidth ? 'portrait' : 'landscape');
    };

    window.addEventListener('resize', handleOrientationChange);
    window.addEventListener('orientationchange', handleOrientationChange);
    
    // Initial check
    handleOrientationChange();

    return () => {
      window.removeEventListener('resize', handleOrientationChange);
      window.removeEventListener('orientationchange', handleOrientationChange);
    };
  }, []);

  // Handle deep link for template pre-selection
  const handleDeepLink = useCallback((linkData: any) => {
    if (linkData.type === 'create_class' && linkData.parameters.template) {
      // Template will be handled by ClassCreationForm if needed
      console.log('Deep link detected for class creation:', linkData);
    }
  }, []);

  // Set up deep link listener
  useEffect(() => {
    const unsubscribe = useDeepLink(handleDeepLink);
    return unsubscribe;
  }, [handleDeepLink]);

  // Show PWA install prompt after a delay
  useEffect(() => {
    if (!isInstalled && isInstallable && !installPromptDismissed) {
      const timer = setTimeout(() => {
        setShowPWAPrompt(true);
      }, 3000); // Show after 3 seconds

      return () => clearTimeout(timer);
    }
  }, [isInstalled, isInstallable, installPromptDismissed]);

  // Handle successful session creation
  const handleSessionCreated = useCallback((session: ClassSessionResponse) => {
    // Copy QR code link to clipboard for quick sharing
    if (navigator.clipboard && session.qr_data) {
      const shareUrl = `${window.location.origin}/join/${session.id}?code=${session.verification_code}`;
      navigator.clipboard.writeText(shareUrl).catch(console.warn);
    }

    // Show quick access options
    setShowQuickAccess(true);
    
    // Call parent handler
    onSessionCreated(session);
  }, [onSessionCreated]);

  // Handle PWA install
  const handleInstall = async () => {
    try {
      const installed = await promptInstall();
      if (installed) {
        setShowPWAPrompt(false);
      }
    } catch (error) {
      console.warn('Install failed:', error);
    }
  };

  // Handle PWA prompt dismiss
  const handlePWADismiss = () => {
    setShowPWAPrompt(false);
    setInstallPromptDismissed(true);
  };

  // Generate sharing options
  const generateShareOptions = (session: ClassSessionResponse) => {
    const shareUrl = `${window.location.origin}/join/${session.id}?code=${session.verification_code}`;
    const shareText = `Join my class "${session.name}" - Use code: ${session.verification_code}`;
    
    return {
      url: shareUrl,
      title: `Join ${session.name}`,
      text: shareText
    };
  };

  // Handle native sharing
  const handleNativeShare = async (session: ClassSessionResponse) => {
    if (navigator.share) {
      try {
        const shareData = generateShareOptions(session);
        await navigator.share(shareData);
      } catch (error) {
        if (error instanceof Error && error.name !== 'AbortError') {
          console.warn('Native share failed:', error);
          // Fallback to clipboard copy
          const shareData = generateShareOptions(session);
          navigator.clipboard?.writeText(`${shareData.text}\n${shareData.url}`);
        }
      }
    }
  };

  // Device-specific optimizations
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const isAndroid = /Android/.test(navigator.userAgent);
  const isMobile = /Mobi|Android/i.test(navigator.userAgent);
  
  return (
    <div className={`mobile-class-creation ${orientation} ${isMobile ? 'mobile' : 'desktop'}`}>
      {/* Network Status Indicator */}
      {!isOnline && (
        <div className="network-status offline">
          <span className="status-icon">📴</span>
          <span>Offline - Changes will sync when reconnected</span>
        </div>
      )}

      {/* Main Content */}
      <div className="creation-content">
        <ClassCreationForm
          onSessionCreated={handleSessionCreated}
          onCancel={onCancel}
        />
      </div>

      {/* Quick Access Panel */}
      {showQuickAccess && (
        <div className="quick-access-panel">
          <div className="quick-access-content">
            <h3>Class Created Successfully!</h3>
            <div className="quick-actions">
              <button 
                className="quick-action primary"
                onClick={() => setShowQuickAccess(false)}
              >
                Create Another Class
              </button>
              {!isInstalled && isInstallable && (
                <button 
                  className="quick-action secondary"
                  onClick={handleInstall}
                >
                  📱 Install App for Quick Access
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* PWA Install Prompt */}
      {showPWAPrompt && !isInstalled && (
        <PWAInstallPrompt
          onInstall={handlePWADismiss}
          onDismiss={handlePWADismiss}
        />
      )}

      {/* Mobile-specific Features */}
      {isMobile && (
        <>
          {/* Swipe Gesture Indicator */}
          <div className="swipe-indicator">
            <div className="swipe-hint">
              {isIOS ? 'Swipe down to dismiss' : 'Tap outside to dismiss'}
            </div>
          </div>
          
          {/* Device-specific Status */}
          <div className="device-status">
            {isIOS && (
              <div className="ios-optimizations">
                <span>🍎 Optimized for iOS</span>
              </div>
            )}
            {isAndroid && (
              <div className="android-optimizations">
                <span>🤖 Optimized for Android</span>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

// Hook for mobile-specific class creation features
export const useMobileClassCreation = () => {
  const [isMobile, setIsMobile] = useState(/Mobi|Android/i.test(navigator.userAgent));
  const [orientation, setOrientation] = useState<'portrait' | 'landscape'>('portrait');
  const [isOnline, setIsOnline] = useState(navigator.onLine);
  
  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(/Mobi|Android/i.test(navigator.userAgent));
    };
    
    const handleOrientationChange = () => {
      setOrientation(window.innerHeight > window.innerWidth ? 'portrait' : 'landscape');
    };
    
    const handleOnlineStatus = () => {
      setIsOnline(navigator.onLine);
    };
    
    window.addEventListener('resize', checkMobile);
    window.addEventListener('orientationchange', handleOrientationChange);
    window.addEventListener('online', handleOnlineStatus);
    window.addEventListener('offline', handleOnlineStatus);
    
    return () => {
      window.removeEventListener('resize', checkMobile);
      window.removeEventListener('orientationchange', handleOrientationChange);
      window.removeEventListener('online', handleOnlineStatus);
      window.removeEventListener('offline', handleOnlineStatus);
    };
  }, []);
  
  return {
    isMobile,
    orientation,
    isOnline,
    canShare: 'share' in navigator,
    canInstall: 'getInstalledRelatedApps' in navigator
  };
};