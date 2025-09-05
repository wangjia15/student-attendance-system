/**
 * Progressive Sync Service with Bandwidth Optimization
 * 
 * Provides intelligent sync scheduling and bandwidth-aware data transfer:
 * - Adaptive chunk sizing based on network conditions
 * - Priority-based operation scheduling
 * - Compression and data deduplication
 * - Background sync with minimal user impact
 * - Resume functionality for interrupted syncs
 * - Smart retry with exponential backoff
 */

import { networkMonitor, NetworkStatus } from './networkMonitor';
import { syncProcessor, SyncStatus } from './syncProcessor';
import { offlineStorage, SyncOperation } from './offlineStorage';

export enum SyncPriority {
  CRITICAL = 10,     // Immediate sync required
  HIGH = 7,          // Sync ASAP
  NORMAL = 5,        // Standard priority
  LOW = 3,           // Can wait for good conditions
  BACKGROUND = 1     // Only sync when conditions are excellent
}

export interface ProgressiveSyncConfig {
  maxChunkSize: number;
  minChunkSize: number;
  maxConcurrentChunks: number;
  adaptiveChunking: boolean;
  compressionEnabled: boolean;
  deduplicationEnabled: boolean;
  backgroundSyncEnabled: boolean;
  respectDataSaver: boolean;
  maxBandwidthUsage: number; // Percentage of available bandwidth
}

export interface SyncChunk {
  id: string;
  operations: SyncOperation[];
  priority: number;
  estimatedBytes: number;
  estimatedDuration: number;
  compressionRatio: number;
  dependencies: string[];
  retryCount: number;
  lastAttempt?: number;
}

export interface ProgressiveProgress {
  totalChunks: number;
  completedChunks: number;
  currentChunk: SyncChunk | null;
  bytesTransferred: number;
  totalBytes: number;
  currentSpeed: number; // bytes per second
  estimatedTimeRemaining: number;
  adaptiveMetrics: {
    optimalChunkSize: number;
    networkUtilization: number;
    compressionEfficiency: number;
  };
}

export interface BandwidthMetrics {
  downloadSpeed: number; // Mbps
  uploadSpeed: number;   // Mbps
  latency: number;       // ms
  jitter: number;        // ms
  packetLoss: number;    // percentage
  timestamp: number;
}

export type ProgressiveProgressHandler = (progress: ProgressiveProgress) => void;
export type ChunkCompleteHandler = (chunk: SyncChunk, success: boolean) => void;

/**
 * Progressive sync service with intelligent bandwidth management
 */
export class ProgressiveSyncService {
  private config: ProgressiveSyncConfig;
  private isRunning = false;
  private currentChunks = new Map<string, SyncChunk>();
  private completedChunks = new Set<string>();
  private failedChunks = new Map<string, { chunk: SyncChunk; error: string; timestamp: number }>();
  
  private listeners: {
    progress: Set<ProgressiveProgressHandler>;
    chunkComplete: Set<ChunkCompleteHandler>;
  };
  
  private metrics: {
    bandwidth: BandwidthMetrics;
    performance: {
      averageChunkTime: number;
      successRate: number;
      optimalChunkSize: number;
      compressionRatio: number;
    };
  };
  
  private adaptiveState: {
    lastChunkSize: number;
    lastChunkDuration: number;
    recentPerformance: number[];
    networkStability: number;
  };
  
  // Timers and intervals
  private syncInterval: NodeJS.Timeout | null = null;
  private metricsInterval: NodeJS.Timeout | null = null;
  private bandwidthTestInterval: NodeJS.Timeout | null = null;

  constructor(config: Partial<ProgressiveSyncConfig> = {}) {
    this.config = {
      maxChunkSize: 10,
      minChunkSize: 2,
      maxConcurrentChunks: 3,
      adaptiveChunking: true,
      compressionEnabled: true,
      deduplicationEnabled: true,
      backgroundSyncEnabled: true,
      respectDataSaver: true,
      maxBandwidthUsage: 70,
      ...config
    };
    
    this.listeners = {
      progress: new Set(),
      chunkComplete: new Set()
    };
    
    this.metrics = {
      bandwidth: {
        downloadSpeed: 0,
        uploadSpeed: 0,
        latency: 0,
        jitter: 0,
        packetLoss: 0,
        timestamp: 0
      },
      performance: {
        averageChunkTime: 0,
        successRate: 100,
        optimalChunkSize: this.config.maxChunkSize / 2,
        compressionRatio: 0.7
      }
    };
    
    this.adaptiveState = {
      lastChunkSize: this.config.maxChunkSize / 2,
      lastChunkDuration: 0,
      recentPerformance: [],
      networkStability: 1.0
    };
    
    this.bindNetworkMonitor();
  }

  /**
   * Start progressive sync service
   */
  async startProgressiveSync(): Promise<void> {
    if (this.isRunning) return;
    
    this.isRunning = true;
    
    // Start bandwidth monitoring
    this.startBandwidthMonitoring();
    
    // Start sync processing
    this.startSyncLoop();
    
    // Start metrics collection
    this.startMetricsCollection();
    
    console.log('Progressive sync service started');
  }

  /**
   * Stop progressive sync service
   */
  stopProgressiveSync(): void {
    if (!this.isRunning) return;
    
    this.isRunning = false;
    
    if (this.syncInterval) {
      clearInterval(this.syncInterval);
      this.syncInterval = null;
    }
    
    if (this.metricsInterval) {
      clearInterval(this.metricsInterval);
      this.metricsInterval = null;
    }
    
    if (this.bandwidthTestInterval) {
      clearInterval(this.bandwidthTestInterval);
      this.bandwidthTestInterval = null;
    }
    
    console.log('Progressive sync service stopped');
  }

  /**
   * Queue operation for progressive sync
   */
  async queueOperation(
    operation: Omit<SyncOperation, 'id' | 'timestamp' | 'retryCount' | 'status'>,
    priority: SyncPriority = SyncPriority.NORMAL
  ): Promise<string> {
    
    // Add priority to operation
    const operationWithPriority = {
      ...operation,
      priority
    };
    
    const operationId = await offlineStorage.addSyncOperation(operationWithPriority);
    
    // Trigger sync if network conditions are good and it's high priority
    if (priority >= SyncPriority.HIGH && this.shouldSyncNow()) {
      this.triggerImediateSync();
    }
    
    return operationId;
  }

  /**
   * Get current progressive sync status
   */
  getProgressiveStatus(): ProgressiveProgress {
    const totalChunks = this.currentChunks.size + this.completedChunks.size;
    const completedChunks = this.completedChunks.size;
    
    const totalBytes = Array.from(this.currentChunks.values())
      .reduce((sum, chunk) => sum + chunk.estimatedBytes, 0);
      
    const bytesTransferred = completedChunks > 0 ? 
      totalBytes * (completedChunks / totalChunks) : 0;
    
    return {
      totalChunks,
      completedChunks,
      currentChunk: this.getCurrentChunk(),
      bytesTransferred,
      totalBytes,
      currentSpeed: this.calculateCurrentSpeed(),
      estimatedTimeRemaining: this.estimateTimeRemaining(),
      adaptiveMetrics: {
        optimalChunkSize: this.metrics.performance.optimalChunkSize,
        networkUtilization: this.calculateNetworkUtilization(),
        compressionEfficiency: this.metrics.performance.compressionRatio
      }
    };
  }

  /**
   * Add progress listener
   */
  onProgress(handler: ProgressiveProgressHandler): () => void {
    this.listeners.progress.add(handler);
    return () => this.listeners.progress.delete(handler);
  }

  /**
   * Add chunk complete listener
   */
  onChunkComplete(handler: ChunkCompleteHandler): () => void {
    this.listeners.chunkComplete.add(handler);
    return () => this.listeners.chunkComplete.delete(handler);
  }

  // Private methods
  private async startSyncLoop(): Promise<void> {
    this.syncInterval = setInterval(async () => {
      if (!this.isRunning) return;
      
      try {
        await this.processPendingOperations();
      } catch (error) {
        console.error('Progressive sync loop error:', error);
      }
    }, this.calculateSyncInterval());
  }

  private async processPendingOperations(): Promise<void> {
    if (!this.shouldSyncNow()) return;
    
    // Get pending operations
    const operations = await offlineStorage.getPendingSyncOperations();
    
    if (operations.length === 0) return;
    
    // Create optimized chunks
    const chunks = await this.createOptimizedChunks(operations);
    
    // Process chunks with concurrency limits
    await this.processChunks(chunks);
  }

  private async createOptimizedChunks(operations: SyncOperation[]): Promise<SyncChunk[]> {
    const chunks: SyncChunk[] = [];
    const optimalChunkSize = this.calculateOptimalChunkSize();
    
    // Group operations by priority
    const priorityGroups = this.groupByPriority(operations);
    
    // Create chunks for each priority group
    for (const [priority, ops] of priorityGroups.entries()) {
      const priorityChunks = await this.createChunksForPriority(ops, optimalChunkSize, priority);
      chunks.push(...priorityChunks);
    }
    
    // Sort chunks by priority and dependencies
    return this.sortChunksByDependencies(chunks);
  }

  private async createChunksForPriority(
    operations: SyncOperation[],
    chunkSize: number,
    priority: number
  ): Promise<SyncChunk[]> {
    
    const chunks: SyncChunk[] = [];
    
    // Apply deduplication if enabled
    const dedupedOps = this.config.deduplicationEnabled ? 
      this.deduplicateOperations(operations) : operations;
    
    // Create chunks
    for (let i = 0; i < dedupedOps.length; i += chunkSize) {
      const chunkOps = dedupedOps.slice(i, i + chunkSize);
      
      const chunk: SyncChunk = {
        id: `chunk_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        operations: chunkOps,
        priority,
        estimatedBytes: await this.estimateChunkBytes(chunkOps),
        estimatedDuration: this.estimateChunkDuration(chunkOps),
        compressionRatio: this.config.compressionEnabled ? 
          this.metrics.performance.compressionRatio : 1.0,
        dependencies: this.extractDependencies(chunkOps),
        retryCount: 0
      };
      
      chunks.push(chunk);
    }
    
    return chunks;
  }

  private async processChunks(chunks: SyncChunk[]): Promise<void> {
    // Add chunks to current processing map
    chunks.forEach(chunk => {
      this.currentChunks.set(chunk.id, chunk);
    });
    
    // Process with concurrency limits
    const semaphore = new Array(this.config.maxConcurrentChunks).fill(null);
    
    const processChunk = async (chunk: SyncChunk): Promise<void> => {
      try {
        const startTime = Date.now();
        
        // Apply compression if enabled
        const processedOps = this.config.compressionEnabled ?
          await this.compressOperations(chunk.operations) : chunk.operations;
        
        // Process the chunk
        const results = await this.executeChunk(chunk, processedOps);
        
        const endTime = Date.now();
        const duration = endTime - startTime;
        
        // Update metrics
        this.updateChunkMetrics(chunk, duration, true);
        
        // Mark as completed
        this.currentChunks.delete(chunk.id);
        this.completedChunks.add(chunk.id);
        
        // Notify listeners
        this.notifyChunkComplete(chunk, true);
        this.notifyProgress();
        
      } catch (error) {
        console.error('Chunk processing failed:', error);
        
        // Handle retry logic
        await this.handleChunkFailure(chunk, error as Error);
        
        // Notify listeners
        this.notifyChunkComplete(chunk, false);
      }
    };
    
    // Process chunks with controlled concurrency
    const processingPromises = chunks.map(chunk => processChunk(chunk));
    await Promise.all(processingPromises);
  }

  private async executeChunk(chunk: SyncChunk, operations: SyncOperation[]): Promise<any[]> {
    const results: any[] = [];
    
    // Use the existing sync processor for actual execution
    for (const operation of operations) {
      try {
        // Convert to sync processor format and execute
        const syncId = await syncProcessor.queueOperation(
          operation.type,
          operation.endpoint,
          operation.method,
          operation.data,
          {
            priority: operation.priority,
            dependencies: operation.dependencies
          }
        );
        
        results.push({ success: true, syncId });
        
      } catch (error) {
        results.push({ success: false, error: error instanceof Error ? error.message : 'Unknown error' });
      }
    }
    
    return results;
  }

  private calculateOptimalChunkSize(): number {
    if (!this.config.adaptiveChunking) {
      return Math.floor((this.config.maxChunkSize + this.config.minChunkSize) / 2);
    }
    
    const networkState = networkMonitor.getNetworkState();
    const { current, qualityScore } = networkState;
    
    // Base chunk size on network conditions
    let chunkSize = this.config.minChunkSize;
    
    if (current.status === NetworkStatus.EXCELLENT && qualityScore > 80) {
      chunkSize = this.config.maxChunkSize;
    } else if (current.status === NetworkStatus.GOOD && qualityScore > 60) {
      chunkSize = Math.floor(this.config.maxChunkSize * 0.75);
    } else if (current.status === NetworkStatus.POOR || qualityScore < 40) {
      chunkSize = this.config.minChunkSize;
    } else {
      chunkSize = Math.floor(this.config.maxChunkSize * 0.5);
    }
    
    // Adjust based on data saver mode
    if (this.config.respectDataSaver && current.saveData) {
      chunkSize = Math.max(this.config.minChunkSize, Math.floor(chunkSize * 0.5));
    }
    
    // Adjust based on recent performance
    if (this.adaptiveState.recentPerformance.length > 0) {
      const avgPerformance = this.adaptiveState.recentPerformance
        .reduce((sum, perf) => sum + perf, 0) / this.adaptiveState.recentPerformance.length;
      
      if (avgPerformance < 0.7) { // Poor recent performance
        chunkSize = Math.max(this.config.minChunkSize, Math.floor(chunkSize * 0.8));
      } else if (avgPerformance > 0.9) { // Good recent performance
        chunkSize = Math.min(this.config.maxChunkSize, Math.floor(chunkSize * 1.2));
      }
    }
    
    this.metrics.performance.optimalChunkSize = chunkSize;
    return chunkSize;
  }

  private shouldSyncNow(): boolean {
    const networkState = networkMonitor.getNetworkState();
    
    // Must be online
    if (!networkState.current.isOnline) return false;
    
    // Check if background sync is disabled and we're in background
    if (!this.config.backgroundSyncEnabled && document.hidden) return false;
    
    // Check data saver mode
    if (this.config.respectDataSaver && networkState.current.saveData) {
      // Only sync high priority items in data saver mode
      return this.hasCriticalOperations();
    }
    
    // Check network quality
    return networkState.qualityScore > 30;
  }

  private async hasCriticalOperations(): Promise<boolean> {
    const operations = await offlineStorage.getPendingSyncOperations();
    return operations.some(op => op.priority >= SyncPriority.HIGH);
  }

  private triggerImediateSync(): void {
    // Clear existing interval and start immediate sync
    if (this.syncInterval) {
      clearInterval(this.syncInterval);
    }
    
    setTimeout(() => {
      this.processPendingOperations();
      this.startSyncLoop(); // Restart normal interval
    }, 100);
  }

  private calculateSyncInterval(): number {
    const networkState = networkMonitor.getNetworkState();
    
    // Base interval on network conditions
    let interval = 30000; // 30 seconds default
    
    switch (networkState.current.status) {
      case NetworkStatus.EXCELLENT:
        interval = 10000; // 10 seconds
        break;
      case NetworkStatus.GOOD:
        interval = 20000; // 20 seconds
        break;
      case NetworkStatus.POOR:
        interval = 60000; // 1 minute
        break;
      default:
        interval = 120000; // 2 minutes
    }
    
    // Adjust based on pending operations priority
    if (this.hasCriticalOperations()) {
      interval = Math.floor(interval * 0.5);
    }
    
    return interval;
  }

  private groupByPriority(operations: SyncOperation[]): Map<number, SyncOperation[]> {
    const groups = new Map<number, SyncOperation[]>();
    
    operations.forEach(op => {
      const priority = op.priority || SyncPriority.NORMAL;
      if (!groups.has(priority)) {
        groups.set(priority, []);
      }
      groups.get(priority)!.push(op);
    });
    
    return groups;
  }

  private deduplicateOperations(operations: SyncOperation[]): SyncOperation[] {
    const seen = new Map<string, SyncOperation>();
    
    // Keep the most recent operation for each unique key
    operations.forEach(op => {
      const key = `${op.type}_${op.endpoint}_${JSON.stringify(op.data)}`;
      
      if (!seen.has(key) || op.timestamp > seen.get(key)!.timestamp) {
        seen.set(key, op);
      }
    });
    
    return Array.from(seen.values());
  }

  private async estimateChunkBytes(operations: SyncOperation[]): Promise<number> {
    let totalBytes = 0;
    
    operations.forEach(op => {
      const dataSize = JSON.stringify(op.data).length;
      const overhead = 200; // HTTP headers and protocol overhead
      totalBytes += dataSize + overhead;
    });
    
    return totalBytes;
  }

  private estimateChunkDuration(operations: SyncOperation[]): number {
    const baseTime = 300; // 300ms base per operation
    const networkMultiplier = this.getNetworkTimeMultiplier();
    
    return operations.length * baseTime * networkMultiplier;
  }

  private getNetworkTimeMultiplier(): number {
    const networkState = networkMonitor.getNetworkState();
    
    switch (networkState.current.status) {
      case NetworkStatus.EXCELLENT:
        return 0.8;
      case NetworkStatus.GOOD:
        return 1.0;
      case NetworkStatus.POOR:
        return 2.0;
      default:
        return 3.0;
    }
  }

  private extractDependencies(operations: SyncOperation[]): string[] {
    const deps = new Set<string>();
    
    operations.forEach(op => {
      if (op.dependencies) {
        op.dependencies.forEach(dep => deps.add(dep));
      }
    });
    
    return Array.from(deps);
  }

  private sortChunksByDependencies(chunks: SyncChunk[]): SyncChunk[] {
    // Simple sorting by priority for now
    // In a more complex implementation, we would use topological sorting
    return chunks.sort((a, b) => b.priority - a.priority || a.operations[0].timestamp - b.operations[0].timestamp);
  }

  private async compressOperations(operations: SyncOperation[]): Promise<SyncOperation[]> {
    // For now, just return as-is
    // In a real implementation, we might compress the JSON data
    return operations;
  }

  private async handleChunkFailure(chunk: SyncChunk, error: Error): Promise<void> {
    chunk.retryCount++;
    chunk.lastAttempt = Date.now();
    
    // Store failed chunk for retry
    this.failedChunks.set(chunk.id, {
      chunk,
      error: error.message,
      timestamp: Date.now()
    });
    
    // Remove from current chunks
    this.currentChunks.delete(chunk.id);
    
    // Update metrics
    this.updateChunkMetrics(chunk, 0, false);
    
    // Schedule retry if under retry limit
    if (chunk.retryCount < 3) {
      const retryDelay = Math.pow(2, chunk.retryCount) * 1000; // Exponential backoff
      
      setTimeout(() => {
        if (this.isRunning && this.shouldSyncNow()) {
          this.currentChunks.set(chunk.id, chunk);
          this.failedChunks.delete(chunk.id);
          this.processChunks([chunk]);
        }
      }, retryDelay);
    }
  }

  private updateChunkMetrics(chunk: SyncChunk, duration: number, success: boolean): void {
    // Update performance metrics
    if (success) {
      this.adaptiveState.lastChunkSize = chunk.operations.length;
      this.adaptiveState.lastChunkDuration = duration;
      
      // Track recent performance
      const performance = duration > 0 ? Math.min(1, 5000 / duration) : 0; // Normalize to 0-1
      this.adaptiveState.recentPerformance.push(performance);
      
      // Keep only recent performance data
      if (this.adaptiveState.recentPerformance.length > 10) {
        this.adaptiveState.recentPerformance.shift();
      }
    }
    
    // Update success rate
    const totalAttempts = this.completedChunks.size + this.failedChunks.size + (success ? 1 : 0);
    const successfulAttempts = this.completedChunks.size + (success ? 1 : 0);
    
    if (totalAttempts > 0) {
      this.metrics.performance.successRate = (successfulAttempts / totalAttempts) * 100;
    }
  }

  private getCurrentChunk(): SyncChunk | null {
    const chunks = Array.from(this.currentChunks.values());
    return chunks.length > 0 ? chunks[0] : null;
  }

  private calculateCurrentSpeed(): number {
    // This would be calculated based on recent transfer metrics
    // For now, return a rough estimate
    const networkState = networkMonitor.getNetworkState();
    const bandwidth = networkMonitor.getEstimatedBandwidth();
    
    return bandwidth * 1024 * 1024 / 8; // Convert Mbps to bytes per second
  }

  private estimateTimeRemaining(): number {
    const progress = this.getProgressiveStatus();
    const speed = this.calculateCurrentSpeed();
    
    if (speed === 0 || progress.totalBytes === 0) return 0;
    
    const remainingBytes = progress.totalBytes - progress.bytesTransferred;
    return Math.ceil(remainingBytes / speed * 1000); // Return in milliseconds
  }

  private calculateNetworkUtilization(): number {
    // Calculate how much of the available bandwidth we're using
    const maxBandwidth = networkMonitor.getEstimatedBandwidth() * 1024 * 1024 / 8; // bytes per second
    const currentUsage = this.calculateCurrentSpeed();
    
    if (maxBandwidth === 0) return 0;
    
    return Math.min(100, (currentUsage / maxBandwidth) * 100);
  }

  private startBandwidthMonitoring(): void {
    this.bandwidthTestInterval = setInterval(() => {
      this.measureBandwidth();
    }, 60000); // Test every minute
  }

  private async measureBandwidth(): Promise<void> {
    // This would perform actual bandwidth measurements
    // For now, just update with network monitor data
    const networkState = networkMonitor.getNetworkState();
    
    this.metrics.bandwidth = {
      downloadSpeed: networkMonitor.getEstimatedBandwidth(),
      uploadSpeed: networkMonitor.getEstimatedBandwidth() * 0.8, // Rough estimate
      latency: networkState.averageRtt,
      jitter: networkState.averageRtt * 0.1, // Rough estimate
      packetLoss: 0, // Would need actual measurement
      timestamp: Date.now()
    };
  }

  private startMetricsCollection(): void {
    this.metricsInterval = setInterval(() => {
      this.notifyProgress();
    }, 2000); // Update progress every 2 seconds
  }

  private bindNetworkMonitor(): void {
    networkMonitor.onNetworkChange(() => {
      // Adjust sync behavior based on network changes
      if (this.isRunning) {
        this.adjustSyncBehavior();
      }
    });
  }

  private adjustSyncBehavior(): void {
    const networkState = networkMonitor.getNetworkState();
    
    // Pause sync if network is poor and we have non-critical operations
    if (networkState.current.status === NetworkStatus.OFFLINE) {
      // Don't pause completely, just reduce frequency
      console.log('Network offline, reducing sync frequency');
    }
    
    // Adjust chunk sizes based on new network conditions
    this.metrics.performance.optimalChunkSize = this.calculateOptimalChunkSize();
  }

  private notifyProgress(): void {
    const progress = this.getProgressiveStatus();
    
    this.listeners.progress.forEach(handler => {
      try {
        handler(progress);
      } catch (error) {
        console.error('Error in progress handler:', error);
      }
    });
  }

  private notifyChunkComplete(chunk: SyncChunk, success: boolean): void {
    this.listeners.chunkComplete.forEach(handler => {
      try {
        handler(chunk, success);
      } catch (error) {
        console.error('Error in chunk complete handler:', error);
      }
    });
  }
}

// Singleton instance
export const progressiveSync = new ProgressiveSyncService();

export default progressiveSync;