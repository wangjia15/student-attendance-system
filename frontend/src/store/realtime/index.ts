/**
 * Real-time state management store for WebSocket-driven updates.
 * 
 * This store manages:
 * - WebSocket connection state
 * - Real-time attendance events
 * - Live student join monitoring
 * - Session statistics updates
 * - System notifications
 * - Connection health monitoring
 */

import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { 
  ConnectionState,
  MessageType,
  StudentJoinedData,
  AttendanceUpdateData,
  SessionUpdateData,
  StatsUpdateData,
  SystemNotificationData
} from '../../services/websocket';

// Real-time store state interface
export interface RealtimeState {
  // Connection state
  connectionState: ConnectionState;
  connectionStats: {
    messagesReceived: number;
    messagesSent: number;
    reconnectionCount: number;
    totalConnections: number;
    averageLatency: number;
    errorCount: number;
    uptime: number;
    isConnected: boolean;
  };
  connectionError: string | null;
  
  // Active connections by class
  activeConnections: Record<string, {
    classId: string;
    token: string;
    connectedAt: string;
    lastActivity: string;
  }>;
  
  // Real-time events
  events: {
    studentJoins: Array<StudentJoinedData & { id: string; timestamp: string }>;
    attendanceUpdates: Array<AttendanceUpdateData & { id: string; timestamp: string }>;
    sessionUpdates: Array<SessionUpdateData & { id: string; timestamp: string }>;
    systemNotifications: Array<SystemNotificationData & { id: string; read: boolean }>;
  };
  
  // Live statistics by class/session
  liveStats: Record<string, StatsUpdateData>;
  
  // Recent activity feed
  activityFeed: Array<{
    id: string;
    type: 'student_joined' | 'attendance_update' | 'session_update' | 'system_notification';
    timestamp: string;
    data: any;
    classId: string;
  }>;
  
  // UI state
  ui: {
    showConnectionIndicator: boolean;
    showNotifications: boolean;
    notificationCount: number;
    soundEnabled: boolean;
    autoScrollActivity: boolean;
  };
}

// Real-time store actions interface
export interface RealtimeActions {
  // Connection management
  setConnectionState: (state: ConnectionState, error?: string) => void;
  updateConnectionStats: (stats: any) => void;
  addActiveConnection: (classId: string, token: string) => void;
  removeActiveConnection: (classId: string) => void;
  
  // Event handling
  addStudentJoin: (data: StudentJoinedData) => void;
  addAttendanceUpdate: (data: AttendanceUpdateData) => void;
  addSessionUpdate: (data: SessionUpdateData) => void;
  addSystemNotification: (data: SystemNotificationData) => void;
  
  // Statistics updates
  updateLiveStats: (classId: string, stats: StatsUpdateData) => void;
  
  // Activity feed management
  addActivityItem: (type: string, data: any, classId: string) => void;
  clearActivityFeed: () => void;
  removeOldActivity: (olderThanHours?: number) => void;
  
  // Notifications management
  markNotificationAsRead: (id: string) => void;
  markAllNotificationsAsRead: () => void;
  clearNotifications: () => void;
  
  // UI state management
  setShowConnectionIndicator: (show: boolean) => void;
  setShowNotifications: (show: boolean) => void;
  setSoundEnabled: (enabled: boolean) => void;
  setAutoScrollActivity: (enabled: boolean) => void;
  
  // Data cleanup
  clearOldEvents: (olderThanHours?: number) => void;
  clearAllEvents: () => void;
  reset: () => void;
}

// Utility functions
const generateId = () => `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

// Initial state
const initialState: RealtimeState = {
  connectionState: ConnectionState.DISCONNECTED,
  connectionStats: {
    messagesReceived: 0,
    messagesSent: 0,
    reconnectionCount: 0,
    totalConnections: 0,
    averageLatency: 0,
    errorCount: 0,
    uptime: 0,
    isConnected: false,
  },
  connectionError: null,
  activeConnections: {},
  events: {
    studentJoins: [],
    attendanceUpdates: [],
    sessionUpdates: [],
    systemNotifications: [],
  },
  liveStats: {},
  activityFeed: [],
  ui: {
    showConnectionIndicator: true,
    showNotifications: true,
    notificationCount: 0,
    soundEnabled: true,
    autoScrollActivity: true,
  },
};

// Create the real-time store
export const useRealtimeStore = create<RealtimeState & RealtimeActions>()(
  subscribeWithSelector((set, get) => ({
    ...initialState,
    
    // Connection management
    setConnectionState: (state: ConnectionState, error?: string) => {
      set((prev) => ({
        ...prev,
        connectionState: state,
        connectionError: error || null,
      }));
    },
    
    updateConnectionStats: (stats: any) => {
      set((prev) => ({
        ...prev,
        connectionStats: {
          ...prev.connectionStats,
          ...stats,
        },
      }));
    },
    
    addActiveConnection: (classId: string, token: string) => {
      set((prev) => ({
        ...prev,
        activeConnections: {
          ...prev.activeConnections,
          [classId]: {
            classId,
            token,
            connectedAt: new Date().toISOString(),
            lastActivity: new Date().toISOString(),
          },
        },
      }));
    },
    
    removeActiveConnection: (classId: string) => {
      set((prev) => {
        const { [classId]: removed, ...remaining } = prev.activeConnections;
        return {
          ...prev,
          activeConnections: remaining,
        };
      });
    },
    
    // Event handling
    addStudentJoin: (data: StudentJoinedData) => {
      const id = generateId();
      const timestamp = new Date().toISOString();
      
      set((prev) => ({
        ...prev,
        events: {
          ...prev.events,
          studentJoins: [
            { ...data, id, timestamp },
            ...prev.events.studentJoins.slice(0, 99), // Keep last 100
          ],
        },
      }));
      
      // Add to activity feed
      get().addActivityItem('student_joined', data, data.session_id);
    },
    
    addAttendanceUpdate: (data: AttendanceUpdateData) => {
      const id = generateId();
      const timestamp = new Date().toISOString();
      
      set((prev) => ({
        ...prev,
        events: {
          ...prev.events,
          attendanceUpdates: [
            { ...data, id, timestamp },
            ...prev.events.attendanceUpdates.slice(0, 99), // Keep last 100
          ],
        },
      }));
      
      // Add to activity feed
      get().addActivityItem('attendance_update', data, data.session_id);
    },
    
    addSessionUpdate: (data: SessionUpdateData) => {
      const id = generateId();
      const timestamp = new Date().toISOString();
      
      set((prev) => ({
        ...prev,
        events: {
          ...prev.events,
          sessionUpdates: [
            { ...data, id, timestamp },
            ...prev.events.sessionUpdates.slice(0, 99), // Keep last 100
          ],
        },
      }));
      
      // Add to activity feed
      get().addActivityItem('session_update', data, data.session_id);
    },
    
    addSystemNotification: (data: SystemNotificationData) => {
      const id = generateId();
      const notification = { ...data, id, read: false };
      
      set((prev) => ({
        ...prev,
        events: {
          ...prev.events,
          systemNotifications: [
            notification,
            ...prev.events.systemNotifications.slice(0, 49), // Keep last 50
          ],
        },
        ui: {
          ...prev.ui,
          notificationCount: prev.ui.notificationCount + 1,
        },
      }));
      
      // Add to activity feed (use a default classId for system notifications)
      get().addActivityItem('system_notification', data, 'system');
    },
    
    // Statistics updates
    updateLiveStats: (classId: string, stats: StatsUpdateData) => {
      set((prev) => ({
        ...prev,
        liveStats: {
          ...prev.liveStats,
          [classId]: stats,
        },
      }));
    },
    
    // Activity feed management
    addActivityItem: (type: string, data: any, classId: string) => {
      const id = generateId();
      const timestamp = new Date().toISOString();
      
      set((prev) => ({
        ...prev,
        activityFeed: [
          { id, type: type as any, timestamp, data, classId },
          ...prev.activityFeed.slice(0, 199), // Keep last 200 items
        ],
      }));
    },
    
    clearActivityFeed: () => {
      set((prev) => ({
        ...prev,
        activityFeed: [],
      }));
    },
    
    removeOldActivity: (olderThanHours = 24) => {
      const cutoffTime = new Date(Date.now() - olderThanHours * 60 * 60 * 1000);
      
      set((prev) => ({
        ...prev,
        activityFeed: prev.activityFeed.filter(
          (item) => new Date(item.timestamp) > cutoffTime
        ),
      }));
    },
    
    // Notifications management
    markNotificationAsRead: (id: string) => {
      set((prev) => ({
        ...prev,
        events: {
          ...prev.events,
          systemNotifications: prev.events.systemNotifications.map((notification) =>
            notification.id === id ? { ...notification, read: true } : notification
          ),
        },
        ui: {
          ...prev.ui,
          notificationCount: Math.max(0, prev.ui.notificationCount - 1),
        },
      }));
    },
    
    markAllNotificationsAsRead: () => {
      set((prev) => ({
        ...prev,
        events: {
          ...prev.events,
          systemNotifications: prev.events.systemNotifications.map((notification) => ({
            ...notification,
            read: true,
          })),
        },
        ui: {
          ...prev.ui,
          notificationCount: 0,
        },
      }));
    },
    
    clearNotifications: () => {
      set((prev) => ({
        ...prev,
        events: {
          ...prev.events,
          systemNotifications: [],
        },
        ui: {
          ...prev.ui,
          notificationCount: 0,
        },
      }));
    },
    
    // UI state management
    setShowConnectionIndicator: (show: boolean) => {
      set((prev) => ({
        ...prev,
        ui: {
          ...prev.ui,
          showConnectionIndicator: show,
        },
      }));
    },
    
    setShowNotifications: (show: boolean) => {
      set((prev) => ({
        ...prev,
        ui: {
          ...prev.ui,
          showNotifications: show,
        },
      }));
    },
    
    setSoundEnabled: (enabled: boolean) => {
      set((prev) => ({
        ...prev,
        ui: {
          ...prev.ui,
          soundEnabled: enabled,
        },
      }));
    },
    
    setAutoScrollActivity: (enabled: boolean) => {
      set((prev) => ({
        ...prev,
        ui: {
          ...prev.ui,
          autoScrollActivity: enabled,
        },
      }));
    },
    
    // Data cleanup
    clearOldEvents: (olderThanHours = 24) => {
      const cutoffTime = new Date(Date.now() - olderThanHours * 60 * 60 * 1000);
      
      set((prev) => ({
        ...prev,
        events: {
          studentJoins: prev.events.studentJoins.filter(
            (event) => new Date(event.timestamp) > cutoffTime
          ),
          attendanceUpdates: prev.events.attendanceUpdates.filter(
            (event) => new Date(event.timestamp) > cutoffTime
          ),
          sessionUpdates: prev.events.sessionUpdates.filter(
            (event) => new Date(event.timestamp) > cutoffTime
          ),
          systemNotifications: prev.events.systemNotifications.filter(
            (event) => new Date(event.timestamp) > cutoffTime
          ),
        },
      }));
    },
    
    clearAllEvents: () => {
      set((prev) => ({
        ...prev,
        events: {
          studentJoins: [],
          attendanceUpdates: [],
          sessionUpdates: [],
          systemNotifications: [],
        },
        ui: {
          ...prev.ui,
          notificationCount: 0,
        },
      }));
    },
    
    reset: () => {
      set(() => ({ ...initialState }));
    },
  }))
);

// Selectors for easy access to specific parts of state
export const useConnectionState = () => {
  return useRealtimeStore((state) => ({
    connectionState: state.connectionState,
    connectionStats: state.connectionStats,
    connectionError: state.connectionError,
    isConnected: state.connectionState === ConnectionState.AUTHENTICATED,
  }));
};

export const useRealtimeEvents = () => {
  return useRealtimeStore((state) => state.events);
};

export const useActivityFeed = () => {
  return useRealtimeStore((state) => state.activityFeed);
};

export const useLiveStats = (classId?: string) => {
  return useRealtimeStore((state) => 
    classId ? state.liveStats[classId] : state.liveStats
  );
};

export const useNotifications = () => {
  return useRealtimeStore((state) => ({
    notifications: state.events.systemNotifications,
    notificationCount: state.ui.notificationCount,
    unreadNotifications: state.events.systemNotifications.filter(n => !n.read),
  }));
};

export const useRealtimeUI = () => {
  return useRealtimeStore((state) => state.ui);
};

// Auto-cleanup old events periodically
if (typeof window !== 'undefined') {
  setInterval(() => {
    const state = useRealtimeStore.getState();
    state.removeOldActivity(24); // Remove activity older than 24 hours
    state.clearOldEvents(24); // Remove events older than 24 hours
  }, 60 * 60 * 1000); // Run every hour
}

export default useRealtimeStore;