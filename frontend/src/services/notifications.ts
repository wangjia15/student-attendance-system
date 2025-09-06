/**
 * Frontend notifications service for managing push notifications across all platforms
 */

// Notification types matching backend enums
export enum NotificationType {
  ATTENDANCE_REMINDER = 'attendance_reminder',
  LATE_ARRIVAL = 'late_arrival',
  ABSENT_ALERT = 'absent_alert',
  CLASS_STARTED = 'class_started',
  CLASS_ENDED = 'class_ended',
  PATTERN_ALERT = 'pattern_alert',
  SYSTEM_ANNOUNCEMENT = 'system_announcement',
  ACHIEVEMENT_BADGE = 'achievement_badge'
}

export enum NotificationPriority {
  LOW = 'low',
  NORMAL = 'normal',
  HIGH = 'high',
  URGENT = 'urgent'
}

export enum DevicePlatform {
  IOS = 'ios',
  ANDROID = 'android',
  WEB = 'web'
}

// Interfaces for notification data
export interface NotificationPreferences {
  enabled: boolean;
  quiet_hours_start?: string;
  quiet_hours_end?: string;
  attendance_reminders: boolean;
  late_arrival_alerts: boolean;
  absent_alerts: boolean;
  class_notifications: boolean;
  pattern_alerts: boolean;
  system_announcements: boolean;
  achievement_notifications: boolean;
  push_notifications: boolean;
  email_notifications: boolean;
  sms_notifications: boolean;
  batch_enabled: boolean;
  batch_interval_minutes: number;
  max_batch_size: number;
}

export interface NotificationAction {
  action: string;
  title: string;
  icon?: string;
}

export interface NotificationData {
  id?: number;
  type: NotificationType;
  priority: NotificationPriority;
  title: string;
  message: string;
  data?: Record<string, any>;
  actions?: NotificationAction[];
  image_url?: string;
  icon_url?: string;
  click_action?: string;
  timestamp?: number;
  tag?: string;
}

export interface DeviceTokenRegistration {
  platform: DevicePlatform;
  token: string;
  device_id?: string;
  device_name?: string;
  app_version?: string;
  os_version?: string;
}

class NotificationsService {
  private baseURL: string;
  private vapidPublicKey: string | null = null;
  private serviceWorkerRegistration: ServiceWorkerRegistration | null = null;
  private offlineQueue: NotificationData[] = [];
  
  constructor() {
    this.baseURL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    this.initializeService();
  }

  /**
   * Initialize the notifications service
   */
  private async initializeService(): Promise<void> {
    try {
      // Register service worker for web push notifications
      if ('serviceWorker' in navigator && 'PushManager' in window) {
        await this.registerServiceWorker();
      }

      // Get VAPID public key for web push
      await this.loadVapidPublicKey();

      // Process any queued offline notifications
      await this.processOfflineQueue();

      // Set up online/offline listeners
      window.addEventListener('online', () => this.processOfflineQueue());
      
    } catch (error) {
      console.error('Failed to initialize notifications service:', error);
    }
  }

  /**
   * Register service worker for web push notifications
   */
  private async registerServiceWorker(): Promise<void> {
    try {
      this.serviceWorkerRegistration = await navigator.serviceWorker.register(
        '/sw-notifications.js'
      );
      
      console.log('Notification service worker registered successfully');
      
      // Listen for messages from service worker
      navigator.serviceWorker.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'NOTIFICATION_CLICKED') {
          this.handleNotificationClick(event.data.notification);
        }
      });
      
    } catch (error) {
      console.error('Failed to register notification service worker:', error);
    }
  }

  /**
   * Load VAPID public key from server
   */
  private async loadVapidPublicKey(): Promise<void> {
    try {
      const response = await fetch(`${this.baseURL}/api/v1/notifications/vapid-key`);
      if (response.ok) {
        const data = await response.json();
        this.vapidPublicKey = data.public_key;
      }
    } catch (error) {
      console.error('Failed to load VAPID public key:', error);
    }
  }

  /**
   * Request notification permission from user
   */
  async requestPermission(): Promise<NotificationPermission> {
    if (!('Notification' in window)) {
      throw new Error('This browser does not support notifications');
    }

    if (Notification.permission === 'granted') {
      return 'granted';
    }

    if (Notification.permission === 'denied') {
      throw new Error('Notification permission denied');
    }

    const permission = await Notification.requestPermission();
    return permission;
  }

  /**
   * Subscribe to web push notifications
   */
  async subscribeToWebPush(): Promise<PushSubscription | null> {
    if (!this.serviceWorkerRegistration || !this.vapidPublicKey) {
      console.warn('Service worker or VAPID key not available');
      return null;
    }

    try {
      // Check if already subscribed
      const existingSubscription = await this.serviceWorkerRegistration.pushManager.getSubscription();
      if (existingSubscription) {
        return existingSubscription;
      }

      // Create new subscription
      const subscription = await this.serviceWorkerRegistration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: this.urlBase64ToUint8Array(this.vapidPublicKey)
      });

      // Register the subscription with the backend
      await this.registerDeviceToken({
        platform: DevicePlatform.WEB,
        token: JSON.stringify(subscription.toJSON()),
        device_name: navigator.userAgent,
        app_version: import.meta.env.VITE_APP_VERSION || '1.0.0'
      });

      return subscription;

    } catch (error) {
      console.error('Failed to subscribe to web push:', error);
      return null;
    }
  }

  /**
   * Unsubscribe from web push notifications
   */
  async unsubscribeFromWebPush(): Promise<boolean> {
    if (!this.serviceWorkerRegistration) {
      return false;
    }

    try {
      const subscription = await this.serviceWorkerRegistration.pushManager.getSubscription();
      if (subscription) {
        const success = await subscription.unsubscribe();
        if (success) {
          // Remove token from backend
          await this.unregisterDeviceToken(JSON.stringify(subscription.toJSON()));
        }
        return success;
      }
      return true;
    } catch (error) {
      console.error('Failed to unsubscribe from web push:', error);
      return false;
    }
  }

  /**
   * Register device token with backend
   */
  async registerDeviceToken(tokenData: DeviceTokenRegistration): Promise<boolean> {
    try {
      const authToken = localStorage.getItem('access_token');
      if (!authToken) {
        throw new Error('User not authenticated');
      }

      const response = await fetch(`${this.baseURL}/api/v1/notifications/register-token`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify(tokenData)
      });

      if (!response.ok) {
        throw new Error('Failed to register device token');
      }

      return true;
    } catch (error) {
      console.error('Failed to register device token:', error);
      return false;
    }
  }

  /**
   * Unregister device token from backend
   */
  async unregisterDeviceToken(token: string): Promise<boolean> {
    try {
      const authToken = localStorage.getItem('access_token');
      if (!authToken) {
        return true; // If not authenticated, consider it successful
      }

      const response = await fetch(`${this.baseURL}/api/v1/notifications/unregister-token`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify({ token })
      });

      return response.ok;
    } catch (error) {
      console.error('Failed to unregister device token:', error);
      return false;
    }
  }

  /**
   * Get user notification preferences
   */
  async getNotificationPreferences(): Promise<NotificationPreferences | null> {
    try {
      const authToken = localStorage.getItem('access_token');
      if (!authToken) {
        return null;
      }

      const response = await fetch(`${this.baseURL}/api/v1/notifications/preferences`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${authToken}`
        }
      });

      if (!response.ok) {
        throw new Error('Failed to get notification preferences');
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get notification preferences:', error);
      return null;
    }
  }

  /**
   * Update user notification preferences
   */
  async updateNotificationPreferences(preferences: Partial<NotificationPreferences>): Promise<boolean> {
    try {
      const authToken = localStorage.getItem('access_token');
      if (!authToken) {
        throw new Error('User not authenticated');
      }

      const response = await fetch(`${this.baseURL}/api/v1/notifications/preferences`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${authToken}`
        },
        body: JSON.stringify(preferences)
      });

      return response.ok;
    } catch (error) {
      console.error('Failed to update notification preferences:', error);
      return false;
    }
  }

  /**
   * Send local notification (fallback for when push notifications fail)
   */
  async sendLocalNotification(notification: NotificationData): Promise<void> {
    if (!('Notification' in window) || Notification.permission !== 'granted') {
      // Queue for later if offline or permission not granted
      this.queueNotificationForOffline(notification);
      return;
    }

    try {
      const localNotification = new Notification(notification.title, {
        body: notification.message,
        icon: notification.icon_url || '/icon-192x192.png',
        image: notification.image_url,
        tag: notification.tag || `notification-${Date.now()}`,
        data: notification.data,
        actions: notification.actions?.map(action => ({
          action: action.action,
          title: action.title,
          icon: action.icon
        })),
        requireInteraction: notification.priority === NotificationPriority.HIGH || 
                           notification.priority === NotificationPriority.URGENT,
        silent: notification.priority === NotificationPriority.LOW
      });

      // Handle click events
      localNotification.onclick = () => {
        this.handleNotificationClick(notification);
        localNotification.close();
      };

    } catch (error) {
      console.error('Failed to send local notification:', error);
      this.queueNotificationForOffline(notification);
    }
  }

  /**
   * Handle notification click events
   */
  private handleNotificationClick(notification: NotificationData): void {
    // Focus the window
    if (window.focus) {
      window.focus();
    }

    // Handle click action
    if (notification.click_action) {
      if (notification.click_action.startsWith('http')) {
        // External URL
        window.open(notification.click_action, '_blank');
      } else {
        // Internal route
        window.location.href = notification.click_action;
      }
    }

    // Custom event for notification click
    window.dispatchEvent(new CustomEvent('notification-click', {
      detail: notification
    }));
  }

  /**
   * Queue notification for offline processing
   */
  private queueNotificationForOffline(notification: NotificationData): void {
    try {
      this.offlineQueue.push(notification);
      
      // Store in localStorage for persistence across sessions
      const existingQueue = JSON.parse(
        localStorage.getItem('notification_queue') || '[]'
      );
      existingQueue.push(notification);
      localStorage.setItem('notification_queue', JSON.stringify(existingQueue));
      
    } catch (error) {
      console.error('Failed to queue notification for offline:', error);
    }
  }

  /**
   * Process queued offline notifications
   */
  private async processOfflineQueue(): Promise<void> {
    try {
      // Load queued notifications from localStorage
      const queuedNotifications = JSON.parse(
        localStorage.getItem('notification_queue') || '[]'
      );

      // Combine with memory queue
      const allQueued = [...this.offlineQueue, ...queuedNotifications];
      
      if (allQueued.length === 0) {
        return;
      }

      console.log(`Processing ${allQueued.length} queued notifications`);

      // Process each queued notification
      for (const notification of allQueued) {
        try {
          await this.sendLocalNotification(notification);
        } catch (error) {
          console.error('Failed to process queued notification:', error);
        }
      }

      // Clear the queues
      this.offlineQueue = [];
      localStorage.removeItem('notification_queue');

    } catch (error) {
      console.error('Failed to process offline notification queue:', error);
    }
  }

  /**
   * Check if notifications are supported and enabled
   */
  isNotificationSupported(): boolean {
    return 'Notification' in window && 'serviceWorker' in navigator;
  }

  /**
   * Check if user has granted notification permission
   */
  hasNotificationPermission(): boolean {
    return 'Notification' in window && Notification.permission === 'granted';
  }

  /**
   * Get notification permission status
   */
  getNotificationPermission(): NotificationPermission | null {
    if (!('Notification' in window)) {
      return null;
    }
    return Notification.permission;
  }

  /**
   * Utility function to convert VAPID key
   */
  private urlBase64ToUint8Array(base64String: string): Uint8Array {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding)
      .replace(/-/g, '+')
      .replace(/_/g, '/');

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  /**
   * Test notification functionality
   */
  async testNotification(): Promise<boolean> {
    try {
      const permission = await this.requestPermission();
      if (permission !== 'granted') {
        return false;
      }

      await this.sendLocalNotification({
        type: NotificationType.SYSTEM_ANNOUNCEMENT,
        priority: NotificationPriority.NORMAL,
        title: 'Test Notification',
        message: 'Notifications are working correctly!',
        icon_url: '/icon-192x192.png'
      });

      return true;
    } catch (error) {
      console.error('Test notification failed:', error);
      return false;
    }
  }
}

// Create singleton instance
const notificationsService = new NotificationsService();

// Export individual methods for easier importing
export const {
  requestPermission,
  subscribeToWebPush,
  unsubscribeFromWebPush,
  registerDeviceToken,
  unregisterDeviceToken,
  getNotificationPreferences,
  updateNotificationPreferences,
  sendLocalNotification,
  isNotificationSupported,
  hasNotificationPermission,
  getNotificationPermission,
  testNotification
} = notificationsService;

export default notificationsService;