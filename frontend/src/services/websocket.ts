/**
 * Enhanced WebSocket client service for real-time communication with v2 infrastructure.
 * 
 * Features:
 * - Connection to new v2 WebSocket endpoint (/ws/v2/{connection_id})
 * - JWT authentication integration
 * - Automatic reconnection with exponential backoff
 * - Event-driven architecture for real-time updates
 * - Connection status monitoring and health checks
 * - Type-safe message handling
 */

import { v4 as uuidv4 } from 'uuid';

// WebSocket connection states
export enum ConnectionState {
  DISCONNECTED = 'disconnected',
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  AUTHENTICATING = 'authenticating',
  AUTHENTICATED = 'authenticated',
  ERROR = 'error'
}

// Message types from backend (aligned with Stream A)
export enum MessageType {
  // Connection management
  CONNECT = 'connect',
  DISCONNECT = 'disconnect',
  PING = 'ping',
  PONG = 'pong',
  
  // Authentication
  AUTH = 'auth',
  AUTH_SUCCESS = 'auth_success',
  AUTH_FAILED = 'auth_failed',
  
  // Real-time events
  STUDENT_JOINED = 'student_joined',
  STUDENT_LEFT = 'student_left',
  ATTENDANCE_UPDATE = 'attendance_update',
  SESSION_UPDATE = 'session_update',
  SESSION_ENDED = 'session_ended',
  STATS_UPDATE = 'stats_update',
  
  // System events
  ERROR = 'error',
  SYSTEM_NOTIFICATION = 'system_notification'
}

// WebSocket message interface
export interface WebSocketMessage {
  type: MessageType;
  timestamp: string;
  data: any;
}

// Event data interfaces
export interface StudentJoinedData {
  student_id: number;
  student_name: string;
  session_id: string;
  joined_at: string;
  join_method: 'qr' | 'code' | 'link';
  location?: string;
  device_info?: string;
}

export interface AttendanceUpdateData {
  session_id: string;
  student_id: number;
  status: 'present' | 'late' | 'absent' | 'excused';
  timestamp: string;
  updated_by: string;
}

export interface SessionUpdateData {
  session_id: string;
  updates: any;
  timestamp: string;
}

export interface StatsUpdateData {
  class_id: string;
  session_id: string;
  total_students: number;
  present_count: number;
  late_count: number;
  absent_count: number;
  attendance_rate: number;
  recent_joins: Array<{
    student_name: string;
    joined_at: string;
    join_method: string;
  }>;
  time_remaining_minutes?: number;
  updated_at: string;
}

export interface SystemNotificationData {
  message: string;
  type: 'info' | 'warning' | 'error' | 'success';
  timestamp: string;
  data?: any;
}

// Connection configuration
export interface WebSocketConfig {
  classId: string;
  token: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  heartbeatInterval?: number;
  apiBaseUrl?: string;
}

// Event listener types
export type MessageHandler = (message: WebSocketMessage) => void;
export type EventHandler<T = any> = (data: T) => void;
export type StateChangeHandler = (state: ConnectionState, error?: string) => void;

/**
 * Enhanced WebSocket client for real-time communication with v2 infrastructure
 */
export class RealtimeWebSocketClient {
  private websocket: WebSocket | null = null;
  private connectionId: string;
  private state: ConnectionState = ConnectionState.DISCONNECTED;
  private config: Required<WebSocketConfig>;
  
  // Event listeners
  private messageHandlers = new Set<MessageHandler>();
  private eventHandlers = new Map<MessageType, Set<EventHandler>>();
  private stateChangeHandlers = new Set<StateChangeHandler>();
  
  // Connection management
  private reconnectAttempts = 0;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private heartbeatInterval: NodeJS.Timeout | null = null;
  private lastPingTime: number = 0;
  private connectionStartTime: number = 0;
  
  // Statistics
  private stats = {
    messagesReceived: 0,
    messagesSent: 0,
    reconnectionCount: 0,
    totalConnections: 0,
    averageLatency: 0,
    errorCount: 0
  };

  constructor(config: WebSocketConfig) {
    this.connectionId = uuidv4();
    this.config = {
      reconnectInterval: 3000,
      maxReconnectAttempts: 10,
      heartbeatInterval: 30000,
      apiBaseUrl: import.meta.env.VITE_API_URL || 'http://localhost:8000',
      ...config
    };
  }

  /**
   * Connect to the WebSocket server using v2 endpoint
   */
  async connect(): Promise<void> {
    if (this.state !== ConnectionState.DISCONNECTED && this.state !== ConnectionState.ERROR) {
      return;
    }

    this.setState(ConnectionState.CONNECTING);
    this.connectionStartTime = Date.now();

    try {
      // Build WebSocket URL for v2 endpoint: /ws/v2/{connection_id}
      const wsUrl = this.buildWebSocketUrl();
      
      // Create WebSocket connection
      this.websocket = new WebSocket(wsUrl);
      
      // Set up event handlers
      this.websocket.onopen = this.handleOpen.bind(this);
      this.websocket.onmessage = this.handleMessage.bind(this);
      this.websocket.onclose = this.handleClose.bind(this);
      this.websocket.onerror = this.handleError.bind(this);
      
    } catch (error) {
      this.handleConnectionError(error);
    }
  }

  /**
   * Disconnect from the WebSocket server
   */
  disconnect(): void {
    this.clearReconnectTimeout();
    this.clearHeartbeat();
    
    if (this.websocket) {
      this.websocket.close(1000, 'Manual disconnect');
      this.websocket = null;
    }
    
    this.setState(ConnectionState.DISCONNECTED);
  }

  /**
   * Send a message to the server
   */
  async sendMessage(type: MessageType, data: any = {}): Promise<void> {
    if (!this.websocket || this.websocket.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not connected');
    }

    const message: WebSocketMessage = {
      type,
      timestamp: new Date().toISOString(),
      data
    };

    try {
      this.websocket.send(JSON.stringify(message));
      this.stats.messagesSent++;
    } catch (error) {
      this.stats.errorCount++;
      throw error;
    }
  }

  /**
   * Add a general message handler
   */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  /**
   * Add an event-specific handler
   */
  onEvent<T = any>(eventType: MessageType, handler: EventHandler<T>): () => void {
    if (!this.eventHandlers.has(eventType)) {
      this.eventHandlers.set(eventType, new Set());
    }
    this.eventHandlers.get(eventType)!.add(handler);
    
    return () => {
      const handlers = this.eventHandlers.get(eventType);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.eventHandlers.delete(eventType);
        }
      }
    };
  }

  /**
   * Add a state change handler
   */
  onStateChange(handler: StateChangeHandler): () => void {
    this.stateChangeHandlers.add(handler);
    return () => this.stateChangeHandlers.delete(handler);
  }

  /**
   * Get current connection state
   */
  getState(): ConnectionState {
    return this.state;
  }

  /**
   * Get connection statistics
   */
  getStats() {
    return {
      ...this.stats,
      state: this.state,
      connectionId: this.connectionId,
      uptime: this.connectionStartTime ? Date.now() - this.connectionStartTime : 0,
      isConnected: this.state === ConnectionState.AUTHENTICATED
    };
  }

  /**
   * Force reconnection
   */
  async reconnect(): Promise<void> {
    this.disconnect();
    await new Promise(resolve => setTimeout(resolve, 1000));
    await this.connect();
  }

  /**
   * Build WebSocket URL for v2 endpoint
   */
  private buildWebSocketUrl(): string {
    const baseUrl = this.config.apiBaseUrl;
    const wsBaseUrl = baseUrl.replace(/^https?:\/\//, '').replace(/^http/, 'ws').replace(/^https/, 'wss');
    return `ws://${wsBaseUrl}/ws/v2/${this.connectionId}`;
  }

  /**
   * Handle WebSocket connection open
   */
  private handleOpen(event: Event): void {
    console.log(`WebSocket connected with connection ID: ${this.connectionId}`);
    this.setState(ConnectionState.CONNECTED);
    this.stats.totalConnections++;
    
    // Start authentication process
    this.authenticate();
  }

  /**
   * Handle WebSocket message
   */
  private handleMessage(event: MessageEvent): void {
    try {
      const message: WebSocketMessage = JSON.parse(event.data);
      this.stats.messagesReceived++;
      
      // Update activity
      if (message.type === MessageType.PING) {
        this.lastPingTime = Date.now();
      }
      
      // Notify message handlers
      this.messageHandlers.forEach(handler => {
        try {
          handler(message);
        } catch (error) {
          console.error('Error in message handler:', error);
        }
      });
      
      // Notify event-specific handlers
      const handlers = this.eventHandlers.get(message.type);
      if (handlers) {
        handlers.forEach(handler => {
          try {
            handler(message.data);
          } catch (error) {
            console.error('Error in event handler:', error);
          }
        });
      }
      
      // Handle built-in message types
      this.handleBuiltInMessage(message);
      
    } catch (error) {
      console.error('Failed to parse WebSocket message:', error);
      this.stats.errorCount++;
    }
  }

  /**
   * Handle WebSocket connection close
   */
  private handleClose(event: CloseEvent): void {
    console.log(`WebSocket disconnected: ${event.code} - ${event.reason}`);
    
    if (event.code === 1000) {
      // Clean disconnect
      this.setState(ConnectionState.DISCONNECTED);
    } else {
      // Unexpected disconnect
      this.setState(ConnectionState.ERROR, `Connection lost: ${event.reason}`);
      this.attemptReconnect();
    }
    
    this.clearHeartbeat();
  }

  /**
   * Handle WebSocket error
   */
  private handleError(event: Event): void {
    console.error('WebSocket error:', event);
    this.setState(ConnectionState.ERROR, 'WebSocket error occurred');
    this.stats.errorCount++;
  }

  /**
   * Handle connection errors
   */
  private handleConnectionError(error: any): void {
    console.error('Connection error:', error);
    this.setState(ConnectionState.ERROR, error.message || 'Connection failed');
    this.stats.errorCount++;
    this.attemptReconnect();
  }

  /**
   * Set connection state and notify handlers
   */
  private setState(newState: ConnectionState, error?: string): void {
    if (this.state !== newState) {
      this.state = newState;
      this.stateChangeHandlers.forEach(handler => {
        try {
          handler(newState, error);
        } catch (err) {
          console.error('Error in state change handler:', err);
        }
      });
    }
  }

  /**
   * Authenticate the connection
   */
  private async authenticate(): Promise<void> {
    this.setState(ConnectionState.AUTHENTICATING);
    
    try {
      await this.sendMessage(MessageType.AUTH, {
        token: this.config.token,
        class_id: this.config.classId
      });
    } catch (error) {
      console.error('Authentication failed:', error);
      this.setState(ConnectionState.ERROR, 'Authentication failed');
    }
  }

  /**
   * Handle built-in message types
   */
  private handleBuiltInMessage(message: WebSocketMessage): void {
    switch (message.type) {
      case MessageType.CONNECT:
        console.log('Connection confirmed:', message.data);
        break;
        
      case MessageType.AUTH_SUCCESS:
        console.log('Authentication successful:', message.data);
        this.setState(ConnectionState.AUTHENTICATED);
        this.startHeartbeat();
        break;
        
      case MessageType.AUTH_FAILED:
        console.error('Authentication failed:', message.data);
        this.setState(ConnectionState.ERROR, message.data?.error || 'Authentication failed');
        break;
        
      case MessageType.PONG:
        // Calculate latency
        if (this.lastPingTime > 0) {
          const latency = Date.now() - this.lastPingTime;
          this.stats.averageLatency = (this.stats.averageLatency + latency) / 2;
        }
        break;
        
      case MessageType.ERROR:
        console.error('Server error:', message.data);
        this.setState(ConnectionState.ERROR, message.data?.error || 'Server error');
        break;
        
      default:
        // Other message types are handled by specific event handlers
        break;
    }
  }

  /**
   * Attempt to reconnect with exponential backoff
   */
  private attemptReconnect(): void {
    if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached');
      this.setState(ConnectionState.ERROR, 'Connection lost and could not be restored');
      return;
    }

    this.clearReconnectTimeout();
    
    const delay = this.config.reconnectInterval * Math.pow(2, this.reconnectAttempts);
    console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts + 1}/${this.config.maxReconnectAttempts})`);

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempts++;
      this.stats.reconnectionCount++;
      this.connect();
    }, delay);
  }

  /**
   * Clear reconnection timeout
   */
  private clearReconnectTimeout(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
  }

  /**
   * Start heartbeat ping
   */
  private startHeartbeat(): void {
    this.clearHeartbeat();
    
    this.heartbeatInterval = setInterval(() => {
      if (this.state === ConnectionState.AUTHENTICATED) {
        this.lastPingTime = Date.now();
        this.sendMessage(MessageType.PING, { timestamp: this.lastPingTime });
      }
    }, this.config.heartbeatInterval);
  }

  /**
   * Clear heartbeat interval
   */
  private clearHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
}

// Legacy compatibility class for existing code
export class AttendanceWebSocketService {
  private client: RealtimeWebSocketClient | null = null;
  
  async connect(classId: string, token: string, callbacks: any): Promise<boolean> {
    try {
      this.client = new RealtimeWebSocketClient({ classId, token });
      
      // Set up legacy callback handlers
      if (callbacks.onAttendanceUpdate) {
        this.client.onEvent(MessageType.ATTENDANCE_UPDATE, callbacks.onAttendanceUpdate);
      }
      if (callbacks.onStatsUpdate) {
        this.client.onEvent(MessageType.STATS_UPDATE, callbacks.onStatsUpdate);
      }
      if (callbacks.onConnection) {
        this.client.onStateChange((state) => {
          callbacks.onConnection(state === ConnectionState.AUTHENTICATED);
        });
      }
      if (callbacks.onError) {
        this.client.onStateChange((state, error) => {
          if (state === ConnectionState.ERROR && error) {
            callbacks.onError(error);
          }
        });
      }
      
      await this.client.connect();
      return true;
    } catch (error) {
      console.error('Failed to connect:', error);
      return false;
    }
  }
  
  disconnect(): void {
    if (this.client) {
      this.client.disconnect();
      this.client = null;
    }
  }
  
  isConnected(): boolean {
    return this.client?.getState() === ConnectionState.AUTHENTICATED;
  }
  
  ping(): boolean {
    if (this.client && this.client.getState() === ConnectionState.AUTHENTICATED) {
      try {
        this.client.sendMessage(MessageType.PING, {});
        return true;
      } catch (error) {
        return false;
      }
    }
    return false;
  }
}

// Singleton instance for global use
export const attendanceWebSocket = new AttendanceWebSocketService();

export default attendanceWebSocket;