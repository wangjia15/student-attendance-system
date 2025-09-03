import React, { useState, useEffect } from 'react';
import { deepLinkHandler } from '../utils/deepLinking';
import './PWAInstallPrompt.css';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

interface PWAInstallPromptProps {
  onInstall?: () => void;
  onDismiss?: () => void;
  className?: string;
}

export const PWAInstallPrompt: React.FC<PWAInstallPromptProps> = ({
  onInstall,
  onDismiss,
  className = ''
}) => {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [isInstallable, setIsInstallable] = useState(false);
  const [isInstalled, setIsInstalled] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [installMethod, setInstallMethod] = useState<'browser' | 'manual' | 'native'>('browser');

  // Check installation status and setup event listeners
  useEffect(() => {
    const checkInstallStatus = async () => {
      const installed = await deepLinkHandler.isAppInstalled();
      setIsInstalled(installed);
      
      if (!installed) {
        setupInstallPrompt();
      }
    };

    checkInstallStatus();
  }, []);

  // Setup PWA install prompt listeners
  const setupInstallPrompt = () => {
    // Listen for beforeinstallprompt event
    const handleBeforeInstallPrompt = (e: Event) => {
      console.log('PWA: beforeinstallprompt event fired');
      e.preventDefault();
      
      const promptEvent = e as BeforeInstallPromptEvent;
      setDeferredPrompt(promptEvent);
      setIsInstallable(true);
      setInstallMethod('browser');
      
      // Show install prompt after a delay
      setTimeout(() => {
        if (!isInstalled) {
          setShowPrompt(true);
        }
      }, 5000); // Wait 5 seconds before showing
    };

    // Listen for appinstalled event
    const handleAppInstalled = () => {
      console.log('PWA: App was installed');
      setIsInstalled(true);
      setShowPrompt(false);
      setDeferredPrompt(null);
      if (onInstall) onInstall();
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    window.addEventListener('appinstalled', handleAppInstalled);

    // Cleanup
    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  };

  // Detect browser and platform for manual install instructions
  useEffect(() => {
    if (!deferredPrompt && !isInstalled) {
      const userAgent = navigator.userAgent.toLowerCase();
      const isIOS = /iphone|ipad|ipod/.test(userAgent);
      const isSafari = /safari/.test(userAgent) && !/chrome/.test(userAgent);
      const isChrome = /chrome/.test(userAgent);
      const isFirefox = /firefox/.test(userAgent);

      if ((isIOS && isSafari) || isChrome || isFirefox) {
        setInstallMethod('manual');
        setIsInstallable(true);
        
        // Show manual install prompt after delay
        setTimeout(() => {
          if (!isInstalled) {
            setShowPrompt(true);
          }
        }, 10000); // Wait 10 seconds for manual instructions
      }
    }
  }, [deferredPrompt, isInstalled]);

  // Handle native install prompt
  const handleInstall = async () => {
    if (!deferredPrompt) {
      console.warn('No install prompt available');
      return;
    }

    setIsLoading(true);

    try {
      await deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      
      console.log(`PWA: User response to install prompt: ${outcome}`);
      
      if (outcome === 'accepted') {
        console.log('PWA: User accepted the install prompt');
        setShowPrompt(false);
      } else {
        console.log('PWA: User dismissed the install prompt');
        if (onDismiss) onDismiss();
      }
      
      setDeferredPrompt(null);
    } catch (error) {
      console.error('PWA: Install prompt failed:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle manual dismiss
  const handleDismiss = () => {
    setShowPrompt(false);
    
    // Don't show again for this session
    sessionStorage.setItem('pwa-prompt-dismissed', 'true');
    
    if (onDismiss) onDismiss();
  };

  // Check if prompt was already dismissed
  useEffect(() => {
    const wasDismissed = sessionStorage.getItem('pwa-prompt-dismissed');
    if (wasDismissed) {
      setShowPrompt(false);
    }
  }, []);

  // Get manual install instructions based on browser/platform
  const getManualInstructions = (): { title: string; steps: string[] } => {
    const userAgent = navigator.userAgent.toLowerCase();
    const isIOS = /iphone|ipad|ipod/.test(userAgent);
    const isSafari = /safari/.test(userAgent) && !/chrome/.test(userAgent);
    const isChrome = /chrome/.test(userAgent);

    if (isIOS && isSafari) {
      return {
        title: 'Install on iOS Safari',
        steps: [
          'Tap the Share button (square with arrow)',
          'Scroll down and tap "Add to Home Screen"',
          'Tap "Add" to confirm installation',
          'Find the app icon on your home screen'
        ]
      };
    }

    if (isChrome) {
      return {
        title: 'Install on Chrome',
        steps: [
          'Look for the install icon in the address bar',
          'Click "Install" when prompted',
          'Or use Chrome menu → "Install Student Attendance System"',
          'The app will open in its own window'
        ]
      };
    }

    return {
      title: 'Install App',
      steps: [
        'Look for install options in your browser menu',
        'Add this site to your home screen or desktop',
        'Enable notifications for attendance updates',
        'Enjoy the full app experience!'
      ]
    };
  };

  // Don't render if already installed or not installable
  if (isInstalled || !isInstallable || !showPrompt) {
    return null;
  }

  const instructions = installMethod === 'manual' ? getManualInstructions() : null;

  return (
    <div className={`pwa-install-prompt ${className}`}>
      <div className="install-prompt-overlay" onClick={handleDismiss}></div>
      
      <div className="install-prompt-content">
        <div className="install-header">
          <div className="app-icon">📱</div>
          <div className="install-title">
            <h3>Install Attendance App</h3>
            <p>Get quick access and work offline</p>
          </div>
          <button 
            className="dismiss-button"
            onClick={handleDismiss}
            aria-label="Close install prompt"
          >
            ×
          </button>
        </div>

        <div className="install-benefits">
          <div className="benefit-item">
            <span className="benefit-icon">⚡</span>
            <span>Instant access from home screen</span>
          </div>
          <div className="benefit-item">
            <span className="benefit-icon">📴</span>
            <span>Works offline for viewing sessions</span>
          </div>
          <div className="benefit-item">
            <span className="benefit-icon">🔔</span>
            <span>Get push notifications</span>
          </div>
          <div className="benefit-item">
            <span className="benefit-icon">📊</span>
            <span>Full-screen dashboard experience</span>
          </div>
        </div>

        {installMethod === 'browser' && deferredPrompt && (
          <div className="install-actions">
            <button
              className="install-button primary"
              onClick={handleInstall}
              disabled={isLoading}
            >
              {isLoading ? 'Installing...' : 'Install App'}
            </button>
            <button
              className="install-button secondary"
              onClick={handleDismiss}
              disabled={isLoading}
            >
              Maybe Later
            </button>
          </div>
        )}

        {installMethod === 'manual' && instructions && (
          <div className="manual-install">
            <h4>{instructions.title}</h4>
            <ol className="install-steps">
              {instructions.steps.map((step, index) => (
                <li key={index}>{step}</li>
              ))}
            </ol>
            <div className="install-actions">
              <button
                className="install-button secondary"
                onClick={handleDismiss}
              >
                Got it!
              </button>
            </div>
          </div>
        )}

        <div className="install-footer">
          <small>
            Free to install • No app store required • Same great features
          </small>
        </div>
      </div>
    </div>
  );
};

// Hook for checking PWA install status
export const usePWAInstall = () => {
  const [isInstalled, setIsInstalled] = useState(false);
  const [isInstallable, setIsInstallable] = useState(false);
  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null);

  useEffect(() => {
    const checkStatus = async () => {
      const installed = await deepLinkHandler.isAppInstalled();
      setIsInstalled(installed);
    };

    const handleBeforeInstallPrompt = (e: Event) => {
      e.preventDefault();
      const promptEvent = e as BeforeInstallPromptEvent;
      setInstallPrompt(promptEvent);
      setIsInstallable(true);
    };

    const handleAppInstalled = () => {
      setIsInstalled(true);
      setInstallPrompt(null);
    };

    checkStatus();
    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    window.addEventListener('appinstalled', handleAppInstalled);

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
      window.removeEventListener('appinstalled', handleAppInstalled);
    };
  }, []);

  const promptInstall = async () => {
    if (installPrompt) {
      await installPrompt.prompt();
      const { outcome } = await installPrompt.userChoice;
      return outcome === 'accepted';
    }
    return false;
  };

  return {
    isInstalled,
    isInstallable,
    promptInstall
  };
};