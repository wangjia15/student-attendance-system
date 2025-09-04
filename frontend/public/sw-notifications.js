/**
 * Service Worker for handling Web Push notifications
 */

const CACHE_NAME = 'attendance-notifications-v1';
const NOTIFICATION_ICON = '/icon-192x192.png';
const NOTIFICATION_BADGE = '/badge-72x72.png';

// Installation and activation
self.addEventListener('install', (event) => {
  console.log('Notification service worker installing...');
  
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll([
        NOTIFICATION_ICON,
        NOTIFICATION_BADGE,
        '/',
        '/attendance',
        '/dashboard'
      ]);
    })
  );
  
  // Take control immediately
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  console.log('Notification service worker activated');
  
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((cacheName) => cacheName !== CACHE_NAME)
          .map((cacheName) => caches.delete(cacheName))
      );
    })
  );
  
  // Take control of all clients
  self.clients.claim();
});

// Push notification handling
self.addEventListener('push', (event) => {
  console.log('Push notification received:', event);
  
  if (!event.data) {
    console.warn('Push event has no data');
    return;
  }
  
  try {
    const notificationData = event.data.json();
    console.log('Notification data:', notificationData);
    
    const options = buildNotificationOptions(notificationData);
    
    event.waitUntil(
      self.registration.showNotification(notificationData.title, options)
    );
  } catch (error) {
    console.error('Error handling push notification:', error);
    
    // Fallback notification
    event.waitUntil(
      self.registration.showNotification('New Notification', {
        body: 'You have a new attendance notification',
        icon: NOTIFICATION_ICON,
        badge: NOTIFICATION_BADGE,
        tag: 'fallback-notification'
      })
    );
  }
});

// Notification click handling
self.addEventListener('notificationclick', (event) => {
  console.log('Notification clicked:', event.notification);
  
  const notification = event.notification;
  const notificationData = notification.data || {};
  
  notification.close();
  
  event.waitUntil(
    handleNotificationClick(event.action, notificationData)
  );
});

// Notification close handling
self.addEventListener('notificationclose', (event) => {
  console.log('Notification closed:', event.notification);
  
  // Track notification dismissals for analytics
  const notificationData = event.notification.data || {};
  if (notificationData.id) {
    trackNotificationInteraction('dismissed', notificationData.id);
  }
});

/**
 * Build notification options from data
 */
function buildNotificationOptions(data) {
  const options = {
    body: data.body || data.message,
    icon: data.icon || NOTIFICATION_ICON,
    badge: data.badge || NOTIFICATION_BADGE,
    tag: data.tag || `notification-${Date.now()}`,
    data: data.data || {},
    timestamp: data.timestamp || Date.now(),
    requireInteraction: data.requireInteraction || false,
    silent: data.silent || false,
    renotify: true
  };
  
  // Add image if provided
  if (data.image) {
    options.image = data.image;
  }
  
  // Add actions for rich notifications
  if (data.actions && Array.isArray(data.actions)) {
    options.actions = data.actions.map(action => ({
      action: action.action,
      title: action.title,
      icon: action.icon
    }));
  }
  
  // Add vibration pattern based on priority
  if (data.priority) {
    switch (data.priority) {
      case 'urgent':
        options.vibrate = [300, 100, 300, 100, 300];
        options.requireInteraction = true;
        break;
      case 'high':
        options.vibrate = [200, 100, 200];
        break;
      case 'normal':
        options.vibrate = [100];
        break;
      case 'low':
        options.silent = true;
        options.vibrate = [];
        break;
    }
  }
  
  return options;
}

/**
 * Handle notification click events
 */
async function handleNotificationClick(action, notificationData) {
  console.log('Handling notification click:', action, notificationData);
  
  // Track the interaction
  if (notificationData.id) {
    trackNotificationInteraction(action || 'clicked', notificationData.id);
  }
  
  let targetUrl = '/';
  
  // Handle different actions
  switch (action) {
    case 'view_attendance':
      targetUrl = '/attendance';
      break;
    case 'join_class':
      if (notificationData.classId) {
        targetUrl = `/join-class/${notificationData.classId}`;
      }
      break;
    case 'view_dashboard':
      targetUrl = '/dashboard';
      break;
    case 'mark_read':
      // Just mark as read, don't navigate
      return markNotificationRead(notificationData.id);
    default:
      // Use click action from notification data
      if (notificationData.clickAction) {
        if (notificationData.clickAction.startsWith('http')) {
          // External URL - open in new tab
          return clients.openWindow(notificationData.clickAction);
        } else {
          targetUrl = notificationData.clickAction;
        }
      }
  }
  
  // Try to focus existing client or open new one
  const clients = await self.clients.matchAll({
    type: 'window',
    includeUncontrolled: true
  });
  
  // Check if we have a client with the target URL
  for (const client of clients) {
    if (client.url.includes(targetUrl.split('?')[0])) {
      client.focus();
      client.postMessage({
        type: 'NOTIFICATION_CLICKED',
        notification: notificationData,
        action: action
      });
      return;
    }
  }
  
  // Check if we have any client to navigate
  if (clients.length > 0) {
    const client = clients[0];
    client.focus();
    client.navigate(targetUrl);
    client.postMessage({
      type: 'NOTIFICATION_CLICKED',
      notification: notificationData,
      action: action
    });
  } else {
    // Open new window
    const fullUrl = self.registration.scope + targetUrl.substring(1);
    return clients.openWindow(fullUrl);
  }
}

/**
 * Track notification interaction for analytics
 */
function trackNotificationInteraction(action, notificationId) {
  // Send tracking data to backend if possible
  fetch('/api/v1/notifications/track', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      notification_id: notificationId,
      action: action,
      timestamp: Date.now()
    })
  }).catch(error => {
    console.warn('Failed to track notification interaction:', error);
  });
}

/**
 * Mark notification as read
 */
function markNotificationRead(notificationId) {
  if (!notificationId) return;
  
  fetch('/api/v1/notifications/mark-read', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      notification_id: notificationId
    })
  }).catch(error => {
    console.warn('Failed to mark notification as read:', error);
  });
}

// Background sync for offline notifications
self.addEventListener('sync', (event) => {
  if (event.tag === 'notification-sync') {
    console.log('Background sync triggered for notifications');
    event.waitUntil(syncOfflineNotifications());
  }
});

/**
 * Sync offline notifications when connection is restored
 */
async function syncOfflineNotifications() {
  try {
    // Get offline notification queue from IndexedDB or cache
    const cache = await caches.open(CACHE_NAME);
    const queuedNotifications = await getQueuedNotifications();
    
    if (queuedNotifications.length === 0) {
      return;
    }
    
    console.log(`Syncing ${queuedNotifications.length} offline notifications`);
    
    // Process each queued notification
    for (const notificationData of queuedNotifications) {
      try {
        const options = buildNotificationOptions(notificationData);
        await self.registration.showNotification(notificationData.title, options);
      } catch (error) {
        console.error('Failed to show queued notification:', error);
      }
    }
    
    // Clear the queue after successful sync
    await clearNotificationQueue();
    
  } catch (error) {
    console.error('Failed to sync offline notifications:', error);
  }
}

/**
 * Get queued notifications from storage
 */
async function getQueuedNotifications() {
  try {
    // In a real implementation, this would use IndexedDB
    // For now, we'll use a simple cache-based approach
    const cache = await caches.open(CACHE_NAME);
    const response = await cache.match('/notification-queue');
    
    if (response) {
      const data = await response.json();
      return data.notifications || [];
    }
    
    return [];
  } catch (error) {
    console.error('Failed to get queued notifications:', error);
    return [];
  }
}

/**
 * Clear notification queue
 */
async function clearNotificationQueue() {
  try {
    const cache = await caches.open(CACHE_NAME);
    await cache.delete('/notification-queue');
  } catch (error) {
    console.error('Failed to clear notification queue:', error);
  }
}

/**
 * Queue notification for offline processing
 */
async function queueNotificationForOffline(notificationData) {
  try {
    const cache = await caches.open(CACHE_NAME);
    const existingQueue = await getQueuedNotifications();
    
    existingQueue.push(notificationData);
    
    const response = new Response(JSON.stringify({
      notifications: existingQueue
    }), {
      headers: { 'Content-Type': 'application/json' }
    });
    
    await cache.put('/notification-queue', response);
    
    // Register for background sync
    await self.registration.sync.register('notification-sync');
    
  } catch (error) {
    console.error('Failed to queue notification for offline:', error);
  }
}

// Message handling from main thread
self.addEventListener('message', (event) => {
  console.log('Service worker received message:', event.data);
  
  if (event.data && event.data.type === 'QUEUE_NOTIFICATION') {
    queueNotificationForOffline(event.data.notification);
  }
});

// Network failure handling
self.addEventListener('fetch', (event) => {
  // Only handle notification-related requests
  if (!event.request.url.includes('/api/v1/notifications/')) {
    return;
  }
  
  event.respondWith(
    fetch(event.request).catch(error => {
      console.warn('Network request failed, handling offline:', error);
      
      // If this was a notification request, queue it for later
      if (event.request.method === 'POST' && 
          event.request.url.includes('/api/v1/notifications/send')) {
        // Extract notification data and queue it
        event.request.json().then(notificationData => {
          queueNotificationForOffline(notificationData);
        });
      }
      
      // Return a generic offline response
      return new Response(JSON.stringify({
        error: 'Offline',
        message: 'Request queued for when connection is restored'
      }), {
        status: 202,
        headers: { 'Content-Type': 'application/json' }
      });
    })
  );
});

console.log('Notification service worker loaded successfully');