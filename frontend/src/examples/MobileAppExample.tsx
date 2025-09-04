import React from 'react';
import { MobileApp, initializeMobileApp } from '../components/MobileApp';

/**
 * Example usage of the Mobile-Optimized Class Creation System
 * 
 * This component demonstrates how to integrate the mobile app
 * into your application with proper URL handling and deep linking.
 */

// Example 1: Basic Mobile App Implementation
export const BasicMobileAppExample: React.FC = () => {
  return (
    <div style={{ width: '100%', minHeight: '100vh' }}>
      <MobileApp />
    </div>
  );
};

// Example 2: Mobile App with URL Parameter Initialization
export const URLInitializedMobileApp: React.FC = () => {
  // Get initial props from URL parameters
  const initialProps = initializeMobileApp();
  
  return (
    <div style={{ width: '100%', minHeight: '100vh' }}>
      <MobileApp {...initialProps} />
    </div>
  );
};

// Example 3: Mobile App with Specific Initial State
export const SpecificStateMobileApp: React.FC = () => {
  return (
    <div style={{ width: '100%', minHeight: '100vh' }}>
      <MobileApp
        initialView="create"
        // Optionally pre-fill with specific class data
      />
    </div>
  );
};

// Example 4: Mobile App for Joining a Specific Class
export const JoinClassMobileApp: React.FC<{ classId: string; code?: string }> = ({ 
  classId, 
  code 
}) => {
  return (
    <div style={{ width: '100%', minHeight: '100vh' }}>
      <MobileApp
        initialView="join"
        classId={classId}
        code={code}
      />
    </div>
  );
};

// Example 5: Integration with React Router
import { useParams, useLocation } from 'react-router-dom';

export const RouterIntegratedMobileApp: React.FC = () => {
  const params = useParams<{ classId?: string; action?: string }>();
  const location = useLocation();
  
  // Parse URL parameters
  const urlParams = new URLSearchParams(location.search);
  const code = urlParams.get('code') || undefined;
  const token = urlParams.get('token') || undefined;
  
  // Determine initial view from route
  let initialView: 'create' | 'join' | 'dashboard' | 'welcome' = 'welcome';
  if (params.action === 'create') {
    initialView = 'create';
  } else if (params.action === 'join' && params.classId) {
    initialView = 'join';
  } else if (params.action === 'dashboard') {
    initialView = 'dashboard';
  }
  
  return (
    <div style={{ width: '100%', minHeight: '100vh' }}>
      <MobileApp
        initialView={initialView}
        classId={params.classId}
        code={code}
        token={token}
      />
    </div>
  );
};

// Example 6: Standalone Class Creation Component
import { MobileClassCreation } from '../components/MobileClassCreation';

export const StandaloneClassCreation: React.FC = () => {
  const handleSessionCreated = (session: any) => {
    console.log('Class created:', session);
    // Handle successful creation
    // e.g., redirect to dashboard, show success message, etc.
  };

  const handleCancel = () => {
    console.log('Creation cancelled');
    // Handle cancellation
    // e.g., navigate back, close modal, etc.
  };

  return (
    <div style={{ width: '100%', minHeight: '100vh' }}>
      <MobileClassCreation
        onSessionCreated={handleSessionCreated}
        onCancel={handleCancel}
      />
    </div>
  );
};

// Example 7: Custom Hook Usage
import { useMobileClassCreation } from '../components/MobileClassCreation';

export const MobileFeatureDetection: React.FC = () => {
  const { 
    isMobile, 
    orientation, 
    isOnline, 
    canShare, 
    canInstall 
  } = useMobileClassCreation();

  return (
    <div style={{ padding: '1rem' }}>
      <h2>Mobile Features Detection</h2>
      <ul>
        <li>Is Mobile: {isMobile ? 'Yes' : 'No'}</li>
        <li>Orientation: {orientation}</li>
        <li>Online Status: {isOnline ? 'Online' : 'Offline'}</li>
        <li>Can Share: {canShare ? 'Yes' : 'No'}</li>
        <li>Can Install: {canInstall ? 'Yes' : 'No'}</li>
      </ul>
    </div>
  );
};

// Example 8: Deep Link Handling
import { useEffect } from 'react';
import { deepLinkHandler } from '../utils/deepLinking';

export const DeepLinkHandlingExample: React.FC = () => {
  useEffect(() => {
    const handleDeepLink = (linkData: any) => {
      console.log('Deep link received:', linkData);
      
      switch (linkData.type) {
        case 'join_class':
          // Navigate to join view with class data
          console.log('Joining class:', linkData.classId, linkData.code);
          break;
        case 'create_class':
          // Navigate to creation view
          console.log('Creating class with template:', linkData.parameters.template);
          break;
        case 'view_session':
          // Navigate to dashboard
          console.log('Viewing session:', linkData.classId);
          break;
      }
    };

    const unsubscribe = deepLinkHandler.onDeepLink(handleDeepLink);
    return unsubscribe;
  }, []);

  return (
    <div style={{ padding: '1rem' }}>
      <h2>Deep Link Handling Active</h2>
      <p>Check console for deep link events</p>
    </div>
  );
};

/**
 * Usage Instructions:
 * 
 * 1. Basic Integration:
 *    Import and use <MobileApp /> component directly
 * 
 * 2. URL-based Initialization:
 *    Use initializeMobileApp() to parse current URL and set initial state
 * 
 * 3. Custom Initial State:
 *    Pass specific props to control the initial view and data
 * 
 * 4. Router Integration:
 *    Use with React Router to handle navigation and deep linking
 * 
 * 5. Feature Detection:
 *    Use useMobileClassCreation() hook to detect device capabilities
 * 
 * 6. Deep Link Handling:
 *    Use deepLinkHandler to handle custom protocol and universal links
 * 
 * Supported URL Patterns:
 * - /create - Opens class creation view
 * - /join/:classId?code=123456 - Opens join view with pre-filled data
 * - /dashboard/:classId - Opens dashboard for specific class
 * - attendance://join/classId123?code=456789 - Custom protocol deep link
 */