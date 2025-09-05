/**
 * Offline Data Storage Service
 * 
 * Provides offline-first data caching using IndexedDB with localStorage fallback.
 * Handles attendance records, sync operations, and network state management.
 */

import { AttendanceRecord, AttendanceState, ClassAttendanceStatus } from '../../types/attendance';

// Database configuration
const DB_NAME = 'AttendanceDB';
const DB_VERSION = 1;
const STORES = {
  ATTENDANCE_RECORDS: 'attendance_records',
  CLASS_STATUS: 'class_status',
  SYNC_QUEUE: 'sync_queue',
  META_DATA: 'meta_data'
} as const;

// Storage item types
export interface StorageItem<T = any> {
  id: string;
  data: T;
  timestamp: number;
  expires?: number;
  version: number;
}

export interface SyncOperation {
  id: string;
  type: 'check_in' | 'status_update' | 'bulk_operation';
  endpoint: string;
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  data: any;
  timestamp: number;
  retryCount: number;
  priority: number; // Higher number = higher priority
  dependencies?: string[]; // IDs of operations that must complete first
  status: 'pending' | 'processing' | 'completed' | 'failed';
}

export interface CacheStats {
  totalItems: number;
  totalSize: number;
  lastSync: number;
  pendingOperations: number;
  failedOperations: number;
}

/**
 * IndexedDB-based offline storage with localStorage fallback
 */
export class OfflineStorageService {
  private db: IDB.Database | null = null;
  private isIndexedDBAvailable = false;
  private initPromise: Promise<void> | null = null;
  
  constructor() {
    this.initPromise = this.initialize();
  }

  /**
   * Initialize the storage service
   */
  private async initialize(): Promise<void> {
    try {
      await this.initIndexedDB();
      this.isIndexedDBAvailable = true;
      console.log('Offline storage initialized with IndexedDB');
    } catch (error) {
      console.warn('IndexedDB not available, falling back to localStorage:', error);
      this.isIndexedDBAvailable = false;
    }
  }

  /**
   * Initialize IndexedDB database
   */
  private async initIndexedDB(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        reject(new Error('IndexedDB not supported'));
        return;
      }

      const request = indexedDB.open(DB_NAME, DB_VERSION);
      
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        this.db = request.result;
        resolve();
      };
      
      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        
        // Create stores if they don't exist
        if (!db.objectStoreNames.contains(STORES.ATTENDANCE_RECORDS)) {
          const attendanceStore = db.createObjectStore(STORES.ATTENDANCE_RECORDS, { keyPath: 'id' });
          attendanceStore.createIndex('class_session_id', 'data.class_session_id', { unique: false });
          attendanceStore.createIndex('timestamp', 'timestamp', { unique: false });
        }
        
        if (!db.objectStoreNames.contains(STORES.CLASS_STATUS)) {
          const statusStore = db.createObjectStore(STORES.CLASS_STATUS, { keyPath: 'id' });
          statusStore.createIndex('class_id', 'data.class_session_id', { unique: false });
        }
        
        if (!db.objectStoreNames.contains(STORES.SYNC_QUEUE)) {
          const syncStore = db.createObjectStore(STORES.SYNC_QUEUE, { keyPath: 'id' });
          syncStore.createIndex('priority', 'priority', { unique: false });
          syncStore.createIndex('status', 'status', { unique: false });
          syncStore.createIndex('timestamp', 'timestamp', { unique: false });
        }
        
        if (!db.objectStoreNames.contains(STORES.META_DATA)) {
          db.createObjectStore(STORES.META_DATA, { keyPath: 'id' });
        }
      };
    });
  }

  /**
   * Store attendance record
   */
  async storeAttendanceRecord(record: AttendanceRecord, ttl?: number): Promise<void> {
    await this.initPromise;
    
    const item: StorageItem<AttendanceRecord> = {
      id: `attendance_${record.id}`,
      data: record,
      timestamp: Date.now(),
      expires: ttl ? Date.now() + ttl : undefined,
      version: 1
    };

    if (this.isIndexedDBAvailable && this.db) {
      await this.storeInIndexedDB(STORES.ATTENDANCE_RECORDS, item);
    } else {
      this.storeInLocalStorage(`${STORES.ATTENDANCE_RECORDS}_${item.id}`, item);
    }
  }

  /**
   * Store class attendance status
   */
  async storeClassStatus(status: ClassAttendanceStatus, ttl?: number): Promise<void> {
    await this.initPromise;
    
    const item: StorageItem<ClassAttendanceStatus> = {
      id: `class_${status.class_session_id}`,
      data: status,
      timestamp: Date.now(),
      expires: ttl ? Date.now() + ttl : undefined,
      version: 1
    };

    if (this.isIndexedDBAvailable && this.db) {
      await this.storeInIndexedDB(STORES.CLASS_STATUS, item);
    } else {
      this.storeInLocalStorage(`${STORES.CLASS_STATUS}_${item.id}`, item);
    }
  }

  /**
   * Retrieve attendance record
   */
  async getAttendanceRecord(recordId: number): Promise<AttendanceRecord | null> {
    await this.initPromise;
    
    const id = `attendance_${recordId}`;
    
    if (this.isIndexedDBAvailable && this.db) {
      const item = await this.getFromIndexedDB<AttendanceRecord>(STORES.ATTENDANCE_RECORDS, id);
      return this.validateAndExtractData(item);
    } else {
      const item = this.getFromLocalStorage<AttendanceRecord>(`${STORES.ATTENDANCE_RECORDS}_${id}`);
      return this.validateAndExtractData(item);
    }
  }

  /**
   * Retrieve class status
   */
  async getClassStatus(classSessionId: number): Promise<ClassAttendanceStatus | null> {
    await this.initPromise;
    
    const id = `class_${classSessionId}`;
    
    if (this.isIndexedDBAvailable && this.db) {
      const item = await this.getFromIndexedDB<ClassAttendanceStatus>(STORES.CLASS_STATUS, id);
      return this.validateAndExtractData(item);
    } else {
      const item = this.getFromLocalStorage<ClassAttendanceStatus>(`${STORES.CLASS_STATUS}_${id}`);
      return this.validateAndExtractData(item);
    }
  }

  /**
   * Get all attendance records for a class session
   */
  async getClassAttendanceRecords(classSessionId: number): Promise<AttendanceRecord[]> {
    await this.initPromise;
    
    if (this.isIndexedDBAvailable && this.db) {
      return this.getRecordsFromIndexedDB(classSessionId);
    } else {
      return this.getRecordsFromLocalStorage(classSessionId);
    }
  }

  /**
   * Add sync operation to queue
   */
  async addSyncOperation(operation: Omit<SyncOperation, 'id' | 'timestamp' | 'retryCount' | 'status'>): Promise<string> {
    await this.initPromise;
    
    const syncOp: SyncOperation = {
      ...operation,
      id: `sync_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      timestamp: Date.now(),
      retryCount: 0,
      status: 'pending'
    };

    if (this.isIndexedDBAvailable && this.db) {
      await this.storeInIndexedDB(STORES.SYNC_QUEUE, syncOp);
    } else {
      this.storeInLocalStorage(`${STORES.SYNC_QUEUE}_${syncOp.id}`, syncOp);
    }

    return syncOp.id;
  }

  /**
   * Get pending sync operations sorted by priority
   */
  async getPendingSyncOperations(): Promise<SyncOperation[]> {
    await this.initPromise;
    
    if (this.isIndexedDBAvailable && this.db) {
      return this.getSyncOpsFromIndexedDB();
    } else {
      return this.getSyncOpsFromLocalStorage();
    }
  }

  /**
   * Update sync operation status
   */
  async updateSyncOperation(operationId: string, updates: Partial<SyncOperation>): Promise<void> {
    await this.initPromise;
    
    if (this.isIndexedDBAvailable && this.db) {
      const existing = await this.getFromIndexedDB<SyncOperation>(STORES.SYNC_QUEUE, operationId);
      if (existing) {
        const updated = { ...existing, ...updates };
        await this.storeInIndexedDB(STORES.SYNC_QUEUE, updated);
      }
    } else {
      const key = `${STORES.SYNC_QUEUE}_${operationId}`;
      const existing = this.getFromLocalStorage<SyncOperation>(key);
      if (existing) {
        const updated = { ...existing.data, ...updates };
        this.storeInLocalStorage(key, { ...existing, data: updated });
      }
    }
  }

  /**
   * Remove completed sync operation
   */
  async removeSyncOperation(operationId: string): Promise<void> {
    await this.initPromise;
    
    if (this.isIndexedDBAvailable && this.db) {
      await this.deleteFromIndexedDB(STORES.SYNC_QUEUE, operationId);
    } else {
      localStorage.removeItem(`${STORES.SYNC_QUEUE}_${operationId}`);
    }
  }

  /**
   * Clear expired items
   */
  async clearExpiredItems(): Promise<void> {
    await this.initPromise;
    
    const now = Date.now();
    
    if (this.isIndexedDBAvailable && this.db) {
      await this.clearExpiredFromIndexedDB(now);
    } else {
      this.clearExpiredFromLocalStorage(now);
    }
  }

  /**
   * Get cache statistics
   */
  async getCacheStats(): Promise<CacheStats> {
    await this.initPromise;
    
    if (this.isIndexedDBAvailable && this.db) {
      return this.getIndexedDBStats();
    } else {
      return this.getLocalStorageStats();
    }
  }

  /**
   * Clear all cached data
   */
  async clearAllCache(): Promise<void> {
    await this.initPromise;
    
    if (this.isIndexedDBAvailable && this.db) {
      await this.clearIndexedDB();
    } else {
      this.clearLocalStorageCache();
    }
  }

  // Private methods for IndexedDB operations
  private async storeInIndexedDB(storeName: string, data: any): Promise<void> {
    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      const request = store.put(data);
      
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  private async getFromIndexedDB<T>(storeName: string, id: string): Promise<StorageItem<T> | null> {
    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([storeName], 'readonly');
      const store = transaction.objectStore(storeName);
      const request = store.get(id);
      
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
    });
  }

  private async deleteFromIndexedDB(storeName: string, id: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      const request = store.delete(id);
      
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  private async getRecordsFromIndexedDB(classSessionId: number): Promise<AttendanceRecord[]> {
    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([STORES.ATTENDANCE_RECORDS], 'readonly');
      const store = transaction.objectStore(STORES.ATTENDANCE_RECORDS);
      const index = store.index('class_session_id');
      const request = index.getAll(classSessionId);
      
      request.onsuccess = () => {
        const items: StorageItem<AttendanceRecord>[] = request.result;
        const validRecords = items
          .map(item => this.validateAndExtractData(item))
          .filter(record => record !== null) as AttendanceRecord[];
        resolve(validRecords);
      };
      request.onerror = () => reject(request.error);
    });
  }

  private async getSyncOpsFromIndexedDB(): Promise<SyncOperation[]> {
    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction([STORES.SYNC_QUEUE], 'readonly');
      const store = transaction.objectStore(STORES.SYNC_QUEUE);
      const index = store.index('status');
      const request = index.getAll('pending');
      
      request.onsuccess = () => {
        const operations: SyncOperation[] = request.result;
        // Sort by priority (higher first) then timestamp (older first)
        operations.sort((a, b) => b.priority - a.priority || a.timestamp - b.timestamp);
        resolve(operations);
      };
      request.onerror = () => reject(request.error);
    });
  }

  private async clearExpiredFromIndexedDB(now: number): Promise<void> {
    for (const storeName of [STORES.ATTENDANCE_RECORDS, STORES.CLASS_STATUS]) {
      const transaction = this.db!.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      const request = store.openCursor();
      
      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest).result;
        if (cursor) {
          const item: StorageItem = cursor.value;
          if (item.expires && item.expires < now) {
            cursor.delete();
          }
          cursor.continue();
        }
      };
    }
  }

  private async getIndexedDBStats(): Promise<CacheStats> {
    let totalItems = 0;
    let totalSize = 0;
    let pendingOperations = 0;
    let failedOperations = 0;
    let lastSync = 0;

    // Count items in each store
    for (const storeName of Object.values(STORES)) {
      const transaction = this.db!.transaction([storeName], 'readonly');
      const store = transaction.objectStore(storeName);
      const countRequest = store.count();
      
      await new Promise<void>((resolve) => {
        countRequest.onsuccess = () => {
          totalItems += countRequest.result;
          resolve();
        };
      });
    }

    // Get sync queue stats
    const syncTransaction = this.db!.transaction([STORES.SYNC_QUEUE], 'readonly');
    const syncStore = syncTransaction.objectStore(STORES.SYNC_QUEUE);
    const allSyncOps = await new Promise<SyncOperation[]>((resolve) => {
      const request = syncStore.getAll();
      request.onsuccess = () => resolve(request.result);
    });

    pendingOperations = allSyncOps.filter(op => op.status === 'pending').length;
    failedOperations = allSyncOps.filter(op => op.status === 'failed').length;
    
    // Get last sync time from metadata
    const metaTransaction = this.db!.transaction([STORES.META_DATA], 'readonly');
    const metaStore = metaTransaction.objectStore(STORES.META_DATA);
    const lastSyncItem = await new Promise<StorageItem | null>((resolve) => {
      const request = metaStore.get('last_sync');
      request.onsuccess = () => resolve(request.result || null);
    });
    
    if (lastSyncItem) {
      lastSync = lastSyncItem.data;
    }

    // Estimate total size (rough calculation)
    totalSize = totalItems * 1024; // Rough estimate: 1KB per item

    return {
      totalItems,
      totalSize,
      lastSync,
      pendingOperations,
      failedOperations
    };
  }

  private async clearIndexedDB(): Promise<void> {
    for (const storeName of Object.values(STORES)) {
      const transaction = this.db!.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      await new Promise<void>((resolve, reject) => {
        const request = store.clear();
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });
    }
  }

  // Private methods for localStorage operations
  private storeInLocalStorage<T>(key: string, item: StorageItem<T>): void {
    try {
      localStorage.setItem(key, JSON.stringify(item));
    } catch (error) {
      console.warn('Failed to store in localStorage:', error);
      // Try to free up space by clearing expired items
      this.clearExpiredFromLocalStorage(Date.now());
      try {
        localStorage.setItem(key, JSON.stringify(item));
      } catch (retryError) {
        console.error('Failed to store after cleanup:', retryError);
      }
    }
  }

  private getFromLocalStorage<T>(key: string): StorageItem<T> | null {
    try {
      const item = localStorage.getItem(key);
      return item ? JSON.parse(item) : null;
    } catch (error) {
      console.warn('Failed to retrieve from localStorage:', error);
      return null;
    }
  }

  private getRecordsFromLocalStorage(classSessionId: number): AttendanceRecord[] {
    const records: AttendanceRecord[] = [];
    const prefix = `${STORES.ATTENDANCE_RECORDS}_attendance_`;
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(prefix)) {
        const item = this.getFromLocalStorage<AttendanceRecord>(key);
        if (item && item.data.class_session_id === classSessionId) {
          const record = this.validateAndExtractData(item);
          if (record) {
            records.push(record);
          }
        }
      }
    }
    
    return records;
  }

  private getSyncOpsFromLocalStorage(): SyncOperation[] {
    const operations: SyncOperation[] = [];
    const prefix = `${STORES.SYNC_QUEUE}_`;
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(prefix)) {
        const item = this.getFromLocalStorage<SyncOperation>(key);
        if (item && item.data.status === 'pending') {
          operations.push(item.data);
        }
      }
    }
    
    // Sort by priority (higher first) then timestamp (older first)
    operations.sort((a, b) => b.priority - a.priority || a.timestamp - b.timestamp);
    
    return operations;
  }

  private clearExpiredFromLocalStorage(now: number): void {
    const keysToRemove: string[] = [];
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key.includes(STORES.ATTENDANCE_RECORDS) || key.includes(STORES.CLASS_STATUS))) {
        const item = this.getFromLocalStorage(key);
        if (item && item.expires && item.expires < now) {
          keysToRemove.push(key);
        }
      }
    }
    
    keysToRemove.forEach(key => localStorage.removeItem(key));
  }

  private getLocalStorageStats(): CacheStats {
    let totalItems = 0;
    let totalSize = 0;
    let pendingOperations = 0;
    let failedOperations = 0;
    let lastSync = 0;

    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)!;
      const item = localStorage.getItem(key);
      
      if (item && (key.includes(STORES.ATTENDANCE_RECORDS) || key.includes(STORES.CLASS_STATUS))) {
        totalItems++;
        totalSize += item.length;
      }
      
      if (key.includes(STORES.SYNC_QUEUE)) {
        const syncItem = this.getFromLocalStorage<SyncOperation>(key);
        if (syncItem) {
          if (syncItem.data.status === 'pending') pendingOperations++;
          if (syncItem.data.status === 'failed') failedOperations++;
        }
      }
      
      if (key === `${STORES.META_DATA}_last_sync`) {
        const syncItem = this.getFromLocalStorage(key);
        if (syncItem) {
          lastSync = syncItem.data;
        }
      }
    }

    return {
      totalItems,
      totalSize,
      lastSync,
      pendingOperations,
      failedOperations
    };
  }

  private clearLocalStorageCache(): void {
    const keysToRemove: string[] = [];
    
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && Object.values(STORES).some(store => key.includes(store))) {
        keysToRemove.push(key);
      }
    }
    
    keysToRemove.forEach(key => localStorage.removeItem(key));
  }

  private validateAndExtractData<T>(item: StorageItem<T> | null): T | null {
    if (!item) return null;
    
    // Check if item is expired
    if (item.expires && item.expires < Date.now()) {
      return null;
    }
    
    return item.data;
  }
}

// Singleton instance
export const offlineStorage = new OfflineStorageService();