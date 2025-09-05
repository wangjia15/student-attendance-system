/**
 * Network State Monitoring Service
 * 
 * Monitors network connectivity state and provides:
 * - Real-time connectivity status
 * - Connection type detection (WiFi, cellular, etc.)
 * - Bandwidth estimation and quality assessment
 * - Network change event handling
 * - Smart sync triggering based on network conditions
 */

export enum NetworkStatus {
  ONLINE = 'online',
  OFFLINE = 'offline',
  POOR = 'poor',
  GOOD = 'good',
  EXCELLENT = 'excellent'
}

export enum ConnectionType {
  ETHERNET = 'ethernet',
  WIFI = 'wifi',
  CELLULAR = 'cellular',
  BLUETOOTH = 'bluetooth',
  WIMAX = 'wimax',
  OTHER = 'other',
  UNKNOWN = 'unknown'
}

export interface NetworkInfo {
  isOnline: boolean;
  status: NetworkStatus;
  connectionType: ConnectionType;
  effectiveType?: '2g' | '3g' | '4g' | 'slow-2g';
  downlink?: number; // Mbps
  rtt?: number; // Round trip time in ms
  saveData?: boolean; // Data saver mode
  timestamp: number;
}

export interface NetworkState {
  current: NetworkInfo;
  history: NetworkInfo[];
  lastOnlineAt: number;
  lastOfflineAt: number;
  consecutiveFailures: number;
  averageRtt: number;
  qualityScore: number; // 0-100, higher is better
}

export type NetworkChangeHandler = (networkInfo: NetworkInfo, previousInfo: NetworkInfo) => void;
export type ConnectivityHandler = (isOnline: boolean) => void;

/**
 * Network monitoring service with bandwidth awareness and quality assessment
 */
export class NetworkMonitorService {
  private state: NetworkState;
  private listeners: {
    networkChange: Set<NetworkChangeHandler>;
    connectivity: Set<ConnectivityHandler>;
  };
  
  private checkInterval: NodeJS.Timeout | null = null;
  private qualityTestInterval: NodeJS.Timeout | null = null;
  private isMonitoring = false;
  
  // Configuration
  private readonly CHECK_INTERVAL = 5000; // Check every 5 seconds
  private readonly QUALITY_TEST_INTERVAL = 30000; // Test quality every 30 seconds
  private readonly HISTORY_LIMIT = 100;
  private readonly RTT_SAMPLES = 10;

  constructor() {
    this.state = {
      current: this.getInitialNetworkInfo(),
      history: [],
      lastOnlineAt: 0,
      lastOfflineAt: 0,
      consecutiveFailures: 0,
      averageRtt: 0,
      qualityScore: 50 // Neutral starting point
    };
    
    this.listeners = {
      networkChange: new Set(),
      connectivity: new Set()
    };

    this.bindEventListeners();
  }

  /**
   * Start monitoring network state
   */
  startMonitoring(): void {
    if (this.isMonitoring) return;
    
    this.isMonitoring = true;
    this.updateNetworkInfo();
    
    // Set up periodic checks
    this.checkInterval = setInterval(() => {
      this.updateNetworkInfo();
    }, this.CHECK_INTERVAL);
    
    // Set up quality testing
    this.qualityTestInterval = setInterval(() => {
      this.testNetworkQuality();
    }, this.QUALITY_TEST_INTERVAL);
    
    console.log('Network monitoring started');
  }

  /**
   * Stop monitoring network state
   */
  stopMonitoring(): void {
    if (!this.isMonitoring) return;
    
    this.isMonitoring = false;
    
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = null;
    }
    
    if (this.qualityTestInterval) {
      clearInterval(this.qualityTestInterval);
      this.qualityTestInterval = null;
    }
    
    console.log('Network monitoring stopped');
  }

  /**
   * Get current network state
   */
  getNetworkState(): NetworkState {
    return { ...this.state };
  }

  /**
   * Get current network info
   */
  getCurrentNetworkInfo(): NetworkInfo {
    return { ...this.state.current };
  }

  /**
   * Check if currently online
   */
  isOnline(): boolean {
    return this.state.current.isOnline;
  }

  /**
   * Check if network quality is good enough for sync operations
   */
  isGoodForSync(): boolean {
    const { current } = this.state;
    return current.isOnline && 
           (current.status === NetworkStatus.GOOD || current.status === NetworkStatus.EXCELLENT) &&
           this.state.qualityScore > 30;
  }

  /**
   * Check if network is suitable for large data transfers
   */
  isGoodForLargeTransfers(): boolean {
    const { current } = this.state;
    return current.isOnline && 
           current.status === NetworkStatus.EXCELLENT &&
           this.state.qualityScore > 60 &&
           !current.saveData;
  }

  /**
   * Get estimated bandwidth in Mbps
   */
  getEstimatedBandwidth(): number {
    return this.state.current.downlink || this.estimateBandwidthFromRtt();
  }

  /**
   * Add network change listener
   */
  onNetworkChange(handler: NetworkChangeHandler): () => void {
    this.listeners.networkChange.add(handler);
    return () => this.listeners.networkChange.delete(handler);
  }

  /**
   * Add connectivity change listener
   */
  onConnectivityChange(handler: ConnectivityHandler): () => void {
    this.listeners.connectivity.add(handler);
    return () => this.listeners.connectivity.delete(handler);
  }

  /**
   * Test connection by attempting a lightweight request
   */
  async testConnection(timeout = 5000): Promise<NetworkInfo> {
    const startTime = Date.now();
    
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);
      
      const response = await fetch('/api/health', {
        method: 'GET',
        signal: controller.signal,
        cache: 'no-cache'
      });
      
      clearTimeout(timeoutId);
      const rtt = Date.now() - startTime;
      
      if (response.ok) {
        this.state.consecutiveFailures = 0;
        this.updateRttAverage(rtt);
        return this.createNetworkInfo(true, rtt);
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (error) {
      this.state.consecutiveFailures++;
      console.warn('Connection test failed:', error);
      return this.createNetworkInfo(false);
    }
  }

  /**
   * Force a network state update
   */
  async forceUpdate(): Promise<NetworkInfo> {
    const networkInfo = await this.testConnection();
    this.updateState(networkInfo);
    return networkInfo;
  }

  /**
   * Get network quality recommendations
   */
  getQualityRecommendations(): {
    canSync: boolean;
    shouldBatch: boolean;
    shouldCompress: boolean;
    maxConcurrentRequests: number;
    recommendedChunkSize: number;
  } {
    const { current, qualityScore } = this.state;
    
    return {
      canSync: this.isGoodForSync(),
      shouldBatch: current.status !== NetworkStatus.EXCELLENT || current.saveData === true,
      shouldCompress: qualityScore < 70 || current.saveData === true,
      maxConcurrentRequests: this.getOptimalConcurrency(),
      recommendedChunkSize: this.getOptimalChunkSize()
    };
  }

  // Private methods
  private bindEventListeners(): void {
    if (typeof window === 'undefined') return;

    // Standard online/offline events
    window.addEventListener('online', this.handleOnlineEvent.bind(this));
    window.addEventListener('offline', this.handleOfflineEvent.bind(this));

    // Network Information API events (if supported)
    if ('connection' in navigator) {
      const connection = (navigator as any).connection;
      connection?.addEventListener?.('change', this.handleConnectionChange.bind(this));
    }
  }

  private getInitialNetworkInfo(): NetworkInfo {
    const isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true;
    return this.createNetworkInfo(isOnline);
  }

  private createNetworkInfo(isOnline: boolean, rtt?: number): NetworkInfo {
    const connection = typeof navigator !== 'undefined' ? (navigator as any).connection : null;
    
    const info: NetworkInfo = {
      isOnline,
      status: this.determineNetworkStatus(isOnline, rtt),
      connectionType: this.getConnectionType(connection),
      timestamp: Date.now()
    };

    // Add Network Information API data if available
    if (connection) {
      if (connection.effectiveType) info.effectiveType = connection.effectiveType;
      if (connection.downlink) info.downlink = connection.downlink;
      if (connection.rtt) info.rtt = connection.rtt;
      if (connection.saveData !== undefined) info.saveData = connection.saveData;
    }

    // Use measured RTT if available
    if (rtt !== undefined) {
      info.rtt = rtt;
    }

    return info;
  }

  private determineNetworkStatus(isOnline: boolean, rtt?: number): NetworkStatus {
    if (!isOnline) return NetworkStatus.OFFLINE;
    
    const effectiveRtt = rtt || this.state.averageRtt || 100;
    
    if (effectiveRtt > 2000) return NetworkStatus.POOR;
    if (effectiveRtt > 1000) return NetworkStatus.GOOD;
    return NetworkStatus.EXCELLENT;
  }

  private getConnectionType(connection: any): ConnectionType {
    if (!connection || !connection.type) return ConnectionType.UNKNOWN;
    
    const typeMapping: Record<string, ConnectionType> = {
      'ethernet': ConnectionType.ETHERNET,
      'wifi': ConnectionType.WIFI,
      'cellular': ConnectionType.CELLULAR,
      'bluetooth': ConnectionType.BLUETOOTH,
      'wimax': ConnectionType.WIMAX,
      'other': ConnectionType.OTHER
    };
    
    return typeMapping[connection.type] || ConnectionType.UNKNOWN;
  }

  private async updateNetworkInfo(): Promise<void> {
    const networkInfo = await this.testConnection();
    this.updateState(networkInfo);
  }

  private updateState(newInfo: NetworkInfo): void {
    const previousInfo = { ...this.state.current };
    const wasOnline = previousInfo.isOnline;
    const isOnline = newInfo.isOnline;
    
    // Update state
    this.state.current = newInfo;
    this.state.history.unshift(newInfo);
    
    // Limit history size
    if (this.state.history.length > this.HISTORY_LIMIT) {
      this.state.history = this.state.history.slice(0, this.HISTORY_LIMIT);
    }
    
    // Update timestamps
    if (isOnline && !wasOnline) {
      this.state.lastOnlineAt = newInfo.timestamp;
    } else if (!isOnline && wasOnline) {
      this.state.lastOfflineAt = newInfo.timestamp;
    }
    
    // Update quality score
    this.updateQualityScore();
    
    // Notify listeners
    this.notifyNetworkChange(newInfo, previousInfo);
    
    if (wasOnline !== isOnline) {
      this.notifyConnectivityChange(isOnline);
    }
  }

  private updateQualityScore(): void {
    const { current, history, consecutiveFailures } = this.state;
    
    let score = 50; // Base score
    
    // Adjust based on current status
    switch (current.status) {
      case NetworkStatus.EXCELLENT:
        score += 30;
        break;
      case NetworkStatus.GOOD:
        score += 10;
        break;
      case NetworkStatus.POOR:
        score -= 20;
        break;
      case NetworkStatus.OFFLINE:
        score = 0;
        break;
    }
    
    // Penalize consecutive failures
    score -= consecutiveFailures * 5;
    
    // Adjust based on recent history stability
    if (history.length >= 5) {
      const recentStatuses = history.slice(0, 5).map(h => h.status);
      const isStable = recentStatuses.every(s => s === recentStatuses[0]);
      if (isStable) {
        score += 10;
      } else {
        score -= 5;
      }
    }
    
    // Adjust for data saving mode
    if (current.saveData) {
      score -= 15;
    }
    
    this.state.qualityScore = Math.max(0, Math.min(100, score));
  }

  private updateRttAverage(newRtt: number): void {
    const { averageRtt } = this.state;
    
    if (averageRtt === 0) {
      this.state.averageRtt = newRtt;
    } else {
      // Exponential moving average
      this.state.averageRtt = averageRtt * 0.8 + newRtt * 0.2;
    }
  }

  private estimateBandwidthFromRtt(): number {
    const { averageRtt } = this.state;
    
    if (averageRtt === 0) return 1; // Default 1 Mbps
    
    // Very rough estimation based on RTT
    if (averageRtt < 50) return 10; // Excellent connection
    if (averageRtt < 150) return 5;  // Good connection
    if (averageRtt < 300) return 2;  // Fair connection
    return 0.5; // Poor connection
  }

  private async testNetworkQuality(): Promise<void> {
    if (!this.state.current.isOnline) return;
    
    try {
      const samples: number[] = [];
      
      // Take multiple RTT samples for better accuracy
      for (let i = 0; i < Math.min(this.RTT_SAMPLES, 3); i++) {
        const startTime = Date.now();
        
        try {
          await fetch('/api/health', { 
            method: 'HEAD',
            cache: 'no-cache'
          });
          
          samples.push(Date.now() - startTime);
        } catch (error) {
          // Skip failed samples
        }
      }
      
      if (samples.length > 0) {
        const avgRtt = samples.reduce((a, b) => a + b, 0) / samples.length;
        this.updateRttAverage(avgRtt);
      }
    } catch (error) {
      console.warn('Network quality test failed:', error);
    }
  }

  private getOptimalConcurrency(): number {
    const { qualityScore, current } = this.state;
    
    if (qualityScore > 80) return 4;
    if (qualityScore > 60) return 3;
    if (qualityScore > 40) return 2;
    return 1;
  }

  private getOptimalChunkSize(): number {
    const { qualityScore, current } = this.state;
    const bandwidth = this.getEstimatedBandwidth();
    
    // Base chunk size on bandwidth and quality
    if (current.saveData) return 1024; // 1KB for data saving
    if (bandwidth > 5 && qualityScore > 70) return 10 * 1024; // 10KB
    if (bandwidth > 2 && qualityScore > 50) return 5 * 1024;  // 5KB
    return 2 * 1024; // 2KB for poor connections
  }

  private notifyNetworkChange(current: NetworkInfo, previous: NetworkInfo): void {
    this.listeners.networkChange.forEach(handler => {
      try {
        handler(current, previous);
      } catch (error) {
        console.error('Error in network change handler:', error);
      }
    });
  }

  private notifyConnectivityChange(isOnline: boolean): void {
    this.listeners.connectivity.forEach(handler => {
      try {
        handler(isOnline);
      } catch (error) {
        console.error('Error in connectivity change handler:', error);
      }
    });
  }

  private handleOnlineEvent(): void {
    console.log('Browser reported online');
    this.forceUpdate();
  }

  private handleOfflineEvent(): void {
    console.log('Browser reported offline');
    const offlineInfo = this.createNetworkInfo(false);
    this.updateState(offlineInfo);
  }

  private handleConnectionChange(): void {
    console.log('Network connection properties changed');
    this.forceUpdate();
  }
}

// Singleton instance
export const networkMonitor = new NetworkMonitorService();

export default networkMonitor;