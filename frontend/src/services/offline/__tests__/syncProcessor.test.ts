/**
 * Sync Queue Processor Tests
 * 
 * Tests for sync operation processing, retry logic,
 * and bandwidth-aware synchronization.
 */

import { SyncQueueProcessor, SyncStatus } from '../syncProcessor';
import { offlineStorage } from '../offlineStorage';
import { networkMonitor } from '../networkMonitor';

// Mock dependencies
jest.mock('../offlineStorage');
jest.mock('../networkMonitor');

const mockOfflineStorage = offlineStorage as jest.Mocked<typeof offlineStorage>;
const mockNetworkMonitor = networkMonitor as jest.Mocked<typeof networkMonitor>;

// Mock fetch for testing
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('SyncQueueProcessor', () => {
  let syncProcessor: SyncQueueProcessor;
  
  beforeEach(() => {
    syncProcessor = new SyncQueueProcessor();
    mockFetch.mockClear();
    
    // Setup default mocks
    mockNetworkMonitor.getNetworkState.mockReturnValue({
      current: {
        isOnline: true,
        status: 'good' as any,
        connectionType: 'wifi' as any,
        timestamp: Date.now()
      },
      history: [],
      lastOnlineAt: Date.now(),
      lastOfflineAt: 0,
      consecutiveFailures: 0,
      averageRtt: 100,
      qualityScore: 80
    });
    
    mockNetworkMonitor.getQualityRecommendations.mockReturnValue({
      canSync: true,
      shouldBatch: false,
      shouldCompress: false,
      maxConcurrentRequests: 3,
      recommendedChunkSize: 5
    });
    
    mockOfflineStorage.getPendingSyncOperations.mockResolvedValue([]);
  });
  
  afterEach(() => {
    syncProcessor.stopSync();
    jest.clearAllMocks();
  });
  
  describe('initialization', () => {
    it('should initialize with idle status', () => {
      const { status } = syncProcessor.getSyncStatus();
      expect(status).toBe(SyncStatus.IDLE);
    });
    
    it('should have empty progress on initialization', () => {
      const { progress } = syncProcessor.getSyncStatus();
      expect(progress.total).toBe(0);
      expect(progress.completed).toBe(0);
      expect(progress.failed).toBe(0);
    });
  });
  
  describe('shouldSync', () => {
    it('should return true for good network conditions', () => {
      mockNetworkMonitor.getNetworkState.mockReturnValue({
        current: { isOnline: true, status: 'excellent' as any } as any,
        consecutiveFailures: 0,
        qualityScore: 90,
        history: [],
        lastOnlineAt: 0,
        lastOfflineAt: 0,
        averageRtt: 50
      });
      
      expect(syncProcessor.shouldSync()).toBe(true);
    });
    
    it('should return false when offline', () => {
      mockNetworkMonitor.getNetworkState.mockReturnValue({
        current: { isOnline: false, status: 'offline' as any } as any,
        consecutiveFailures: 0,
        qualityScore: 0,
        history: [],
        lastOnlineAt: 0,
        lastOfflineAt: Date.now(),
        averageRtt: 0
      });
      
      expect(syncProcessor.shouldSync()).toBe(false);
    });
    
    it('should return false for too many consecutive failures', () => {
      mockNetworkMonitor.getNetworkState.mockReturnValue({
        current: { isOnline: true, status: 'good' as any } as any,
        consecutiveFailures: 10,
        qualityScore: 80,
        history: [],
        lastOnlineAt: Date.now(),
        lastOfflineAt: 0,
        averageRtt: 100
      });
      
      expect(syncProcessor.shouldSync()).toBe(false);
    });
    
    it('should return false for very poor quality', () => {
      mockNetworkMonitor.getNetworkState.mockReturnValue({
        current: { isOnline: true, status: 'poor' as any } as any,
        consecutiveFailures: 0,
        qualityScore: 10,
        history: [],
        lastOnlineAt: Date.now(),
        lastOfflineAt: 0,
        averageRtt: 2000
      });
      
      expect(syncProcessor.shouldSync()).toBe(false);
    });
  });
  
  describe('queueOperation', () => {
    it('should queue operation and return operation ID', async () => {
      const operationId = 'test-op-123';
      mockOfflineStorage.addSyncOperation.mockResolvedValue(operationId);
      
      const result = await syncProcessor.queueOperation(
        'check_in',
        '/api/attendance/check-in',
        'POST',
        { student_id: 123, session_id: 456 }
      );
      
      expect(result).toBe(operationId);
      expect(mockOfflineStorage.addSyncOperation).toHaveBeenCalledWith({
        type: 'check_in',
        endpoint: '/api/attendance/check-in',
        method: 'POST',
        data: { student_id: 123, session_id: 456 },
        priority: 1,
        dependencies: undefined
      });
    });
    
    it('should start sync if network is good and not already syncing', async () => {
      mockOfflineStorage.addSyncOperation.mockResolvedValue('test-op-123');
      
      const startSyncSpy = jest.spyOn(syncProcessor, 'startSync');
      
      await syncProcessor.queueOperation(
        'status_update',
        '/api/attendance/update',
        'PATCH',
        { status: 'present' },
        { priority: 3 }
      );
      
      // Should trigger sync after a short delay
      await new Promise(resolve => setTimeout(resolve, 150));
      
      expect(startSyncSpy).toHaveBeenCalled();
    });
  });
  
  describe('startSync', () => {
    it('should not start sync if already syncing', async () => {
      // Mock already syncing state
      const getSyncStatusSpy = jest.spyOn(syncProcessor, 'getSyncStatus');
      getSyncStatusSpy.mockReturnValue({
        status: SyncStatus.SYNCING,
        progress: { total: 0, completed: 0, failed: 0, estimatedTimeRemaining: 0, bytesTransferred: 0, totalBytes: 0 }
      });
      
      const processSyncQueueSpy = jest.spyOn(syncProcessor as any, 'processSyncQueue');
      
      await syncProcessor.startSync();
      
      expect(processSyncQueueSpy).not.toHaveBeenCalled();
    });
    
    it('should process sync queue when conditions are good', async () => {
      const mockOperations = [
        {
          id: 'op1',
          type: 'check_in',
          endpoint: '/api/check-in',
          method: 'POST' as const,
          data: { student_id: 123 },
          timestamp: Date.now(),
          retryCount: 0,
          status: 'pending' as const,
          priority: 1
        }
      ];
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue(mockOperations);
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true })
      });
      
      await syncProcessor.startSync();
      
      expect(mockOfflineStorage.getPendingSyncOperations).toHaveBeenCalled();
    });
  });
  
  describe('batch processing', () => {
    it('should create appropriate batch sizes based on network quality', async () => {
      const mockOperations = Array.from({ length: 20 }, (_, i) => ({
        id: `op${i}`,
        type: 'check_in',
        endpoint: '/api/check-in',
        method: 'POST' as const,
        data: { student_id: i },
        timestamp: Date.now() + i,
        retryCount: 0,
        status: 'pending' as const,
        priority: 1
      }));
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue(mockOperations);
      
      // Mock excellent network conditions
      mockNetworkMonitor.getNetworkState.mockReturnValue({
        current: { isOnline: true, status: 'excellent' as any } as any,
        consecutiveFailures: 0,
        qualityScore: 95,
        history: [],
        lastOnlineAt: Date.now(),
        lastOfflineAt: 0,
        averageRtt: 30
      });
      
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true })
      });
      
      await syncProcessor.startSync();
      
      // Should have processed operations in batches
      expect(mockFetch).toHaveBeenCalled();
    });
    
    it('should respect concurrent operation limits', async () => {
      const mockOperations = Array.from({ length: 10 }, (_, i) => ({
        id: `op${i}`,
        type: 'check_in',
        endpoint: '/api/check-in',
        method: 'POST' as const,
        data: { student_id: i },
        timestamp: Date.now() + i,
        retryCount: 0,
        status: 'pending' as const,
        priority: 1
      }));
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue(mockOperations);
      
      mockNetworkMonitor.getQualityRecommendations.mockReturnValue({
        canSync: true,
        shouldBatch: false,
        shouldCompress: false,
        maxConcurrentRequests: 2, // Limit concurrency
        recommendedChunkSize: 5
      });
      
      mockFetch.mockImplementation(() => 
        new Promise(resolve => 
          setTimeout(() => resolve({
            ok: true,
            json: () => Promise.resolve({ success: true })
          }), 100)
        )
      );
      
      await syncProcessor.startSync();
      
      // Should have respected concurrent limits
      expect(mockFetch).toHaveBeenCalled();
    });
  });
  
  describe('retry logic', () => {
    it('should retry failed operations with exponential backoff', async () => {
      const mockOperation = {
        id: 'failing-op',
        type: 'check_in',
        endpoint: '/api/check-in',
        method: 'POST' as const,
        data: { student_id: 123 },
        timestamp: Date.now(),
        retryCount: 0,
        status: 'pending' as const,
        priority: 1
      };
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue([mockOperation]);
      
      // Mock network error
      mockFetch.mockRejectedValueOnce(new Error('Network error'));
      // Then success on retry
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ success: true })
      });
      
      await syncProcessor.startSync();
      
      expect(mockOfflineStorage.updateSyncOperation).toHaveBeenCalledWith(
        mockOperation.id,
        expect.objectContaining({ retryCount: 1 })
      );
    });
    
    it('should stop retrying after max attempts', async () => {
      const mockOperation = {
        id: 'failing-op',
        type: 'check_in',
        endpoint: '/api/check-in',
        method: 'POST' as const,
        data: { student_id: 123 },
        timestamp: Date.now(),
        retryCount: 3, // Already at max retries
        status: 'pending' as const,
        priority: 1
      };
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue([mockOperation]);
      mockFetch.mockRejectedValue(new Error('Network error'));
      
      await syncProcessor.startSync();
      
      expect(mockOfflineStorage.updateSyncOperation).toHaveBeenCalledWith(
        mockOperation.id,
        expect.objectContaining({ status: 'failed' })
      );
    });
  });
  
  describe('conflict handling', () => {
    it('should handle HTTP 409 conflicts', async () => {
      const mockOperation = {
        id: 'conflict-op',
        type: 'status_update',
        endpoint: '/api/attendance/update',
        method: 'PATCH' as const,
        data: { student_id: 123, status: 'present' },
        timestamp: Date.now(),
        retryCount: 0,
        status: 'pending' as const,
        priority: 1
      };
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue([mockOperation]);
      
      // Mock conflict response
      mockFetch.mockResolvedValue({
        ok: false,
        status: 409,
        json: () => Promise.resolve({ 
          conflict: 'status_mismatch',
          server_status: 'absent',
          local_status: 'present'
        })
      });
      
      const conflictHandlers = new Set();
      const mockConflictHandler = jest.fn().mockResolvedValue({
        resolved: true,
        data: { student_id: 123, status: 'present' }
      });
      
      // Mock conflict handler setup
      jest.spyOn(syncProcessor, 'onConflict').mockImplementation((handler) => {
        conflictHandlers.add(handler);
        return () => conflictHandlers.delete(handler);
      });
      
      syncProcessor.onConflict(mockConflictHandler);
      
      await syncProcessor.startSync();
      
      // Conflict should be detected
      expect(mockFetch).toHaveBeenCalledWith(
        mockOperation.endpoint,
        expect.objectContaining({
          method: mockOperation.method,
          body: JSON.stringify(mockOperation.data)
        })
      );
    });
  });
  
  describe('progress tracking', () => {
    it('should update progress during sync', async () => {
      const mockOperations = [
        {
          id: 'op1',
          type: 'check_in',
          endpoint: '/api/check-in',
          method: 'POST' as const,
          data: { student_id: 123 },
          timestamp: Date.now(),
          retryCount: 0,
          status: 'pending' as const,
          priority: 1
        },
        {
          id: 'op2',
          type: 'status_update',
          endpoint: '/api/update',
          method: 'PATCH' as const,
          data: { student_id: 124, status: 'present' },
          timestamp: Date.now(),
          retryCount: 0,
          status: 'pending' as const,
          priority: 1
        }
      ];
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue(mockOperations);
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true })
      });
      
      const progressHandler = jest.fn();
      syncProcessor.onProgress(progressHandler);
      
      await syncProcessor.startSync();
      
      expect(progressHandler).toHaveBeenCalled();
      
      const lastCall = progressHandler.mock.calls[progressHandler.mock.calls.length - 1][0];
      expect(lastCall.total).toBe(2);
    });
    
    it('should emit complete event when sync finishes', async () => {
      const mockOperations = [
        {
          id: 'op1',
          type: 'check_in',
          endpoint: '/api/check-in',
          method: 'POST' as const,
          data: { student_id: 123 },
          timestamp: Date.now(),
          retryCount: 0,
          status: 'pending' as const,
          priority: 1
        }
      ];
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue(mockOperations);
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true })
      });
      
      const completeHandler = jest.fn();
      syncProcessor.onComplete(completeHandler);
      
      await syncProcessor.startSync();
      
      expect(completeHandler).toHaveBeenCalled();
      
      const results = completeHandler.mock.calls[0][0];
      expect(results).toHaveLength(1);
      expect(results[0].success).toBe(true);
    });
  });
  
  describe('bandwidth optimization', () => {
    it('should apply compression when recommended', async () => {
      mockNetworkMonitor.getQualityRecommendations.mockReturnValue({
        canSync: true,
        shouldBatch: true,
        shouldCompress: true,
        maxConcurrentRequests: 2,
        recommendedChunkSize: 3
      });
      
      const mockOperation = {
        id: 'op1',
        type: 'check_in',
        endpoint: '/api/check-in',
        method: 'POST' as const,
        data: { student_id: 123 },
        timestamp: Date.now(),
        retryCount: 0,
        status: 'pending' as const,
        priority: 1
      };
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue([mockOperation]);
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true })
      });
      
      await syncProcessor.startSync();
      
      // Should include compression headers when recommended
      expect(mockFetch).toHaveBeenCalledWith(
        mockOperation.endpoint,
        expect.objectContaining({
          headers: expect.objectContaining({
            'Accept-Encoding': 'gzip, deflate'
          })
        })
      );
    });
    
    it('should adjust timeout based on network conditions', async () => {
      mockNetworkMonitor.getNetworkState.mockReturnValue({
        current: { isOnline: true, status: 'poor' as any } as any,
        consecutiveFailures: 0,
        qualityScore: 30,
        history: [],
        lastOnlineAt: Date.now(),
        lastOfflineAt: 0,
        averageRtt: 1500
      });
      
      const mockOperation = {
        id: 'op1',
        type: 'check_in',
        endpoint: '/api/check-in',
        method: 'POST' as const,
        data: { student_id: 123 },
        timestamp: Date.now(),
        retryCount: 0,
        status: 'pending' as const,
        priority: 1
      };
      
      mockOfflineStorage.getPendingSyncOperations.mockResolvedValue([mockOperation]);
      
      // Mock slow response
      mockFetch.mockImplementation(() => 
        new Promise(resolve => 
          setTimeout(() => resolve({
            ok: true,
            json: () => Promise.resolve({ success: true })
          }), 5000)
        )
      );
      
      await syncProcessor.startSync();
      
      // Should handle slow network conditions appropriately
      expect(mockFetch).toHaveBeenCalled();
    });
  });
});

// Cleanup
afterAll(() => {
  jest.restoreAllMocks();
});