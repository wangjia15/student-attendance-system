// Deep Linking Utilities for Student Attendance System
// Handles universal links, app links, and custom protocol handling

export interface DeepLinkData {
  type: 'join_class' | 'view_session' | 'create_class' | 'unknown';
  classId?: string;
  code?: string;
  token?: string;
  parameters: Record<string, string>;
  fallbackUrl?: string;
}

export interface DeepLinkConfig {
  customProtocol: string;
  webBaseUrl: string;
  appBaseUrl: string;
  universalLinkDomains: string[];
}

const DEFAULT_CONFIG: DeepLinkConfig = {
  customProtocol: 'attendance',
  webBaseUrl: window.location.origin,
  appBaseUrl: 'https://attendance.school.edu',
  universalLinkDomains: ['attendance.school.edu', 'app.attendance.edu']
};

export class DeepLinkHandler {
  private config: DeepLinkConfig;
  private listeners: Set<(data: DeepLinkData) => void> = new Set();

  constructor(config?: Partial<DeepLinkConfig>) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.setupEventListeners();
  }

  // Setup event listeners for various deep link triggers
  private setupEventListeners(): void {
    // Handle initial page load with deep link parameters
    if (typeof window !== 'undefined') {
      this.handleInitialUrl();

      // Listen for hash changes (for single-page apps)
      window.addEventListener('hashchange', () => {
        this.handleCurrentUrl();
      });

      // Listen for popstate (browser navigation)
      window.addEventListener('popstate', () => {
        this.handleCurrentUrl();
      });

      // Listen for custom protocol launches (if supported)
      this.setupProtocolHandler();

      // Listen for Web Share Target API
      this.setupShareTargetHandler();
    }
  }

  // Handle initial URL on app startup
  private handleInitialUrl(): void {
    const currentUrl = window.location.href;
    const linkData = this.parseUrl(currentUrl);
    
    if (linkData.type !== 'unknown') {
      this.notifyListeners(linkData);
    }
  }

  // Handle current URL changes
  private handleCurrentUrl(): void {
    const currentUrl = window.location.href;
    const linkData = this.parseUrl(currentUrl);
    
    if (linkData.type !== 'unknown') {
      this.notifyListeners(linkData);
    }
  }

  // Parse URL and extract deep link data
  parseUrl(url: string): DeepLinkData {
    try {
      const parsedUrl = new URL(url);
      
      // Handle custom protocol (attendance://join/class123?code=123456)
      if (parsedUrl.protocol === `${this.config.customProtocol}:`) {
        return this.parseCustomProtocolUrl(parsedUrl);
      }

      // Handle universal links (https://attendance.school.edu/join/class123?code=123456)
      if (this.config.universalLinkDomains.includes(parsedUrl.hostname)) {
        return this.parseUniversalLink(parsedUrl);
      }

      // Handle web app URLs
      return this.parseWebAppUrl(parsedUrl);
      
    } catch (error) {
      console.error('Failed to parse deep link URL:', error);
      return {
        type: 'unknown',
        parameters: {},
        fallbackUrl: url
      };
    }
  }

  // Parse custom protocol URLs (attendance://action/...)
  private parseCustomProtocolUrl(url: URL): DeepLinkData {
    const pathParts = url.pathname.split('/').filter(Boolean);
    const searchParams = new URLSearchParams(url.search);
    const parameters: Record<string, string> = {};
    
    // Convert URLSearchParams to object
    searchParams.forEach((value, key) => {
      parameters[key] = value;
    });

    if (pathParts[0] === 'join' && pathParts[1]) {
      return {
        type: 'join_class',
        classId: pathParts[1],
        code: parameters.code,
        token: parameters.token,
        parameters,
        fallbackUrl: `${this.config.webBaseUrl}/join/${pathParts[1]}?${url.search}`
      };
    }

    if (pathParts[0] === 'session' && pathParts[1]) {
      return {
        type: 'view_session',
        classId: pathParts[1],
        parameters,
        fallbackUrl: `${this.config.webBaseUrl}/session/${pathParts[1]}?${url.search}`
      };
    }

    if (pathParts[0] === 'create') {
      return {
        type: 'create_class',
        parameters,
        fallbackUrl: `${this.config.webBaseUrl}/create?${url.search}`
      };
    }

    return {
      type: 'unknown',
      parameters,
      fallbackUrl: this.config.webBaseUrl
    };
  }

  // Parse universal links (https://domain/path)
  private parseUniversalLink(url: URL): DeepLinkData {
    return this.parseWebAppUrl(url);
  }

  // Parse web app URLs
  private parseWebAppUrl(url: URL): DeepLinkData {
    const pathParts = url.pathname.split('/').filter(Boolean);
    const searchParams = new URLSearchParams(url.search);
    const parameters: Record<string, string> = {};
    
    searchParams.forEach((value, key) => {
      parameters[key] = value;
    });

    // Handle join links (/join/:classId)
    if (pathParts[0] === 'join' && pathParts[1]) {
      return {
        type: 'join_class',
        classId: pathParts[1],
        code: parameters.code,
        token: parameters.token,
        parameters
      };
    }

    // Handle session view (/session/:classId or /dashboard/:classId)
    if ((pathParts[0] === 'session' || pathParts[0] === 'dashboard') && pathParts[1]) {
      return {
        type: 'view_session',
        classId: pathParts[1],
        parameters
      };
    }

    // Handle create class (/create)
    if (pathParts[0] === 'create') {
      return {
        type: 'create_class',
        parameters
      };
    }

    return {
      type: 'unknown',
      parameters
    };
  }

  // Generate deep links for sharing
  generateDeepLink(type: string, data: Record<string, string> = {}): {
    webUrl: string;
    universalUrl: string;
    customProtocolUrl: string;
    fallbackUrl: string;
  } {
    let webPath = '';
    let customPath = '';

    switch (type) {
      case 'join_class':
        if (data.classId) {
          webPath = `/join/${data.classId}`;
          customPath = `/join/${data.classId}`;
        }
        break;
      
      case 'view_session':
        if (data.classId) {
          webPath = `/session/${data.classId}`;
          customPath = `/session/${data.classId}`;
        }
        break;
      
      case 'create_class':
        webPath = '/create';
        customPath = '/create';
        break;
      
      default:
        webPath = '/';
        customPath = '/';
    }

    // Build query string
    const queryParams = new URLSearchParams();
    Object.entries(data).forEach(([key, value]) => {
      if (key !== 'classId' && value) {
        queryParams.append(key, value);
      }
    });

    const queryString = queryParams.toString();
    const webUrl = `${this.config.webBaseUrl}${webPath}${queryString ? '?' + queryString : ''}`;
    const universalUrl = `${this.config.appBaseUrl}${webPath}${queryString ? '?' + queryString : ''}`;
    const customProtocolUrl = `${this.config.customProtocol}:${customPath}${queryString ? '?' + queryString : ''}`;

    return {
      webUrl,
      universalUrl,
      customProtocolUrl,
      fallbackUrl: webUrl
    };
  }

  // Setup protocol handler registration
  private setupProtocolHandler(): void {
    if ('registerProtocolHandler' in navigator) {
      try {
        navigator.registerProtocolHandler(
          this.config.customProtocol,
          `${this.config.webBaseUrl}/protocol-handler?url=%s`,
          'Student Attendance System'
        );
      } catch (error) {
        console.warn('Could not register protocol handler:', error);
      }
    }
  }

  // Setup Web Share Target API handler
  private setupShareTargetHandler(): void {
    // Handle shared content from other apps
    if ('serviceWorker' in navigator && 'share' in navigator) {
      // This would be handled by the service worker
      // and passed to the app via URL parameters
      const urlParams = new URLSearchParams(window.location.search);
      
      if (urlParams.has('shared_title') || urlParams.has('shared_text')) {
        const sharedData = {
          title: urlParams.get('shared_title') || '',
          text: urlParams.get('shared_text') || '',
          url: urlParams.get('shared_url') || ''
        };
        
        console.log('Received shared content:', sharedData);
        // Handle shared content (could trigger class creation with shared details)
      }
    }
  }

  // Subscribe to deep link events
  onDeepLink(callback: (data: DeepLinkData) => void): () => void {
    this.listeners.add(callback);
    
    // Return unsubscribe function
    return () => {
      this.listeners.delete(callback);
    };
  }

  // Notify all listeners of deep link data
  private notifyListeners(data: DeepLinkData): void {
    this.listeners.forEach(listener => {
      try {
        listener(data);
      } catch (error) {
        console.error('Error in deep link listener:', error);
      }
    });
  }

  // Test if app is installed (for install prompts)
  async isAppInstalled(): Promise<boolean> {
    if ('getInstalledRelatedApps' in navigator) {
      try {
        const relatedApps = await (navigator as any).getInstalledRelatedApps();
        return relatedApps.length > 0;
      } catch (error) {
        console.warn('Could not check installed apps:', error);
      }
    }
    
    // Fallback: check if running in standalone mode
    return window.matchMedia('(display-mode: standalone)').matches ||
           (window.navigator as any).standalone === true;
  }

  // Handle app-to-app communication
  async handleAppIntentData(): Promise<any> {
    // This would handle Android App Links intent data
    // or iOS Universal Links data passed to the web app
    
    const urlParams = new URLSearchParams(window.location.search);
    const intentData: Record<string, any> = {};
    
    // Extract intent data from URL parameters
    urlParams.forEach((value, key) => {
      if (key.startsWith('intent_')) {
        intentData[key.replace('intent_', '')] = value;
      }
    });
    
    return Object.keys(intentData).length > 0 ? intentData : null;
  }
}

// Export singleton instance
export const deepLinkHandler = new DeepLinkHandler();

// Utility functions for common deep link operations
export const createJoinLink = (classId: string, code?: string, token?: string) => {
  return deepLinkHandler.generateDeepLink('join_class', { 
    classId, 
    ...(code && { code }),
    ...(token && { token })
  });
};

export const createSessionLink = (classId: string) => {
  return deepLinkHandler.generateDeepLink('view_session', { classId });
};

export const createClassCreationLink = (template?: string) => {
  return deepLinkHandler.generateDeepLink('create_class', {
    ...(template && { template })
  });
};

// Hook for React components
export const useDeepLink = (callback: (data: DeepLinkData) => void) => {
  const [isListening, setIsListening] = React.useState(false);
  
  React.useEffect(() => {
    const unsubscribe = deepLinkHandler.onDeepLink(callback);
    setIsListening(true);
    
    return () => {
      unsubscribe();
      setIsListening(false);
    };
  }, [callback]);
  
  return { isListening };
};