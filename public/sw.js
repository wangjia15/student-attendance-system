// Service Worker for Student Attendance System PWA
// Provides offline functionality, caching, and background sync

const CACHE_NAME = 'attendance-app-v1';
const STATIC_CACHE = 'attendance-static-v1';
const DYNAMIC_CACHE = 'attendance-dynamic-v1';

// Resources to cache immediately
const STATIC_ASSETS = [
  '/',
  '/static/js/bundle.js',
  '/static/css/main.css',
  '/manifest.json',
  '/images/icon-192x192.png',
  '/images/icon-512x512.png',
  // Add other critical assets
];

// API endpoints that should be cached
const CACHE_API_PATTERNS = [
  /\/api\/v1\/classes\/[^/]+$/,
  /\/api\/v1\/classes\/[^/]+\/stats$/,
  /\/api\/v1\/classes\/[^/]+\/share-link$/
];

// API endpoints that should NOT be cached (real-time data)
const NO_CACHE_API_PATTERNS = [
  /\/api\/v1\/classes\/create$/,
  /\/api\/v1\/classes\/[^/]+\/qr-code\/regenerate$/,
  /\/api\/v1\/classes\/[^/]+\/verification-code\/regenerate$/,
  /\/api\/v1\/classes\/[^/]+\/live-updates$/
];

self.addEventListener('install', (event) => {
  console.log('Service Worker: Installing...');
  
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => {
        console.log('Service Worker: Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => {
        console.log('Service Worker: Static assets cached');
        return self.skipWaiting();
      })
      .catch((error) => {
        console.error('Service Worker: Failed to cache static assets', error);
      })
  );
});

self.addEventListener('activate', (event) => {
  console.log('Service Worker: Activating...');
  
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames.map((cacheName) => {
            if (cacheName !== STATIC_CACHE && 
                cacheName !== DYNAMIC_CACHE && 
                cacheName !== CACHE_NAME) {
              console.log('Service Worker: Deleting old cache:', cacheName);
              return caches.delete(cacheName);
            }
          })
        );
      })
      .then(() => {
        console.log('Service Worker: Activated');
        return self.clients.claim();
      })
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests and chrome-extension requests
  if (request.method !== 'GET' || url.protocol.startsWith('chrome-extension')) {
    return;
  }

  // Handle API requests
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(handleApiRequest(request));
    return;
  }

  // Handle navigation requests (HTML pages)
  if (request.mode === 'navigate') {
    event.respondWith(handleNavigationRequest(request));
    return;
  }

  // Handle static assets
  event.respondWith(handleStaticAssets(request));
});

// Handle API requests with selective caching
async function handleApiRequest(request) {
  const url = new URL(request.url);
  
  // Check if this API should not be cached
  const shouldNotCache = NO_CACHE_API_PATTERNS.some(pattern => 
    pattern.test(url.pathname)
  );

  if (shouldNotCache) {
    try {
      return await fetch(request);
    } catch (error) {
      console.error('Service Worker: API request failed:', error);
      return new Response(
        JSON.stringify({ 
          error: 'Network unavailable', 
          offline: true 
        }),
        { 
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        }
      );
    }
  }

  // For cacheable APIs, use cache-first strategy
  const shouldCache = CACHE_API_PATTERNS.some(pattern => 
    pattern.test(url.pathname)
  );

  if (shouldCache) {
    try {
      const cache = await caches.open(DYNAMIC_CACHE);
      const cachedResponse = await cache.match(request);

      if (cachedResponse) {
        // Return cached response and update in background
        fetch(request)
          .then(response => {
            if (response.ok) {
              cache.put(request, response.clone());
            }
          })
          .catch(() => {
            // Ignore background update failures
          });
        
        return cachedResponse;
      }

      // Not in cache, fetch and cache
      const response = await fetch(request);
      if (response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    } catch (error) {
      console.error('Service Worker: API caching failed:', error);
      return new Response(
        JSON.stringify({ 
          error: 'Service temporarily unavailable', 
          offline: true 
        }),
        { 
          status: 503,
          headers: { 'Content-Type': 'application/json' }
        }
      );
    }
  }

  // Default: try network, no caching
  return fetch(request);
}

// Handle navigation requests with offline fallback
async function handleNavigationRequest(request) {
  try {
    // Try network first
    const response = await fetch(request);
    return response;
  } catch (error) {
    // Network failed, return cached index.html for SPA routing
    const cache = await caches.open(STATIC_CACHE);
    const cachedResponse = await cache.match('/');
    
    if (cachedResponse) {
      return cachedResponse;
    }

    // Fallback offline page
    return new Response(
      `<!DOCTYPE html>
      <html>
        <head>
          <title>Attendance - Offline</title>
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
                   text-align: center; padding: 2rem; background: #f8f9fa; }
            .offline-container { max-width: 400px; margin: 0 auto; }
            .offline-icon { font-size: 4rem; margin-bottom: 1rem; }
            h1 { color: #495057; margin-bottom: 1rem; }
            p { color: #6c757d; margin-bottom: 2rem; }
            button { background: #007bff; color: white; border: none; 
                     padding: 0.75rem 1.5rem; border-radius: 8px; cursor: pointer; }
          </style>
        </head>
        <body>
          <div class="offline-container">
            <div class="offline-icon">📴</div>
            <h1>You're Offline</h1>
            <p>Check your internet connection and try again.</p>
            <button onclick="window.location.reload()">Try Again</button>
          </div>
        </body>
      </html>`,
      {
        headers: { 'Content-Type': 'text/html' }
      }
    );
  }
}

// Handle static assets with cache-first strategy
async function handleStaticAssets(request) {
  try {
    const cache = await caches.open(STATIC_CACHE);
    const cachedResponse = await cache.match(request);

    if (cachedResponse) {
      return cachedResponse;
    }

    // Not in cache, fetch and cache if successful
    const response = await fetch(request);
    
    if (response.ok && response.status < 400) {
      // Cache successful responses
      cache.put(request, response.clone());
    }

    return response;
  } catch (error) {
    console.error('Service Worker: Static asset request failed:', error);
    
    // For images, return a placeholder
    if (request.destination === 'image') {
      return new Response(
        '<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg"><rect width="200" height="200" fill="#f8f9fa"/><text x="50%" y="50%" text-anchor="middle" dy=".3em" fill="#6c757d">Image Unavailable</text></svg>',
        { headers: { 'Content-Type': 'image/svg+xml' } }
      );
    }

    throw error;
  }
}

// Handle background sync for offline actions
self.addEventListener('sync', (event) => {
  console.log('Service Worker: Background sync triggered:', event.tag);
  
  if (event.tag === 'attendance-sync') {
    event.waitUntil(syncAttendanceData());
  }
});

// Sync attendance data when back online
async function syncAttendanceData() {
  try {
    // Get queued attendance actions from IndexedDB
    const queuedActions = await getQueuedActions();
    
    for (const action of queuedActions) {
      try {
        await fetch(action.url, {
          method: action.method,
          headers: action.headers,
          body: action.body
        });
        
        // Remove successfully synced action
        await removeQueuedAction(action.id);
        console.log('Service Worker: Synced action:', action.id);
      } catch (error) {
        console.error('Service Worker: Failed to sync action:', action.id, error);
      }
    }
  } catch (error) {
    console.error('Service Worker: Background sync failed:', error);
  }
}

// Handle push notifications (if implementing notifications)
self.addEventListener('push', (event) => {
  if (!event.data) return;

  const options = {
    body: event.data.text() || 'New attendance notification',
    icon: '/images/icon-192x192.png',
    badge: '/images/icon-96x96.png',
    tag: 'attendance-notification',
    requireInteraction: true,
    actions: [
      {
        action: 'open',
        title: 'View Dashboard'
      },
      {
        action: 'dismiss',
        title: 'Dismiss'
      }
    ]
  };

  event.waitUntil(
    self.registration.showNotification('Student Attendance', options)
  );
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'open') {
    event.waitUntil(
      clients.openWindow('/dashboard')
    );
  }
});

// Utility functions for IndexedDB operations (simplified)
async function getQueuedActions() {
  // Implementation would use IndexedDB to store offline actions
  return [];
}

async function removeQueuedAction(id) {
  // Implementation would remove action from IndexedDB
  console.log('Removing queued action:', id);
}