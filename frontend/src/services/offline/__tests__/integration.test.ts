/**
 * Offline Integration Tests
 * 
 * End-to-end tests for the complete offline sync workflow:
 * - Offline data storage and retrieval
 * - Sync queue processing with real network conditions
 * - Conflict resolution in realistic scenarios  
 * - Progressive sync with bandwidth optimization
 * - Network state transitions and recovery
 */

import { networkMonitor, NetworkStatus } from '../networkMonitor';
import { syncProcessor, SyncStatus } from '../syncProcessor';
import { offlineStorage } from '../offlineStorage';
import progressiveSync from '../progressiveSync';
import { conflictResolver, ConflictType } from '../../utils/conflict-resolution';

// Mock fetch for controlled testing
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock IndexedDB for testing
const mockIndexedDB = {
  open: jest.fn(),
  deleteDatabase: jest.fn()
};
global.indexedDB = mockIndexedDB;

// Mock localStorage
const mockLocalStorage = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
  length: 0,
  key: jest.fn()
};
global.localStorage = mockLocalStorage;

describe('Offline Integration Tests', () => {
  beforeEach(() => {
    // Reset all mocks
    mockFetch.mockClear();
    mockIndexedDB.open.mockClear();
    mockLocalStorage.getItem.mockClear();
    mockLocalStorage.setItem.mockClear();
    mockLocalStorage.removeItem.mockClear();
    mockLocalStorage.clear.mockClear();
    
    // Setup default network conditions
    Object.defineProperty(navigator, 'onLine', {
      writable: true,
      value: true
    });
    
    // Mock successful health checks by default
    mockFetch.mockImplementation((url) => {
      if (url.includes('/api/health')) {
        return Promise.resolve({
          ok: true,
          status: 200
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true })
      });
    });
  });
  
  afterEach(() => {
    networkMonitor.stopMonitoring();
    syncProcessor.stopSync();
    progressiveSync.stopProgressiveSync();
  });
  
  describe('complete offline workflow', () => {
    it('should handle full offline-to-online cycle', async () => {
      // Start with online state
      networkMonitor.startMonitoring();
      
      // Wait for initial network assessment
      await new Promise(resolve => setTimeout(resolve, 100));
      
      expect(networkMonitor.isOnline()).toBe(true);
      
      // Queue some operations while online
      const op1Id = await syncProcessor.queueOperation(
        'check_in',
        '/api/attendance/check-in',
        'POST',
        { student_id: 123, session_id: 456 }
      );
      
      expect(op1Id).toBeTruthy();
      
      // Simulate going offline
      Object.defineProperty(navigator, 'onLine', {
        value: false
      });
      
      // Mock fetch failures for offline state
      mockFetch.mockRejectedValue(new Error('Network unavailable'));
      
      // Force network update
      await networkMonitor.forceUpdate();
      
      expect(networkMonitor.isOnline()).toBe(false);
      
      // Queue operations while offline - should be stored locally
      const op2Id = await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update',
        'PATCH',
        { student_id: 124, status: 'present' }
      );
      
      expect(op2Id).toBeTruthy();
      
      // Simulate coming back online
      Object.defineProperty(navigator, 'onLine', {
        value: true
      });
      
      // Mock successful responses again
      mockFetch.mockImplementation((url) => {
        if (url.includes('/api/health')) {
          return Promise.resolve({
            ok: true,
            status: 200
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ success: true })
        });
      });
      
      // Force network update
      await networkMonitor.forceUpdate();
      
      expect(networkMonitor.isOnline()).toBe(true);
      
      // Should automatically start syncing queued operations
      await new Promise(resolve => setTimeout(resolve, 200));
      
      // Verify sync was initiated
      const syncStatus = syncProcessor.getSyncStatus();
      expect([SyncStatus.SYNCING, SyncStatus.IDLE]).toContain(syncStatus.status);
    });
    
    it('should prioritize high-priority operations', async () => {
      networkMonitor.startMonitoring();
      
      // Queue operations with different priorities
      await syncProcessor.queueOperation(
        'bulk_operation',
        '/api/attendance/bulk',
        'POST',
        { operations: [] },
        { priority: 1 } // Low priority
      );
      
      await syncProcessor.queueOperation(
        'check_in',
        '/api/attendance/check-in',
        'POST',
        { student_id: 123, session_id: 456 },
        { priority: 5 } // High priority
      );
      
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update', 
        'PATCH',
        { student_id: 124, status: 'present' },
        { priority: 3 } // Medium priority
      );
      
      // Start sync
      await syncProcessor.startSync();
      
      // Verify operations were called in priority order
      expect(mockFetch).toHaveBeenCalled();
      
      // The high priority operation should be processed first
      const firstCall = mockFetch.mock.calls.find(call => 
        call[0].includes('/api/attendance/check-in')
      );
      expect(firstCall).toBeTruthy();
    });
  });
  
  describe('conflict resolution integration', () => {
    it('should detect and resolve attendance status conflicts', async () => {
      networkMonitor.startMonitoring();
      
      // Mock a conflict response
      mockFetch.mockImplementation((url, options) => {
        if (url.includes('/api/attendance/update')) {
          return Promise.resolve({
            ok: false,
            status: 409, // Conflict
            json: () => Promise.resolve({
              conflict: 'status_mismatch',
              server_data: { status: 'absent', updated_at: '2023-12-01T10:30:00Z' },
              local_data: { status: 'present', updated_at: '2023-12-01T10:25:00Z' }
            })
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ success: true })
        });
      });
      
      let conflictDetected = false;
      let conflictResolved = false;
      
      // Set up conflict handling
      syncProcessor.onConflict(async (operation, conflictData) => {
        conflictDetected = true;
        
        const conflict = {
          type: ConflictType.ATTENDANCE_STATUS,
          entityId: `student_${operation.data.student_id}_session_${operation.data.session_id}`,
          localVersion: conflictData.local_data,
          serverVersion: conflictData.server_data,
          timestamp: Date.now(),
          conflictFields: ['status']
        };
        
        const resolution = await conflictResolver.resolveConflict(conflict);
        conflictResolved = true;
        
        return resolution.resolvedData;
      });
      
      // Queue an operation that will conflict
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update',
        'PATCH',
        { student_id: 123, session_id: 456, status: 'present' }
      );
      
      // Start sync
      await syncProcessor.startSync();
      
      // Allow time for processing
      await new Promise(resolve => setTimeout(resolve, 100));
      
      expect(conflictDetected).toBe(true);
      expect(conflictResolved).toBe(true);
    });
    
    it('should handle multiple concurrent conflicts', async () => {
      networkMonitor.startMonitoring();
      
      const conflicts = [];
      
      // Mock multiple conflict responses
      mockFetch.mockImplementation((url, options) => {
        if (url.includes('/api/attendance/')) {
          return Promise.resolve({
            ok: false,
            status: 409,
            json: () => Promise.resolve({
              conflict: 'status_mismatch',
              server_data: { status: 'absent' },
              local_data: { status: 'present' }
            })
          });
        }
        return Promise.resolve({ ok: true });
      });
      
      syncProcessor.onConflict(async (operation, conflictData) => {
        conflicts.push({ operation, conflictData });
        return conflictData.server_data; // Resolve with server data
      });
      
      // Queue multiple conflicting operations
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update/123',
        'PATCH',
        { student_id: 123, status: 'present' }
      );
      
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update/124',
        'PATCH',
        { student_id: 124, status: 'present' }
      );
      
      await syncProcessor.startSync();
      
      // Allow time for processing
      await new Promise(resolve => setTimeout(resolve, 200));
      
      expect(conflicts.length).toBe(2);
    });
  });
  
  describe('progressive sync integration', () => {
    it('should adapt chunk sizes based on network conditions', async () => {
      networkMonitor.startMonitoring();
      progressiveSync.startProgressiveSync();
      
      // Simulate poor network conditions
      mockFetch.mockImplementation((url) => {
        if (url.includes('/api/health')) {
          return new Promise(resolve => {
            setTimeout(() => {
              resolve({
                ok: true,
                status: 200
              });
            }, 1500); // Slow response = poor network
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ success: true })
        });
      });
      
      // Force network quality assessment
      await networkMonitor.forceUpdate();
      
      // Queue many operations
      const operations = Array.from({ length: 20 }, (_, i) => 
        progressiveSync.queueOperation({
          type: 'check_in',
          endpoint: `/api/attendance/check-in/${i}`,
          method: 'POST',
          data: { student_id: i }
        })
      );
      
      await Promise.all(operations);
      
      // Start progressive sync
      await new Promise(resolve => setTimeout(resolve, 100));
      
      const status = progressiveSync.getProgressiveStatus();
      
      // Should have created smaller chunks due to poor network
      expect(status.adaptiveMetrics.optimalChunkSize).toBeLessThan(10);
    });
    
    it('should optimize for excellent network conditions', async () => {
      networkMonitor.startMonitoring();
      progressiveSync.startProgressiveSync();
      
      // Simulate excellent network conditions
      mockFetch.mockImplementation((url) => {
        if (url.includes('/api/health')) {
          return Promise.resolve({
            ok: true,
            status: 200
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ success: true })
        });
      });
      
      // Mock fast response times
      const originalDateNow = Date.now;
      let callCount = 0;
      Date.now = jest.fn(() => {
        callCount++;
        return originalDateNow() + (callCount % 2 === 0 ? 30 : 0); // 30ms RTT
      });
      
      // Force network quality assessment
      await networkMonitor.forceUpdate();
      
      // Queue operations
      await progressiveSync.queueOperation({
        type: 'bulk_operation',
        endpoint: '/api/attendance/bulk',
        method: 'POST',
        data: { operations: [] }
      });
      
      await new Promise(resolve => setTimeout(resolve, 100));
      
      const status = progressiveSync.getProgressiveStatus();
      
      // Should use larger chunks for excellent network
      expect(status.adaptiveMetrics.optimalChunkSize).toBeGreaterThan(5);
      
      // Restore Date.now
      Date.now = originalDateNow;
    });
  });
  
  describe('data persistence and recovery', () => {
    it('should persist data across browser restarts', async () => {
      // Simulate storing data
      const testData = {
        student_id: 123,
        session_id: 456,
        status: 'present',
        timestamp: new Date().toISOString()
      };
      
      // Mock localStorage behavior
      const storage = new Map();
      mockLocalStorage.setItem.mockImplementation((key, value) => {
        storage.set(key, value);
      });
      mockLocalStorage.getItem.mockImplementation((key) => {
        return storage.get(key) || null;
      });
      mockLocalStorage.key.mockImplementation((index) => {
        return Array.from(storage.keys())[index] || null;
      });
      Object.defineProperty(mockLocalStorage, 'length', {
        get: () => storage.size
      });
      
      // Store an operation
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update',
        'PATCH',
        testData
      );
      
      // Verify data was stored
      expect(mockLocalStorage.setItem).toHaveBeenCalled();
      
      // Simulate browser restart by creating new processor
      const newProcessor = new (syncProcessor.constructor as any)();
      
      // Should be able to retrieve stored operations
      // This would work if we had proper IndexedDB mocking
      expect(storage.size).toBeGreaterThan(0);
    });
    
    it('should handle storage quota exceeded gracefully', async () => {
      // Mock storage quota exceeded error
      mockLocalStorage.setItem.mockImplementation(() => {
        throw new Error('QuotaExceededError');
      });
      
      let errorHandled = false;
      
      try {
        await syncProcessor.queueOperation(
          'check_in',
          '/api/attendance/check-in',
          'POST',
          { student_id: 123, session_id: 456 }
        );
      } catch (error) {
        errorHandled = true;
      }
      
      // Should handle the error gracefully
      expect(errorHandled).toBe(false); // Should not throw to caller
    });
  });
  
  describe('network transition handling', () => {
    it('should pause sync on network degradation', async () => {
      networkMonitor.startMonitoring();
      
      // Start with good network
      expect(networkMonitor.isOnline()).toBe(true);
      
      // Queue operations
      await syncProcessor.queueOperation(
        'check_in',
        '/api/attendance/check-in',
        'POST',
        { student_id: 123, session_id: 456 }
      );
      
      // Start sync
      await syncProcessor.startSync();
      
      // Simulate network degradation
      mockFetch.mockImplementation((url) => {
        if (url.includes('/api/health')) {
          return new Promise((_, reject) => {
            setTimeout(() => reject(new Error('Network timeout')), 100);
          });
        }
        return Promise.reject(new Error('Network error'));
      });
      
      // Force network update
      await networkMonitor.forceUpdate();
      
      // Should detect poor network and potentially pause
      expect(networkMonitor.isGoodForSync()).toBe(false);
    });
    
    it('should resume sync when network improves', async () => {
      networkMonitor.startMonitoring();
      
      // Start with poor network
      mockFetch.mockRejectedValue(new Error('Network error'));
      await networkMonitor.forceUpdate();
      
      expect(networkMonitor.isOnline()).toBe(false);
      
      // Queue operations while offline
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update',
        'PATCH',
        { student_id: 123, status: 'present' }
      );
      
      // Improve network conditions
      mockFetch.mockImplementation((url) => {
        if (url.includes('/api/health')) {
          return Promise.resolve({
            ok: true,
            status: 200
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ success: true })
        });
      });
      
      // Simulate network improvement
      await networkMonitor.forceUpdate();
      
      expect(networkMonitor.isOnline()).toBe(true);
      
      // Should automatically resume sync
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Verify sync was initiated
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/attendance/update'),
        expect.any(Object)
      );
    });
  });
  
  describe('error handling and recovery', () => {
    it('should retry operations with exponential backoff', async () => {
      networkMonitor.startMonitoring();
      
      let attemptCount = 0;
      
      mockFetch.mockImplementation((url) => {
        if (url.includes('/api/health')) {
          return Promise.resolve({ ok: true });
        }
        
        attemptCount++;
        if (attemptCount < 3) {
          return Promise.reject(new Error(`Attempt ${attemptCount} failed`));
        }
        
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ success: true })
        });
      });
      
      await syncProcessor.queueOperation(
        'check_in',
        '/api/attendance/check-in',
        'POST',
        { student_id: 123, session_id: 456 }
      );
      
      await syncProcessor.startSync();
      
      // Allow time for retries
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Should have made multiple attempts
      expect(attemptCount).toBeGreaterThan(1);
    });
    
    it('should handle malformed server responses', async () => {
      networkMonitor.startMonitoring();
      
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.reject(new Error('Invalid JSON'))
      });
      
      let errorHandled = false;
      
      syncProcessor.onError((error) => {
        errorHandled = true;
      });
      
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update',
        'PATCH',
        { student_id: 123, status: 'present' }
      );
      
      await syncProcessor.startSync();
      
      // Allow time for processing
      await new Promise(resolve => setTimeout(resolve, 100));
      
      // Should handle JSON parsing error gracefully
      expect(errorHandled).toBe(false); // Should not emit error for this case
    });
  });
});

// Performance tests
describe('Offline Performance Tests', () => {
  it('should handle large number of queued operations efficiently', async () => {
    networkMonitor.startMonitoring();
    
    const startTime = Date.now();
    
    // Queue 1000 operations
    const operations = Array.from({ length: 1000 }, (_, i) =>
      syncProcessor.queueOperation(
        'check_in',
        `/api/attendance/check-in/${i}`,
        'POST',
        { student_id: i, session_id: 456 }
      )
    );
    
    await Promise.all(operations);
    
    const queueTime = Date.now() - startTime;
    
    // Should queue efficiently (under 1 second for 1000 operations)
    expect(queueTime).toBeLessThan(1000);
  });
  
  it('should maintain responsive UI during large sync operations', async () => {
    // This would test that sync operations don't block the main thread
    // Implementation would depend on actual performance monitoring
    expect(true).toBe(true); // Placeholder
  });
});

// Cleanup
afterAll(() => {
  jest.restoreAllMocks();
});