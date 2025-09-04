// Enhanced WebSocket service for attendance updates with teacher dashboard support
import { AttendanceStatus } from '../types/api';

// WebSocket message types
export interface WSMessage {
  type: string;
  data?: any;
  timestamp: string;
}

export interface AttendanceUpdateData {
  type: string;
  class_session_id: number;
  student_id: number;
  student_name: string;
  old_status: AttendanceStatus | null;
  new_status: AttendanceStatus;
  updated_by: number;
  updated_by_name: string;
  reason?: string;
  is_override: boolean;
  late_minutes?: number;
  timestamp: string;
}

export interface ClassStatsData {
  class_session_id: number;
  total_enrolled: number;
  checked_in_count: number;
  present_count: number;
  late_count: number;
  absent_count: number;
  excused_count: number;
  attendance_rate: number;
  last_updated: string;
}

export interface BulkOperationData {
  type: string;
  class_session_id: number;
  operation: string;
  affected_students: number[];
  updated_by: number;
  updated_by_name: string;
  processed_count: number;
  failed_count: number;
  timestamp: string;
}

export interface AlertData {
  type: string;
  class_session_id: number;
  alert_type: string;
  severity: 'low' | 'medium' | 'high';
  student_id: number;
  student_name: string;
  message: string;
  data: Record<string, any>;
  timestamp: string;
}

export interface ConflictData {
  class_id: number;
  operation: string;
  conflicting_user: number;
  message: string;
}

// Callback types
export type AttendanceUpdateCallback = (data: AttendanceUpdateData) => void;
export type StatsUpdateCallback = (data: ClassStatsData) => void;
export type BulkOperationCallback = (data: BulkOperationData) => void;
export type AlertCallback = (data: AlertData) => void;
export type ConflictCallback = (data: ConflictData) => void;
export type ConnectionCallback = (connected: boolean) => void;
export type ErrorCallback = (error: string) => void;

export interface WebSocketCallbacks {
  onAttendanceUpdate?: AttendanceUpdateCallback;
  onStatsUpdate?: StatsUpdateCallback;
  onBulkOperation?: BulkOperationCallback;
  onAlert?: AlertCallback;
  onConflict?: ConflictCallback;
  onConnection?: ConnectionCallback;
  onError?: ErrorCallback;
}

export class AttendanceWebSocketService {
  private ws: WebSocket | null = null;
  private callbacks: WebSocketCallbacks = {};
  private classId: number | null = null;
  private token: string | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private heartbeatInterval: NodeJS.Timeout | null = null;
  private isConnecting = false;
  private isReconnecting = false;
  private activeOperations = new Set<string>();

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl || process.env.REACT_APP_WS_URL || 'ws://localhost:8000';
  }

  private baseUrl: string;

  /**
   * Connect to attendance WebSocket for a specific class
   */
  async connect(classId: number, token: string, callbacks: WebSocketCallbacks = {}): Promise<boolean> {
    if (this.isConnecting) {
      return false;
    }

    this.isConnecting = true;
    this.classId = classId;
    this.token = token;
    this.callbacks = callbacks;

    try {
      const wsUrl = `${this.baseUrl}/ws/attendance/${classId}?token=${encodeURIComponent(token)}`;
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = this.handleOpen.bind(this);
      this.ws.onmessage = this.handleMessage.bind(this);
      this.ws.onclose = this.handleClose.bind(this);
      this.ws.onerror = this.handleError.bind(this);

      return new Promise((resolve) => {
        const timeout = setTimeout(() => {
          resolve(false);
          this.isConnecting = false;
        }, 10000);

        const originalOnOpen = this.ws?.onopen;
        if (this.ws) {
          this.ws.onopen = (event) => {
            clearTimeout(timeout);
            resolve(true);
            this.isConnecting = false;
            if (originalOnOpen) {
              originalOnOpen.call(this.ws, event);
            }
          };
        }
      });
    } catch (error) {
      this.isConnecting = false;
      this.callbacks.onError?.(error instanceof Error ? error.message : 'Connection failed');
      return false;
    }
  }

  /**
   * Disconnect from WebSocket
   */
  disconnect(): void {
    this.clearHeartbeat();
    this.stopAllOperations();
    
    if (this.ws) {
      this.ws.close(1000, 'User disconnected');
      this.ws = null;
    }
    
    this.classId = null;
    this.token = null;
    this.reconnectAttempts = 0;
    this.isReconnecting = false;
    this.callbacks.onConnection?.(false);
  }

  /**
   * Check if WebSocket is connected
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Send a message to the WebSocket
   */
  private send(message: any): boolean {
    if (!this.isConnected()) {
      return false;
    }

    try {
      this.ws?.send(JSON.stringify(message));
      return true;
    } catch (error) {
      this.callbacks.onError?.(error instanceof Error ? error.message : 'Send failed');
      return false;
    }
  }

  /**
   * Request current class statistics
   */
  requestStats(): boolean {
    return this.send({
      type: 'request_stats',
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Start an operation with conflict detection
   */
  startOperation(operationType: string, operationId?: string): string {
    const id = operationId || `${operationType}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    this.activeOperations.add(id);
    
    this.send({
      type: 'start_operation',
      operation_type: operationType,
      operation_id: id,
      timestamp: new Date().toISOString()
    });

    return id;
  }

  /**
   * End an operation
   */
  endOperation(operationId: string): void {
    this.activeOperations.delete(operationId);
    
    this.send({
      type: 'end_operation',
      operation_id: operationId,
      timestamp: new Date().toISOString()
    });
  }

  /**
   * Stop all active operations
   */
  stopAllOperations(): void {
    this.activeOperations.forEach(operationId => {
      this.endOperation(operationId);
    });
  }

  /**
   * Get list of active operations
   */
  getActiveOperations(): string[] {
    return Array.from(this.activeOperations);
  }

  /**
   * Send ping to keep connection alive
   */
  ping(): boolean {
    return this.send({
      type: 'ping',
      timestamp: new Date().toISOString()
    });
  }

  private handleOpen(event: Event): void {
    console.log('Attendance WebSocket connected');
    this.reconnectAttempts = 0;
    this.isReconnecting = false;
    this.callbacks.onConnection?.(true);
    this.startHeartbeat();
  }

  private handleMessage(event: MessageEvent): void {
    try {
      const message: WSMessage = JSON.parse(event.data);
      this.processMessage(message);
    } catch (error) {
      console.error('Failed to parse WebSocket message:', error);
      this.callbacks.onError?.('Invalid message format');
    }
  }

  private handleClose(event: CloseEvent): void {
    console.log('Attendance WebSocket disconnected:', event.code, event.reason);
    this.clearHeartbeat();
    this.callbacks.onConnection?.(false);

    // Attempt to reconnect unless it was a clean disconnect
    if (event.code !== 1000 && !this.isReconnecting && this.reconnectAttempts < this.maxReconnectAttempts) {
      this.attemptReconnect();
    }
  }

  private handleError(event: Event): void {
    console.error('WebSocket error:', event);
    this.callbacks.onError?.('Connection error');
  }

  private processMessage(message: WSMessage): void {
    switch (message.type) {
      case 'teacher_connected':
      case 'student_connected':
        console.log('Connected to attendance updates:', message.data);
        break;

      case 'attendance_updated':
        if (message.data && this.callbacks.onAttendanceUpdate) {
          this.callbacks.onAttendanceUpdate(message.data);
        }
        break;

      case 'stats_updated':
        if (message.data && this.callbacks.onStatsUpdate) {
          this.callbacks.onStatsUpdate(message.data);
        }
        break;

      case 'bulk_operation_completed':
        if (message.data && this.callbacks.onBulkOperation) {
          this.callbacks.onBulkOperation(message.data);
        }
        break;

      case 'attendance_alert':
        if (message.data && this.callbacks.onAlert) {
          this.callbacks.onAlert(message.data);
        }
        break;

      case 'operation_conflict':
        if (message.data && this.callbacks.onConflict) {
          this.callbacks.onConflict(message.data);
        }
        break;

      case 'operation_blocked':
        console.warn('Operation blocked:', message.message);
        this.callbacks.onError?.(message.message || 'Operation blocked due to conflict');
        break;

      case 'operation_started':
        console.log('Operation started:', message.data?.operation_id);
        break;

      case 'pong':
        // Heartbeat response - connection is alive
        break;

      case 'error':
        console.error('WebSocket server error:', message.message);
        this.callbacks.onError?.(message.message || 'Server error');
        break;

      default:
        console.warn('Unknown WebSocket message type:', message.type);
    }
  }

  private async attemptReconnect(): Promise<void> {
    if (this.isReconnecting || !this.classId || !this.token) {
      return;
    }

    this.isReconnecting = true;
    this.reconnectAttempts++;

    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
    console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

    setTimeout(async () => {
      if (this.classId && this.token) {
        const success = await this.connect(this.classId, this.token, this.callbacks);
        
        if (!success) {
          this.isReconnecting = false;
          
          if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnection attempts reached');
            this.callbacks.onError?.('Connection lost and could not be restored');
          }
        }
      }
    }, delay);
  }

  private startHeartbeat(): void {
    this.clearHeartbeat();
    this.heartbeatInterval = setInterval(() => {
      if (!this.ping()) {
        this.clearHeartbeat();
      }
    }, 30000); // Ping every 30 seconds
  }

  private clearHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  /**
   * Update callback handlers
   */
  updateCallbacks(callbacks: WebSocketCallbacks): void {
    this.callbacks = { ...this.callbacks, ...callbacks };
  }

  /**
   * Get connection info
   */
  getConnectionInfo(): {
    connected: boolean;
    classId: number | null;
    reconnectAttempts: number;
    activeOperations: string[];
  } {
    return {
      connected: this.isConnected(),
      classId: this.classId,
      reconnectAttempts: this.reconnectAttempts,
      activeOperations: this.getActiveOperations()
    };
  }
}

// Singleton instance for global use
export const attendanceWebSocket = new AttendanceWebSocketService();

export default attendanceWebSocket;