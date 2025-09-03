import { useState, useEffect, useRef, useCallback } from 'react';
import { 
  WebSocketMessage, 
  StudentJoinedMessage, 
  SessionUpdatedMessage, 
  StatsUpdateMessage,
  SessionEndedMessage 
} from '../types/api';

export interface WebSocketConfig {
  url: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  heartbeatInterval?: number;
}

export interface WebSocketState {
  isConnected: boolean;
  isConnecting: boolean;
  error: string | null;
  lastMessage: WebSocketMessage | null;
  connectionAttempts: number;
}

export interface WebSocketActions {
  connect: () => void;
  disconnect: () => void;
  sendMessage: (message: any) => void;
  reconnect: () => void;
}

type MessageHandler = (message: WebSocketMessage) => void;

export const useWebSocket = (
  config: WebSocketConfig,
  onMessage?: MessageHandler
): [WebSocketState, WebSocketActions] => {
  const [state, setState] = useState<WebSocketState>({
    isConnected: false,
    isConnecting: false,
    error: null,
    lastMessage: null,
    connectionAttempts: 0
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const heartbeatIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const isManualDisconnectRef = useRef(false);

  const {
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
    heartbeatInterval = 30000
  } = config;

  // Clear timeouts helper
  const clearTimeouts = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }
  }, []);

  // Start heartbeat to keep connection alive
  const startHeartbeat = useCallback(() => {
    clearTimeouts();
    heartbeatIntervalRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, heartbeatInterval);
  }, [heartbeatInterval, clearTimeouts]);

  // Connect function
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || state.isConnecting) {
      return;
    }

    setState(prev => ({ 
      ...prev, 
      isConnecting: true, 
      error: null 
    }));

    try {
      const ws = new WebSocket(config.url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected:', config.url);
        setState(prev => ({
          ...prev,
          isConnected: true,
          isConnecting: false,
          error: null,
          connectionAttempts: 0
        }));
        startHeartbeat();
      };

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          
          setState(prev => ({
            ...prev,
            lastMessage: message
          }));

          // Handle pong responses
          if (message.type === 'pong') {
            console.log('WebSocket heartbeat received');
            return;
          }

          // Call external message handler
          if (onMessage) {
            onMessage(message);
          }
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
          setState(prev => ({
            ...prev,
            error: 'Failed to parse message from server'
          }));
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setState(prev => ({
          ...prev,
          error: 'WebSocket connection error',
          isConnecting: false
        }));
      };

      ws.onclose = (event) => {
        console.log('WebSocket closed:', event.code, event.reason);
        
        setState(prev => ({
          ...prev,
          isConnected: false,
          isConnecting: false
        }));

        clearTimeouts();

        // Auto-reconnect if not manually disconnected
        if (!isManualDisconnectRef.current && 
            state.connectionAttempts < maxReconnectAttempts) {
          
          setState(prev => ({
            ...prev,
            connectionAttempts: prev.connectionAttempts + 1
          }));

          console.log(`Attempting to reconnect (${state.connectionAttempts + 1}/${maxReconnectAttempts})...`);
          
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectInterval);
        } else if (state.connectionAttempts >= maxReconnectAttempts) {
          setState(prev => ({
            ...prev,
            error: `Failed to reconnect after ${maxReconnectAttempts} attempts`
          }));
        }
      };

    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      setState(prev => ({
        ...prev,
        isConnecting: false,
        error: 'Failed to create WebSocket connection'
      }));
    }
  }, [config.url, state.isConnecting, state.connectionAttempts, onMessage, 
      maxReconnectAttempts, reconnectInterval, startHeartbeat, clearTimeouts]);

  // Disconnect function
  const disconnect = useCallback(() => {
    isManualDisconnectRef.current = true;
    clearTimeouts();

    if (wsRef.current) {
      wsRef.current.close(1000, 'Manual disconnect');
      wsRef.current = null;
    }

    setState(prev => ({
      ...prev,
      isConnected: false,
      isConnecting: false,
      connectionAttempts: 0,
      error: null
    }));
  }, [clearTimeouts]);

  // Send message function
  const sendMessage = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify(message));
      } catch (error) {
        console.error('Failed to send WebSocket message:', error);
        setState(prev => ({
          ...prev,
          error: 'Failed to send message'
        }));
      }
    } else {
      console.warn('Cannot send message: WebSocket not connected');
      setState(prev => ({
        ...prev,
        error: 'Cannot send message: not connected'
      }));
    }
  }, []);

  // Manual reconnect function
  const reconnect = useCallback(() => {
    isManualDisconnectRef.current = false;
    setState(prev => ({
      ...prev,
      connectionAttempts: 0,
      error: null
    }));
    disconnect();
    setTimeout(() => connect(), 100);
  }, [connect, disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isManualDisconnectRef.current = true;
      clearTimeouts();
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmount');
      }
    };
  }, [clearTimeouts]);

  const actions: WebSocketActions = {
    connect,
    disconnect,
    sendMessage,
    reconnect
  };

  return [state, actions];
};

// Specialized hook for class session WebSocket
export const useClassSessionWebSocket = (
  classId: string,
  token: string,
  enabled: boolean = true
) => {
  const [messages, setMessages] = useState<WebSocketMessage[]>([]);
  const [studentJoins, setStudentJoins] = useState<StudentJoinedMessage[]>([]);
  const [sessionUpdates, setSessionUpdates] = useState<SessionUpdatedMessage[]>([]);
  const [stats, setStats] = useState<StatsUpdateMessage | null>(null);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    setMessages(prev => [...prev, message]);

    switch (message.type) {
      case 'student_joined':
        setStudentJoins(prev => [...prev, message as StudentJoinedMessage]);
        break;
      
      case 'session_updated':
        setSessionUpdates(prev => [...prev, message as SessionUpdatedMessage]);
        break;
      
      case 'stats_update':
        setStats(message as StatsUpdateMessage);
        break;
      
      case 'session_ended':
        console.log('Session ended:', (message as SessionEndedMessage).data);
        break;
      
      case 'connection_confirmed':
        console.log('Connection confirmed for class:', classId);
        break;
      
      default:
        console.log('Unknown message type:', message.type);
    }
  }, [classId]);

  const wsUrl = `ws://localhost:8000/api/v1/classes/${classId}/live-updates?token=${encodeURIComponent(token)}`;
  
  const [wsState, wsActions] = useWebSocket(
    { url: wsUrl },
    handleMessage
  );

  // Auto-connect when enabled
  useEffect(() => {
    if (enabled && classId && token) {
      wsActions.connect();
    } else {
      wsActions.disconnect();
    }

    return () => {
      wsActions.disconnect();
    };
  }, [enabled, classId, token, wsActions]);

  // Request initial stats when connected
  useEffect(() => {
    if (wsState.isConnected) {
      wsActions.sendMessage({ type: 'request_stats' });
    }
  }, [wsState.isConnected, wsActions]);

  return {
    ...wsState,
    ...wsActions,
    messages,
    studentJoins,
    sessionUpdates,
    stats,
    clearMessages: () => setMessages([]),
    clearStudentJoins: () => setStudentJoins([]),
    clearSessionUpdates: () => setSessionUpdates([])
  };
};