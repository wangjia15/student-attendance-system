/**
 * Sync Queue Processor Service
 * 
 * Processes queued sync operations when connectivity is restored:
 * - Operation ordering and dependency resolution
 * - Intelligent retry logic with exponential backoff
 * - Bandwidth-aware processing
 * - Conflict detection and resolution integration
 * - Progress tracking and error handling
 */

import { offlineStorage, SyncOperation } from './offlineStorage';
import { networkMonitor, NetworkStatus } from './networkMonitor';

export enum SyncStatus {
  IDLE = 'idle',
  SYNCING = 'syncing',
  PAUSED = 'paused',
  ERROR = 'error'
}

export interface SyncProgress {
  total: number;
  completed: number;
  failed: number;
  current?: SyncOperation;
  estimatedTimeRemaining: number;
  currentOperation?: string;
  bytesTransferred: number;
  totalBytes: number;
}

export interface SyncResult {
  success: boolean;
  operationId: string;
  error?: string;
  conflictData?: any;
  serverResponse?: any;
  duration: number;
  retryCount: number;
}

export interface SyncBatch {
  id: string;
  operations: SyncOperation[];
  priority: number;
  estimatedDuration: number;
  estimatedBytes: number;
}

export type SyncProgressHandler = (progress: SyncProgress) => void;
export type SyncCompleteHandler = (results: SyncResult[]) => void;
export type SyncErrorHandler = (error: string, operation?: SyncOperation) => void;
export type ConflictHandler = (operation: SyncOperation, conflictData: any) => Promise<any>;

/**
 * Intelligent sync queue processor with bandwidth awareness and conflict resolution
 */
export class SyncQueueProcessor {
  private status: SyncStatus = SyncStatus.IDLE;
  private currentBatch: SyncBatch | null = null;
  private isProcessing = false;
  private abortController: AbortController | null = null;
  
  private listeners: {
    progress: Set<SyncProgressHandler>;
    complete: Set<SyncCompleteHandler>;
    error: Set<SyncErrorHandler>;
    conflict: Set<ConflictHandler>;
  };
  
  private progress: SyncProgress = {
    total: 0,
    completed: 0,
    failed: 0,
    estimatedTimeRemaining: 0,
    bytesTransferred: 0,
    totalBytes: 0
  };
  
  // Configuration
  private readonly MAX_RETRY_ATTEMPTS = 3;
  private readonly BASE_RETRY_DELAY = 1000; // 1 second
  private readonly MAX_RETRY_DELAY = 30000; // 30 seconds
  private readonly BATCH_SIZE_EXCELLENT = 10;
  private readonly BATCH_SIZE_GOOD = 5;
  private readonly BATCH_SIZE_POOR = 2;
  private readonly CONCURRENT_OPERATIONS = 3;
  
  constructor() {
    this.listeners = {
      progress: new Set(),
      complete: new Set(),
      error: new Set(),
      conflict: new Set()
    };
    
    this.bindNetworkMonitor();
  }

  /**
   * Start processing the sync queue
   */
  async startSync(force = false): Promise<void> {
    if (this.isProcessing && !force) {
      console.log('Sync already in progress');
      return;
    }
    
    if (!force && !this.shouldSync()) {
      console.log('Network conditions not suitable for sync');
      return;
    }
    
    try {
      this.isProcessing = true;
      this.status = SyncStatus.SYNCING;
      this.abortController = new AbortController();
      
      await this.processSyncQueue();
      
    } catch (error) {
      console.error('Sync process failed:', error);
      this.status = SyncStatus.ERROR;
      this.notifyError(`Sync failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
    } finally {
      this.isProcessing = false;
      if (this.status === SyncStatus.SYNCING) {
        this.status = SyncStatus.IDLE;
      }
      this.abortController = null;
    }
  }

  /**
   * Pause ongoing sync operations
   */
  pauseSync(): void {
    if (this.isProcessing) {
      this.status = SyncStatus.PAUSED;
      this.abortController?.abort();
    }
  }

  /**
   * Resume paused sync operations
   */
  async resumeSync(): Promise<void> {
    if (this.status === SyncStatus.PAUSED) {
      await this.startSync();
    }
  }

  /**
   * Stop and clear all sync operations
   */
  stopSync(): void {
    this.isProcessing = false;
    this.status = SyncStatus.IDLE;
    this.abortController?.abort();
    this.currentBatch = null;
    this.resetProgress();
  }

  /**
   * Add a sync operation to the queue
   */
  async queueOperation(
    type: SyncOperation['type'],
    endpoint: string,
    method: SyncOperation['method'],
    data: any,
    options: {
      priority?: number;
      dependencies?: string[];
      estimatedBytes?: number;
    } = {}
  ): Promise<string> {
    const operationId = await offlineStorage.addSyncOperation({
      type,
      endpoint,
      method,
      data,
      priority: options.priority || 1,
      dependencies: options.dependencies
    });
    
    // Start sync if network is good and we're not already syncing
    if (!this.isProcessing && this.shouldSync()) {
      setTimeout(() => this.startSync(), 100);
    }
    
    return operationId;
  }

  /**
   * Get current sync status and progress
   */
  getSyncStatus(): { status: SyncStatus; progress: SyncProgress } {
    return {
      status: this.status,
      progress: { ...this.progress }
    };
  }

  /**
   * Check if sync should be initiated based on network conditions
   */
  shouldSync(): boolean {
    const networkState = networkMonitor.getNetworkState();
    const { current, consecutiveFailures } = networkState;
    
    // Must be online
    if (!current.isOnline) return false;
    
    // Too many recent failures
    if (consecutiveFailures > 5) return false;
    
    // Network quality must be reasonable
    const qualityScore = networkState.qualityScore;
    if (qualityScore < 20) return false;
    
    return true;
  }

  /**
   * Add progress listener
   */
  onProgress(handler: SyncProgressHandler): () => void {
    this.listeners.progress.add(handler);
    return () => this.listeners.progress.delete(handler);
  }

  /**
   * Add completion listener
   */
  onComplete(handler: SyncCompleteHandler): () => void {
    this.listeners.complete.add(handler);
    return () => this.listeners.complete.delete(handler);
  }

  /**
   * Add error listener
   */
  onError(handler: SyncErrorHandler): () => void {
    this.listeners.error.add(handler);
    return () => this.listeners.error.delete(handler);
  }

  /**
   * Add conflict resolution handler
   */
  onConflict(handler: ConflictHandler): () => void {
    this.listeners.conflict.add(handler);
    return () => this.listeners.conflict.delete(handler);
  }

  // Private methods
  private async processSyncQueue(): Promise<void> {
    const operations = await offlineStorage.getPendingSyncOperations();
    
    if (operations.length === 0) {
      console.log('No pending sync operations');
      this.notifyComplete([]);
      return;
    }
    
    // Sort operations by priority and resolve dependencies
    const sortedOperations = await this.resolveDependencies(operations);
    const batches = this.createBatches(sortedOperations);
    
    this.initializeProgress(operations);
    
    const results: SyncResult[] = [];
    
    for (const batch of batches) {
      if (this.status !== SyncStatus.SYNCING) break;
      
      this.currentBatch = batch;
      const batchResults = await this.processBatch(batch);
      results.push(...batchResults);
      
      // Update progress
      this.progress.completed += batchResults.filter(r => r.success).length;
      this.progress.failed += batchResults.filter(r => !r.success).length;
      
      this.notifyProgress();
      
      // Check network conditions between batches
      if (!this.shouldContinueSync()) {
        console.log('Pausing sync due to network conditions');
        this.status = SyncStatus.PAUSED;
        break;
      }
    }
    
    this.currentBatch = null;
    this.notifyComplete(results);
  }

  private async resolveDependencies(operations: SyncOperation[]): Promise<SyncOperation[]> {
    const resolved: SyncOperation[] = [];
    const pending = [...operations];
    const processing = new Set<string>();
    
    while (pending.length > 0) {
      const canProcess = pending.filter(op => {
        // Check if all dependencies are resolved
        if (!op.dependencies || op.dependencies.length === 0) return true;
        
        return op.dependencies.every(depId => 
          resolved.some(resolved => resolved.id === depId) ||
          processing.has(depId)
        );
      });
      
      if (canProcess.length === 0) {
        // Circular dependency or missing dependency
        console.warn('Circular dependency detected, processing remaining operations');
        resolved.push(...pending);
        break;
      }
      
      // Sort by priority within the processable operations
      canProcess.sort((a, b) => b.priority - a.priority || a.timestamp - b.timestamp);
      
      const nextOp = canProcess[0];
      resolved.push(nextOp);
      processing.add(nextOp.id);
      
      // Remove from pending
      const index = pending.indexOf(nextOp);
      pending.splice(index, 1);
    }
    
    return resolved;
  }

  private createBatches(operations: SyncOperation[]): SyncBatch[] {
    const networkRecommendations = networkMonitor.getQualityRecommendations();
    const batchSize = this.getBatchSize();
    const batches: SyncBatch[] = [];
    
    for (let i = 0; i < operations.length; i += batchSize) {
      const batch = operations.slice(i, i + batchSize);
      const batchId = `batch_${Date.now()}_${i}`;
      
      batches.push({
        id: batchId,
        operations: batch,
        priority: Math.max(...batch.map(op => op.priority)),
        estimatedDuration: this.estimateBatchDuration(batch),
        estimatedBytes: this.estimateBatchBytes(batch)
      });
    }
    
    return batches;
  }

  private getBatchSize(): number {
    const networkState = networkMonitor.getNetworkState();
    
    switch (networkState.current.status) {
      case NetworkStatus.EXCELLENT:
        return this.BATCH_SIZE_EXCELLENT;
      case NetworkStatus.GOOD:
        return this.BATCH_SIZE_GOOD;
      case NetworkStatus.POOR:
        return this.BATCH_SIZE_POOR;
      default:
        return 1;
    }
  }

  private async processBatch(batch: SyncBatch): Promise<SyncResult[]> {
    const results: SyncResult[] = [];
    const networkRecommendations = networkMonitor.getQualityRecommendations();
    const maxConcurrent = Math.min(networkRecommendations.maxConcurrentRequests, this.CONCURRENT_OPERATIONS);
    
    // Process operations in chunks based on concurrency limits
    for (let i = 0; i < batch.operations.length; i += maxConcurrent) {
      if (this.status !== SyncStatus.SYNCING) break;
      
      const chunk = batch.operations.slice(i, i + maxConcurrent);
      const chunkPromises = chunk.map(operation => this.processOperation(operation));
      
      const chunkResults = await Promise.all(chunkPromises);
      results.push(...chunkResults);
    }
    
    return results;
  }

  private async processOperation(operation: SyncOperation): Promise<SyncResult> {
    const startTime = Date.now();
    
    try {
      // Update current operation in progress
      this.progress.current = operation;
      this.progress.currentOperation = `${operation.method} ${operation.endpoint}`;
      this.notifyProgress();
      
      const result = await this.executeOperation(operation);
      
      // Mark operation as completed
      await offlineStorage.updateSyncOperation(operation.id, { 
        status: 'completed' 
      });
      
      // Remove completed operation from queue
      await offlineStorage.removeSyncOperation(operation.id);
      
      return {
        success: true,
        operationId: operation.id,
        serverResponse: result,
        duration: Date.now() - startTime,
        retryCount: operation.retryCount
      };
      
    } catch (error) {
      console.error('Operation failed:', operation, error);
      
      const shouldRetry = operation.retryCount < this.MAX_RETRY_ATTEMPTS && 
                         this.isRetriableError(error);
      
      if (shouldRetry) {
        // Update retry count and schedule retry
        await offlineStorage.updateSyncOperation(operation.id, {
          retryCount: operation.retryCount + 1,
          status: 'pending'
        });
        
        // Wait before retrying
        const delay = this.calculateRetryDelay(operation.retryCount);
        await new Promise(resolve => setTimeout(resolve, delay));
        
        return this.processOperation({ ...operation, retryCount: operation.retryCount + 1 });
      } else {
        // Mark as failed
        await offlineStorage.updateSyncOperation(operation.id, {
          status: 'failed'
        });
        
        return {
          success: false,
          operationId: operation.id,
          error: error instanceof Error ? error.message : 'Unknown error',
          duration: Date.now() - startTime,
          retryCount: operation.retryCount
        };
      }
    }
  }

  private async executeOperation(operation: SyncOperation): Promise<any> {
    const networkRecommendations = networkMonitor.getQualityRecommendations();
    const timeout = this.calculateTimeout();
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };
    
    // Add compression if recommended
    if (networkRecommendations.shouldCompress) {
      headers['Accept-Encoding'] = 'gzip, deflate';
    }
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    
    try {
      const response = await fetch(operation.endpoint, {
        method: operation.method,
        headers,
        body: operation.method !== 'GET' ? JSON.stringify(operation.data) : undefined,
        signal: controller.signal
      });
      
      clearTimeout(timeoutId);
      
      if (!response.ok) {
        // Handle specific HTTP errors
        if (response.status === 409) {
          // Conflict - need resolution
          const conflictData = await response.json().catch(() => ({}));
          await this.handleConflict(operation, conflictData);
          throw new Error(`Conflict: ${response.status}`);
        } else if (response.status >= 400 && response.status < 500) {
          // Client error - don't retry
          throw new Error(`Client error: ${response.status}`);
        } else {
          // Server error - can retry
          throw new Error(`Server error: ${response.status}`);
        }
      }
      
      const result = await response.json().catch(() => ({}));
      
      // Update bytes transferred
      const responseSize = JSON.stringify(result).length;
      this.progress.bytesTransferred += responseSize;
      
      return result;
      
    } finally {
      clearTimeout(timeoutId);
    }
  }

  private async handleConflict(operation: SyncOperation, conflictData: any): Promise<void> {
    // Notify conflict handlers
    for (const handler of this.listeners.conflict) {
      try {
        const resolution = await handler(operation, conflictData);
        if (resolution) {
          // Update operation with resolved data
          await offlineStorage.updateSyncOperation(operation.id, {
            data: resolution
          });
          break;
        }
      } catch (error) {
        console.error('Conflict resolution failed:', error);
      }
    }
  }

  private isRetriableError(error: any): boolean {
    if (error instanceof Error) {
      const message = error.message.toLowerCase();
      
      // Network errors - retriable
      if (message.includes('network') || message.includes('fetch')) return true;
      
      // Timeout errors - retriable
      if (message.includes('timeout') || message.includes('aborted')) return true;
      
      // Server errors (5xx) - retriable
      if (message.includes('server error')) return true;
      
      // Client errors (4xx) - not retriable (except conflicts)
      if (message.includes('client error') && !message.includes('409')) return false;
    }
    
    return false;
  }

  private calculateRetryDelay(retryCount: number): number {
    const exponentialDelay = this.BASE_RETRY_DELAY * Math.pow(2, retryCount);
    const jitteredDelay = exponentialDelay + Math.random() * 1000; // Add jitter
    
    return Math.min(jitteredDelay, this.MAX_RETRY_DELAY);
  }

  private calculateTimeout(): number {
    const networkState = networkMonitor.getNetworkState();
    const baseTimeout = 10000; // 10 seconds
    
    switch (networkState.current.status) {
      case NetworkStatus.EXCELLENT:
        return baseTimeout;
      case NetworkStatus.GOOD:
        return baseTimeout * 1.5;
      case NetworkStatus.POOR:
        return baseTimeout * 2;
      default:
        return baseTimeout * 3;
    }
  }

  private shouldContinueSync(): boolean {
    const networkState = networkMonitor.getNetworkState();
    
    // Stop if offline
    if (!networkState.current.isOnline) return false;
    
    // Stop if too many failures
    if (networkState.consecutiveFailures > 3) return false;
    
    // Stop if quality dropped too much
    if (networkState.qualityScore < 10) return false;
    
    return true;
  }

  private estimateBatchDuration(operations: SyncOperation[]): number {
    const baseTime = 500; // 500ms base per operation
    const networkMultiplier = this.getNetworkTimeMultiplier();
    
    return operations.length * baseTime * networkMultiplier;
  }

  private estimateBatchBytes(operations: SyncOperation[]): number {
    return operations.reduce((total, op) => {
      const dataSize = JSON.stringify(op.data).length;
      return total + dataSize + 1024; // Add overhead
    }, 0);
  }

  private getNetworkTimeMultiplier(): number {
    const networkState = networkMonitor.getNetworkState();
    
    switch (networkState.current.status) {
      case NetworkStatus.EXCELLENT:
        return 1;
      case NetworkStatus.GOOD:
        return 1.5;
      case NetworkStatus.POOR:
        return 3;
      default:
        return 5;
    }
  }

  private initializeProgress(operations: SyncOperation[]): void {
    this.progress = {
      total: operations.length,
      completed: 0,
      failed: 0,
      estimatedTimeRemaining: this.estimateBatchDuration(operations),
      bytesTransferred: 0,
      totalBytes: this.estimateBatchBytes(operations)
    };
  }

  private resetProgress(): void {
    this.progress = {
      total: 0,
      completed: 0,
      failed: 0,
      estimatedTimeRemaining: 0,
      currentOperation: undefined,
      current: undefined,
      bytesTransferred: 0,
      totalBytes: 0
    };
  }

  private bindNetworkMonitor(): void {
    // Auto-start sync when coming back online
    networkMonitor.onConnectivityChange((isOnline) => {
      if (isOnline && !this.isProcessing) {
        setTimeout(() => {
          if (this.shouldSync()) {
            this.startSync();
          }
        }, 2000); // Wait 2 seconds for network to stabilize
      }
    });
  }

  private notifyProgress(): void {
    this.listeners.progress.forEach(handler => {
      try {
        handler({ ...this.progress });
      } catch (error) {
        console.error('Error in progress handler:', error);
      }
    });
  }

  private notifyComplete(results: SyncResult[]): void {
    this.listeners.complete.forEach(handler => {
      try {
        handler(results);
      } catch (error) {
        console.error('Error in complete handler:', error);
      }
    });
  }

  private notifyError(error: string, operation?: SyncOperation): void {
    this.listeners.error.forEach(handler => {
      try {
        handler(error, operation);
      } catch (error) {
        console.error('Error in error handler:', error);
      }
    });
  }
}

// Singleton instance
export const syncProcessor = new SyncQueueProcessor();

export default syncProcessor;