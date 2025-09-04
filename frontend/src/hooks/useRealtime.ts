/**
 * React hook for managing real-time WebSocket connections.
 * 
 * Features:
 * - Automatic connection management with lifecycle
 * - Type-safe event handling
 * - Connection state monitoring
 * - Automatic cleanup on unmount
 * - Integration with authentication
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { 
  RealtimeWebSocketClient, 
  ConnectionState, 
  MessageType, 
  WebSocketConfig,
  EventHandler,
  StudentJoinedData,
  AttendanceUpdateData,
  SessionUpdateData,
  StatsUpdateData,
  SystemNotificationData
} from '../services/websocket';

export interface UseRealtimeConfig {
  classId: string;
  token: string;
  autoConnect?: boolean;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  heartbeatInterval?: number;
}

export interface UseRealtimeHandlers {
  onStudentJoined?: EventHandler<StudentJoinedData>;
  onAttendanceUpdate?: EventHandler<AttendanceUpdateData>;
  onSessionUpdate?: EventHandler<SessionUpdateData>;
  onStatsUpdate?: EventHandler<StatsUpdateData>;
  onSystemNotification?: EventHandler<SystemNotificationData>;
  onConnectionChange?: (isConnected: boolean, state: ConnectionState) => void;
  onError?: (error: string) => void;
}

export interface UseRealtimeReturn {
  // Connection state
  isConnected: boolean;
  connectionState: ConnectionState;
  connectionStats: any;
  
  // Connection control
  connect: () => Promise<void>;
  disconnect: () => void;
  reconnect: () => Promise<void>;
  
  // Message sending
  sendMessage: (type: MessageType, data?: any) => Promise<void>;
  
  // Event subscription
  onStudentJoined: (handler: EventHandler<StudentJoinedData>) => () => void;
  onAttendanceUpdate: (handler: EventHandler<AttendanceUpdateData>) => () => void;
  onSessionUpdate: (handler: EventHandler<SessionUpdateData>) => () => void;
  onStatsUpdate: (handler: EventHandler<StatsUpdateData>) => () => void;
  onSystemNotification: (handler: EventHandler<SystemNotificationData>) => () => void;
}

/**
 * Hook for managing real-time WebSocket connections
 */
export function useRealtime(
  config: UseRealtimeConfig,
  handlers: UseRealtimeHandlers = {}
): UseRealtimeReturn {
  const [connectionState, setConnectionState] = useState<ConnectionState>(ConnectionState.DISCONNECTED);
  const [connectionStats, setConnectionStats] = useState<any>({});
  
  // Use ref to store the client to persist across re-renders
  const clientRef = useRef<RealtimeWebSocketClient | null>(null);
  const handlersRef = useRef(handlers);
  
  // Update handlers ref when handlers change
  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);
  
  // Derived state
  const isConnected = connectionState === ConnectionState.AUTHENTICATED;
  
  // Initialize WebSocket client
  const initializeClient = useCallback(() => {
    if (clientRef.current) {
      return clientRef.current;
    }
    
    const wsConfig: WebSocketConfig = {
      classId: config.classId,
      token: config.token,
      reconnectInterval: config.reconnectInterval,
      maxReconnectAttempts: config.maxReconnectAttempts,
      heartbeatInterval: config.heartbeatInterval,
    };
    
    const client = new RealtimeWebSocketClient(wsConfig);
    
    // Set up state change handler
    client.onStateChange((state, error) => {
      setConnectionState(state);
      setConnectionStats(client.getStats());
      
      const isConnected = state === ConnectionState.AUTHENTICATED;
      handlersRef.current.onConnectionChange?.(isConnected, state);
      
      if (state === ConnectionState.ERROR && error) {
        handlersRef.current.onError?.(error);
      }
    });
    
    // Set up event handlers
    client.onEvent(MessageType.STUDENT_JOINED, (data: StudentJoinedData) => {
      handlersRef.current.onStudentJoined?.(data);
    });
    
    client.onEvent(MessageType.ATTENDANCE_UPDATE, (data: AttendanceUpdateData) => {
      handlersRef.current.onAttendanceUpdate?.(data);
    });
    
    client.onEvent(MessageType.SESSION_UPDATE, (data: SessionUpdateData) => {
      handlersRef.current.onSessionUpdate?.(data);
    });
    
    client.onEvent(MessageType.STATS_UPDATE, (data: StatsUpdateData) => {
      handlersRef.current.onStatsUpdate?.(data);
    });
    
    client.onEvent(MessageType.SYSTEM_NOTIFICATION, (data: SystemNotificationData) => {
      handlersRef.current.onSystemNotification?.(data);
    });
    
    // Periodically update stats
    const statsInterval = setInterval(() => {
      setConnectionStats(client.getStats());
    }, 5000);
    
    // Clean up stats interval when client is destroyed
    const originalDisconnect = client.disconnect.bind(client);
    client.disconnect = () => {
      clearInterval(statsInterval);
      originalDisconnect();
    };
    
    clientRef.current = client;
    return client;
  }, [config.classId, config.token, config.reconnectInterval, config.maxReconnectAttempts, config.heartbeatInterval]);
  
  // Connection control functions
  const connect = useCallback(async () => {
    const client = initializeClient();
    await client.connect();
  }, [initializeClient]);
  
  const disconnect = useCallback(() => {
    if (clientRef.current) {
      clientRef.current.disconnect();
    }
  }, []);
  
  const reconnect = useCallback(async () => {
    if (clientRef.current) {
      await clientRef.current.reconnect();
    }
  }, []);
  
  // Message sending
  const sendMessage = useCallback(async (type: MessageType, data?: any) => {
    if (clientRef.current) {
      await clientRef.current.sendMessage(type, data);
    } else {
      throw new Error('WebSocket client not initialized');
    }
  }, []);
  
  // Event subscription functions
  const onStudentJoined = useCallback((handler: EventHandler<StudentJoinedData>) => {
    const client = initializeClient();
    return client.onEvent(MessageType.STUDENT_JOINED, handler);
  }, [initializeClient]);
  
  const onAttendanceUpdate = useCallback((handler: EventHandler<AttendanceUpdateData>) => {
    const client = initializeClient();
    return client.onEvent(MessageType.ATTENDANCE_UPDATE, handler);
  }, [initializeClient]);
  
  const onSessionUpdate = useCallback((handler: EventHandler<SessionUpdateData>) => {
    const client = initializeClient();
    return client.onEvent(MessageType.SESSION_UPDATE, handler);
  }, [initializeClient]);
  
  const onStatsUpdate = useCallback((handler: EventHandler<StatsUpdateData>) => {
    const client = initializeClient();
    return client.onEvent(MessageType.STATS_UPDATE, handler);
  }, [initializeClient]);
  
  const onSystemNotification = useCallback((handler: EventHandler<SystemNotificationData>) => {
    const client = initializeClient();
    return client.onEvent(MessageType.SYSTEM_NOTIFICATION, handler);
  }, [initializeClient]);
  
  // Auto-connect effect
  useEffect(() => {
    if (config.autoConnect !== false) {
      connect();
    }
    
    // Cleanup on unmount
    return () => {
      if (clientRef.current) {
        clientRef.current.disconnect();
        clientRef.current = null;
      }
    };
  }, [config.autoConnect, connect]);
  
  // Handle config changes
  useEffect(() => {
    if (clientRef.current) {
      // If critical config changed, need to recreate client
      const stats = clientRef.current.getStats();
      if (stats.connectionId) {
        // Disconnect current client and reconnect with new config
        disconnect();
        setTimeout(() => {
          connect();
        }, 1000);
      }
    }
  }, [config.classId, config.token, connect, disconnect]);
  
  return {
    // Connection state
    isConnected,
    connectionState,
    connectionStats,
    
    // Connection control
    connect,
    disconnect,
    reconnect,
    
    // Message sending
    sendMessage,
    
    // Event subscription
    onStudentJoined,
    onAttendanceUpdate,
    onSessionUpdate,
    onStatsUpdate,
    onSystemNotification,
  };
}

/**
 * Hook for simple real-time attendance monitoring (legacy compatibility)
 */
export function useAttendanceRealtime(classId: string, token: string) {
  const [studentJoins, setStudentJoins] = useState<StudentJoinedData[]>([]);
  const [attendanceUpdates, setAttendanceUpdates] = useState<AttendanceUpdateData[]>([]);
  const [currentStats, setCurrentStats] = useState<StatsUpdateData | null>(null);
  const [notifications, setNotifications] = useState<SystemNotificationData[]>([]);
  
  const { isConnected, connectionState, connect, disconnect } = useRealtime(
    { classId, token },
    {
      onStudentJoined: (data) => {
        setStudentJoins(prev => [data, ...prev.slice(0, 49)]); // Keep last 50
      },
      onAttendanceUpdate: (data) => {
        setAttendanceUpdates(prev => [data, ...prev.slice(0, 49)]); // Keep last 50
      },
      onStatsUpdate: (data) => {
        setCurrentStats(data);
      },
      onSystemNotification: (data) => {
        setNotifications(prev => [data, ...prev.slice(0, 19)]); // Keep last 20
      },
      onError: (error) => {
        console.error('Real-time connection error:', error);
      }
    }
  );
  
  return {
    isConnected,
    connectionState,
    connect,
    disconnect,
    
    // Real-time data
    studentJoins,
    attendanceUpdates,
    currentStats,
    notifications,
    
    // Data management
    clearStudentJoins: () => setStudentJoins([]),
    clearAttendanceUpdates: () => setAttendanceUpdates([]),
    clearNotifications: () => setNotifications([]),
  };
}

export default useRealtime;