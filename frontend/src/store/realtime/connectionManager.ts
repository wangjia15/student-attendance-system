/**
 * Real-time connection manager that integrates the WebSocket service with the store.
 * 
 * This manager:
 * - Manages connections across different class sessions
 * - Synchronizes WebSocket events with the store
 * - Provides centralized connection management
 * - Handles connection lifecycle and cleanup
 */

import { useRealtimeStore } from './index';
import { 
  RealtimeWebSocketClient,
  ConnectionState,
  MessageType,
  WebSocketConfig,
  StudentJoinedData,
  AttendanceUpdateData,
  SessionUpdateData,
  StatsUpdateData,
  SystemNotificationData
} from '../../services/websocket';

class RealtimeConnectionManager {
  private connections = new Map<string, RealtimeWebSocketClient>();
  private store = useRealtimeStore.getState();
  
  constructor() {
    // Subscribe to store updates
    useRealtimeStore.subscribe(
      (state) => state,
      (state) => {
        this.store = state;
      }
    );
  }
  
  /**
   * Connect to a class session
   */
  async connectToClass(classId: string, token: string, config?: Partial<WebSocketConfig>): Promise<boolean> {
    try {
      // Check if already connected
      if (this.connections.has(classId)) {
        console.log(`Already connected to class ${classId}`);
        return true;
      }
      
      const wsConfig: WebSocketConfig = {
        classId,
        token,
        reconnectInterval: 3000,
        maxReconnectAttempts: 10,
        heartbeatInterval: 30000,
        ...config,
      };
      
      const client = new RealtimeWebSocketClient(wsConfig);
      
      // Set up event handlers
      this.setupClientEventHandlers(client, classId);
      
      // Connect
      await client.connect();
      
      // Store the connection
      this.connections.set(classId, client);
      
      // Update store
      this.store.addActiveConnection(classId, token);
      
      console.log(`Connected to real-time updates for class ${classId}`);
      return true;
      
    } catch (error) {
      console.error(`Failed to connect to class ${classId}:`, error);
      this.store.setConnectionState(ConnectionState.ERROR, error.message);
      return false;
    }
  }
  
  /**
   * Disconnect from a class session
   */
  disconnectFromClass(classId: string): void {
    const client = this.connections.get(classId);
    if (client) {
      client.disconnect();
      this.connections.delete(classId);
      this.store.removeActiveConnection(classId);
      console.log(`Disconnected from class ${classId}`);
    }
  }
  
  /**
   * Disconnect from all sessions
   */
  disconnectAll(): void {
    for (const [classId, client] of this.connections) {
      client.disconnect();
      this.store.removeActiveConnection(classId);
    }
    this.connections.clear();
    console.log('Disconnected from all real-time sessions');
  }
  
  /**
   * Get connection status for a class
   */
  getConnectionStatus(classId: string): ConnectionState {
    const client = this.connections.get(classId);
    return client?.getState() || ConnectionState.DISCONNECTED;
  }
  
  /**
   * Check if connected to a class
   */
  isConnectedToClass(classId: string): boolean {
    const client = this.connections.get(classId);
    return client?.getState() === ConnectionState.AUTHENTICATED;
  }
  
  /**
   * Get all active connections
   */
  getActiveConnections(): string[] {
    return Array.from(this.connections.keys());
  }
  
  /**
   * Send a message to a specific class
   */
  async sendMessage(classId: string, type: MessageType, data?: any): Promise<void> {
    const client = this.connections.get(classId);
    if (client) {
      await client.sendMessage(type, data);
    } else {
      throw new Error(`Not connected to class ${classId}`);
    }
  }
  
  /**
   * Reconnect to a class
   */
  async reconnectToClass(classId: string): Promise<boolean> {
    const client = this.connections.get(classId);
    if (client) {
      try {
        await client.reconnect();
        return true;
      } catch (error) {
        console.error(`Failed to reconnect to class ${classId}:`, error);
        return false;
      }
    }
    return false;
  }
  
  /**
   * Set up event handlers for a WebSocket client
   */
  private setupClientEventHandlers(client: RealtimeWebSocketClient, classId: string): void {
    // Connection state changes
    client.onStateChange((state, error) => {
      this.store.setConnectionState(state, error);
      
      // Update connection stats periodically when connected
      if (state === ConnectionState.AUTHENTICATED) {
        const updateStats = () => {
          if (client.getState() === ConnectionState.AUTHENTICATED) {
            this.store.updateConnectionStats(client.getStats());
            setTimeout(updateStats, 5000); // Update every 5 seconds
          }
        };
        updateStats();
      }
    });
    
    // Student joined events
    client.onEvent(MessageType.STUDENT_JOINED, (data: StudentJoinedData) => {
      console.log('Student joined:', data);
      this.store.addStudentJoin(data);
      
      // Play notification sound if enabled
      if (this.store.ui.soundEnabled) {
        this.playNotificationSound('student_join');
      }
    });
    
    // Attendance update events
    client.onEvent(MessageType.ATTENDANCE_UPDATE, (data: AttendanceUpdateData) => {
      console.log('Attendance updated:', data);
      this.store.addAttendanceUpdate(data);
      
      // Play notification sound if enabled
      if (this.store.ui.soundEnabled) {
        this.playNotificationSound('attendance_update');
      }
    });
    
    // Session update events
    client.onEvent(MessageType.SESSION_UPDATE, (data: SessionUpdateData) => {
      console.log('Session updated:', data);
      this.store.addSessionUpdate(data);
    });
    
    // Statistics update events
    client.onEvent(MessageType.STATS_UPDATE, (data: StatsUpdateData) => {
      console.log('Stats updated:', data);
      this.store.updateLiveStats(classId, data);
    });
    
    // System notification events
    client.onEvent(MessageType.SYSTEM_NOTIFICATION, (data: SystemNotificationData) => {
      console.log('System notification:', data);
      this.store.addSystemNotification(data);
      
      // Play notification sound if enabled and it's an important notification
      if (this.store.ui.soundEnabled && data.type === 'error') {
        this.playNotificationSound('error');
      }
    });
    
    // Error handling
    client.onEvent(MessageType.ERROR, (data: any) => {
      console.error('WebSocket error:', data);
      this.store.setConnectionState(ConnectionState.ERROR, data.error || 'Unknown error');
    });
  }
  
  /**
   * Play notification sounds
   */
  private playNotificationSound(type: 'student_join' | 'attendance_update' | 'error'): void {
    if (typeof window !== 'undefined' && 'AudioContext' in window) {
      try {
        // Create different tones for different events
        const audioContext = new AudioContext();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        
        // Different frequencies for different event types
        switch (type) {
          case 'student_join':
            oscillator.frequency.value = 800; // High pleasant tone
            break;
          case 'attendance_update':
            oscillator.frequency.value = 600; // Medium tone
            break;
          case 'error':
            oscillator.frequency.value = 300; // Low warning tone
            break;
        }
        
        oscillator.type = 'sine';
        gainNode.gain.setValueAtTime(0.1, audioContext.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);
        
        oscillator.start(audioContext.currentTime);
        oscillator.stop(audioContext.currentTime + 0.5);
        
      } catch (error) {
        console.warn('Failed to play notification sound:', error);
      }
    }
  }
  
  /**
   * Get connection statistics for all connections
   */
  getAllConnectionStats(): Record<string, any> {
    const stats: Record<string, any> = {};
    
    for (const [classId, client] of this.connections) {
      stats[classId] = {
        ...client.getStats(),
        state: client.getState(),
      };
    }
    
    return stats;
  }
  
  /**
   * Health check for all connections
   */
  async healthCheck(): Promise<Record<string, boolean>> {
    const health: Record<string, boolean> = {};
    
    for (const [classId, client] of this.connections) {
      try {
        // Try to send a ping
        if (client.getState() === ConnectionState.AUTHENTICATED) {
          await client.sendMessage(MessageType.PING, { timestamp: Date.now() });
          health[classId] = true;
        } else {
          health[classId] = false;
        }
      } catch (error) {
        health[classId] = false;
      }
    }
    
    return health;
  }
  
  /**
   * Clean up resources
   */
  destroy(): void {
    this.disconnectAll();
    this.connections.clear();
  }
}

// Global singleton instance
export const realtimeConnectionManager = new RealtimeConnectionManager();

// Auto-cleanup on page unload
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', () => {
    realtimeConnectionManager.destroy();
  });
}

export default realtimeConnectionManager;