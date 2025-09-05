/**
 * Network Monitor Service Tests
 * 
 * Tests for network state monitoring, connectivity detection,
 * and bandwidth estimation functionality.
 */

import { NetworkMonitorService, NetworkStatus, ConnectionType } from '../networkMonitor';

// Mock fetch for testing
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock navigator for testing
const mockNavigator = {
  onLine: true,
  connection: {
    type: 'wifi',
    effectiveType: '4g',
    downlink: 10,
    rtt: 50,
    saveData: false
  }
};

// @ts-ignore
global.navigator = mockNavigator;

// Mock window events
const mockAddEventListener = jest.fn();
const mockRemoveEventListener = jest.fn();
global.addEventListener = mockAddEventListener;
global.removeEventListener = mockRemoveEventListener;

describe('NetworkMonitorService', () => {
  let networkMonitor: NetworkMonitorService;
  
  beforeEach(() => {
    networkMonitor = new NetworkMonitorService();
    mockFetch.mockClear();
    mockAddEventListener.mockClear();
    mockRemoveEventListener.mockClear();
  });
  
  afterEach(() => {
    networkMonitor.stopMonitoring();
  });
  
  describe('initialization', () => {
    it('should initialize with correct default state', () => {
      const state = networkMonitor.getNetworkState();
      
      expect(state.current.isOnline).toBe(true);
      expect(state.current.connectionType).toBe(ConnectionType.WIFI);
      expect(state.history).toHaveLength(0);
      expect(state.lastOnlineAt).toBe(0);
      expect(state.consecutiveFailures).toBe(0);
    });
    
    it('should bind event listeners on construction', () => {
      new NetworkMonitorService();
      
      expect(mockAddEventListener).toHaveBeenCalledWith('online', expect.any(Function));
      expect(mockAddEventListener).toHaveBeenCalledWith('offline', expect.any(Function));
    });
  });
  
  describe('startMonitoring', () => {
    it('should start monitoring and begin periodic checks', (done) => {
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200
      });
      
      networkMonitor.startMonitoring();
      
      // Check that monitoring started
      setTimeout(() => {
        expect(mockFetch).toHaveBeenCalledWith('/api/health', expect.objectContaining({
          method: 'GET',
          cache: 'no-cache'
        }));
        done();
      }, 100);
    });
    
    it('should not start monitoring if already running', () => {
      networkMonitor.startMonitoring();
      const spy = jest.spyOn(networkMonitor, 'testConnection');
      
      networkMonitor.startMonitoring(); // Second call should be ignored
      
      expect(spy).toHaveBeenCalledTimes(1);
    });
  });
  
  describe('testConnection', () => {
    it('should resolve with online status when connection succeeds', async () => {
      const mockResponse = {
        ok: true,
        status: 200
      };
      mockFetch.mockResolvedValue(mockResponse);
      
      const result = await networkMonitor.testConnection();
      
      expect(result.isOnline).toBe(true);
      expect(result.timestamp).toBeGreaterThan(0);
      expect(result.rtt).toBeGreaterThan(0);
    });
    
    it('should resolve with offline status when connection fails', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));
      
      const result = await networkMonitor.testConnection();
      
      expect(result.isOnline).toBe(false);
      expect(result.status).toBe(NetworkStatus.OFFLINE);
    });
    
    it('should resolve with offline status on HTTP error', async () => {
      const mockResponse = {
        ok: false,
        status: 500
      };
      mockFetch.mockResolvedValue(mockResponse);
      
      const result = await networkMonitor.testConnection();
      
      expect(result.isOnline).toBe(false);
    });
    
    it('should timeout after specified duration', async () => {
      // Mock a long-running request
      mockFetch.mockImplementation(() => 
        new Promise(resolve => setTimeout(resolve, 10000))
      );
      
      const startTime = Date.now();
      const result = await networkMonitor.testConnection(1000); // 1 second timeout
      const endTime = Date.now();
      
      expect(endTime - startTime).toBeLessThan(2000); // Should timeout in ~1 second
      expect(result.isOnline).toBe(false);
    });
  });
  
  describe('network quality assessment', () => {
    it('should assess excellent network quality for low RTT', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200 });
      
      // Mock low RTT
      const startTime = Date.now();
      jest.spyOn(Date, 'now')
        .mockReturnValueOnce(startTime)
        .mockReturnValueOnce(startTime + 30); // 30ms RTT
      
      const result = await networkMonitor.testConnection();
      
      expect(result.status).toBe(NetworkStatus.EXCELLENT);
    });
    
    it('should assess poor network quality for high RTT', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200 });
      
      // Mock high RTT
      const startTime = Date.now();
      jest.spyOn(Date, 'now')
        .mockReturnValueOnce(startTime)
        .mockReturnValueOnce(startTime + 2500); // 2500ms RTT
      
      const result = await networkMonitor.testConnection();
      
      expect(result.status).toBe(NetworkStatus.POOR);
    });
  });
  
  describe('connection type detection', () => {
    it('should detect WiFi connection type', () => {
      const state = networkMonitor.getNetworkState();
      expect(state.current.connectionType).toBe(ConnectionType.WIFI);
    });
    
    it('should detect cellular connection type', () => {
      // Mock cellular connection
      // @ts-ignore
      global.navigator = {
        ...mockNavigator,
        connection: {
          ...mockNavigator.connection,
          type: 'cellular'
        }
      };
      
      const newMonitor = new NetworkMonitorService();
      const state = newMonitor.getNetworkState();
      
      expect(state.current.connectionType).toBe(ConnectionType.CELLULAR);
    });
    
    it('should handle unknown connection type', () => {
      // Mock unknown connection
      // @ts-ignore
      global.navigator = {
        ...mockNavigator,
        connection: {
          ...mockNavigator.connection,
          type: 'unknown'
        }
      };
      
      const newMonitor = new NetworkMonitorService();
      const state = newMonitor.getNetworkState();
      
      expect(state.current.connectionType).toBe(ConnectionType.UNKNOWN);
    });
  });
  
  describe('event listeners', () => {
    it('should call onNetworkChange handlers when network changes', (done) => {
      const handler = jest.fn();
      networkMonitor.onNetworkChange(handler);
      
      mockFetch.mockResolvedValue({ ok: true, status: 200 });
      
      networkMonitor.forceUpdate().then(() => {
        expect(handler).toHaveBeenCalled();
        done();
      });
    });
    
    it('should call onConnectivityChange handlers when connectivity changes', (done) => {
      const handler = jest.fn();
      networkMonitor.onConnectivityChange(handler);
      
      // Simulate going offline
      mockFetch.mockRejectedValue(new Error('Network error'));
      
      networkMonitor.forceUpdate().then(() => {
        expect(handler).toHaveBeenCalledWith(false);
        done();
      });
    });
    
    it('should remove event handlers when unsubscribe is called', () => {
      const handler = jest.fn();
      const unsubscribe = networkMonitor.onNetworkChange(handler);
      
      unsubscribe();
      
      // Handler should not be called after unsubscribe
      networkMonitor.forceUpdate();
      expect(handler).not.toHaveBeenCalled();
    });
  });
  
  describe('isGoodForSync', () => {
    it('should return true for good network conditions', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200 });
      
      // Mock good conditions
      const startTime = Date.now();
      jest.spyOn(Date, 'now')
        .mockReturnValueOnce(startTime)
        .mockReturnValueOnce(startTime + 100); // 100ms RTT
      
      await networkMonitor.forceUpdate();
      
      expect(networkMonitor.isGoodForSync()).toBe(true);
    });
    
    it('should return false for poor network conditions', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200 });
      
      // Mock poor conditions
      const startTime = Date.now();
      jest.spyOn(Date, 'now')
        .mockReturnValueOnce(startTime)
        .mockReturnValueOnce(startTime + 3000); // 3000ms RTT
      
      await networkMonitor.forceUpdate();
      
      expect(networkMonitor.isGoodForSync()).toBe(false);
    });
    
    it('should return false when offline', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));
      
      await networkMonitor.forceUpdate();
      
      expect(networkMonitor.isGoodForSync()).toBe(false);
    });
  });
  
  describe('bandwidth estimation', () => {
    it('should estimate bandwidth from connection info', () => {
      const bandwidth = networkMonitor.getEstimatedBandwidth();
      
      expect(bandwidth).toBeGreaterThan(0);
      expect(typeof bandwidth).toBe('number');
    });
    
    it('should provide quality recommendations', () => {
      const recommendations = networkMonitor.getQualityRecommendations();
      
      expect(recommendations).toHaveProperty('canSync');
      expect(recommendations).toHaveProperty('shouldBatch');
      expect(recommendations).toHaveProperty('shouldCompress');
      expect(recommendations).toHaveProperty('maxConcurrentRequests');
      expect(recommendations).toHaveProperty('recommendedChunkSize');
      
      expect(typeof recommendations.maxConcurrentRequests).toBe('number');
      expect(recommendations.maxConcurrentRequests).toBeGreaterThan(0);
    });
  });
  
  describe('statistics tracking', () => {
    it('should track consecutive failures', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));
      
      await networkMonitor.testConnection();
      await networkMonitor.testConnection();
      
      const state = networkMonitor.getNetworkState();
      expect(state.consecutiveFailures).toBe(2);
    });
    
    it('should reset consecutive failures on successful connection', async () => {
      // First fail
      mockFetch.mockRejectedValueOnce(new Error('Network error'));
      await networkMonitor.testConnection();
      
      // Then succeed
      mockFetch.mockResolvedValue({ ok: true, status: 200 });
      await networkMonitor.testConnection();
      
      const state = networkMonitor.getNetworkState();
      expect(state.consecutiveFailures).toBe(0);
    });
    
    it('should maintain network history', async () => {
      mockFetch.mockResolvedValue({ ok: true, status: 200 });
      
      await networkMonitor.forceUpdate();
      await networkMonitor.forceUpdate();
      
      const state = networkMonitor.getNetworkState();
      expect(state.history.length).toBeGreaterThan(0);
    });
  });
  
  describe('data saver mode', () => {
    it('should detect data saver mode', () => {
      // Mock data saver mode
      // @ts-ignore
      global.navigator = {
        ...mockNavigator,
        connection: {
          ...mockNavigator.connection,
          saveData: true
        }
      };
      
      const newMonitor = new NetworkMonitorService();
      const state = newMonitor.getNetworkState();
      
      expect(state.current.saveData).toBe(true);
    });
    
    it('should adjust recommendations for data saver mode', () => {
      // @ts-ignore
      global.navigator = {
        ...mockNavigator,
        connection: {
          ...mockNavigator.connection,
          saveData: true
        }
      };
      
      const newMonitor = new NetworkMonitorService();
      const recommendations = newMonitor.getQualityRecommendations();
      
      expect(recommendations.shouldCompress).toBe(true);
    });
  });
});

// Cleanup
afterAll(() => {
  // Restore original implementations
  jest.restoreAllMocks();
});