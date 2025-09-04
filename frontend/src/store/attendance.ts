// Attendance State Management with Zustand
import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import { persist, createJSONStorage } from 'zustand/middleware';
import {
  AttendanceState,
  AttendanceActions,
  AttendanceRecord,
  StudentCheckInResponse,
  ClassAttendanceStatus,
  ClassAttendanceReport,
  AttendanceStatusUpdate,
  CheckInMethod,
  AttendanceAlert,
  StudentAttendancePattern
} from '../types/attendance';
import attendanceService from '../services/attendance';

// Initial state
const initialState: AttendanceState = {
  records: {},
  classStatus: {},
  myAttendance: [],
  loading: {
    checkIn: false,
    status: false,
    history: false,
    patterns: false,
  },
  errors: {},
  liveUpdates: [],
  optimisticUpdates: {},
  offline: {
    isOffline: false,
    pendingOperations: [],
  },
  patterns: {},
  alerts: [],
};

// Utility to generate unique IDs for optimistic updates
const generateOptimisticId = (): string => {
  return `opt_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
};

// WebSocket connection manager
class AttendanceWebSocketManager {
  private connections: Map<number, WebSocket> = new Map();
  private reconnectAttempts: Map<number, number> = new Map();
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;

  connect(classId: number, onMessage: (update: AttendanceStatusUpdate) => void) {
    if (this.connections.has(classId)) {
      return; // Already connected
    }

    const wsUrl = `${process.env.REACT_APP_WS_URL || 'ws://localhost:8000'}/ws/attendance/${classId}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log(`Connected to attendance WebSocket for class ${classId}`);
      this.reconnectAttempts.set(classId, 0);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'attendance_update') {
          onMessage(data.data);
        }
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    ws.onclose = () => {
      console.log(`Disconnected from attendance WebSocket for class ${classId}`);
      this.connections.delete(classId);
      
      // Attempt to reconnect
      const attempts = this.reconnectAttempts.get(classId) || 0;
      if (attempts < this.maxReconnectAttempts) {
        this.reconnectAttempts.set(classId, attempts + 1);
        setTimeout(() => {
          this.connect(classId, onMessage);
        }, this.reconnectDelay * Math.pow(2, attempts));
      }
    };

    ws.onerror = (error) => {
      console.error(`WebSocket error for class ${classId}:`, error);
    };

    this.connections.set(classId, ws);
  }

  disconnect(classId: number) {
    const ws = this.connections.get(classId);
    if (ws) {
      ws.close();
      this.connections.delete(classId);
      this.reconnectAttempts.delete(classId);
    }
  }

  disconnectAll() {
    this.connections.forEach((ws, classId) => {
      ws.close();
    });
    this.connections.clear();
    this.reconnectAttempts.clear();
  }
}

const wsManager = new AttendanceWebSocketManager();

// Create the store with all functionality
export const useAttendanceStore = create<AttendanceState & AttendanceActions>()(
  subscribeWithSelector(
    persist(
      (set, get) => ({
        ...initialState,

        // Student check-in actions
        checkInWithQR: async (qrToken: string): Promise<StudentCheckInResponse> => {
          const optimisticId = get().performOptimisticCheckIn('qr_code', { jwt_token: qrToken });
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, checkIn: true },
            errors: { ...state.errors, checkIn: undefined }
          }));

          try {
            const response = await attendanceService.checkInWithQR(qrToken);
            
            // Confirm optimistic update
            get().confirmOptimisticUpdate(optimisticId);
            
            // Update current session info
            set((state) => ({
              ...state,
              currentSession: {
                id: response.class_session_id,
                name: response.class_name,
                status: response.attendance_status,
                checkInTime: response.join_time,
                isLate: response.is_late,
                lateMinutes: response.late_minutes,
              },
              loading: { ...state.loading, checkIn: false },
            }));

            return response;
          } catch (error) {
            get().rollbackOptimisticUpdate(optimisticId);
            const errorMessage = error instanceof Error ? error.message : 'Check-in failed';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, checkIn: false },
              errors: { ...state.errors, checkIn: errorMessage }
            }));
            throw error;
          }
        },

        checkInWithCode: async (code: string): Promise<StudentCheckInResponse> => {
          const optimisticId = get().performOptimisticCheckIn('verification_code', { verification_code: code });
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, checkIn: true },
            errors: { ...state.errors, checkIn: undefined }
          }));

          try {
            const response = await attendanceService.checkInWithCode(code);
            
            // Confirm optimistic update
            get().confirmOptimisticUpdate(optimisticId);
            
            // Update current session info
            set((state) => ({
              ...state,
              currentSession: {
                id: response.class_session_id,
                name: response.class_name,
                status: response.attendance_status,
                checkInTime: response.join_time,
                isLate: response.is_late,
                lateMinutes: response.late_minutes,
              },
              loading: { ...state.loading, checkIn: false },
            }));

            return response;
          } catch (error) {
            get().rollbackOptimisticUpdate(optimisticId);
            const errorMessage = error instanceof Error ? error.message : 'Check-in failed';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, checkIn: false },
              errors: { ...state.errors, checkIn: errorMessage }
            }));
            throw error;
          }
        },

        checkout: async (sessionId: number): Promise<void> => {
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, checkIn: true },
            errors: { ...state.errors, checkIn: undefined }
          }));

          try {
            await attendanceService.checkOut(sessionId);
            
            // Update current session
            set((state) => ({
              ...state,
              currentSession: state.currentSession ? {
                ...state.currentSession,
                status: 'ABSENT' as const, // Checked out
              } : undefined,
              loading: { ...state.loading, checkIn: false },
            }));
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Check-out failed';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, checkIn: false },
              errors: { ...state.errors, checkIn: errorMessage }
            }));
            throw error;
          }
        },

        // Status and history
        loadMyAttendance: async (): Promise<void> => {
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, history: true },
            errors: { ...state.errors, history: undefined }
          }));

          try {
            const attendance = await attendanceService.getMyAttendance();
            set((state) => ({
              ...state,
              myAttendance: attendance,
              loading: { ...state.loading, history: false },
            }));
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Failed to load attendance';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, history: false },
              errors: { ...state.errors, history: errorMessage }
            }));
          }
        },

        loadClassStatus: async (classId: number): Promise<void> => {
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, status: true },
            errors: { ...state.errors, status: undefined }
          }));

          try {
            const status = await attendanceService.getClassAttendanceStatus(classId);
            set((state) => ({
              ...state,
              classStatus: { ...state.classStatus, [classId]: status },
              loading: { ...state.loading, status: false },
            }));
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Failed to load class status';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, status: false },
              errors: { ...state.errors, status: errorMessage }
            }));
          }
        },

        loadClassReport: async (classId: number): Promise<ClassAttendanceReport> => {
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, status: true },
            errors: { ...state.errors, status: undefined }
          }));

          try {
            const report = await attendanceService.getClassAttendanceReport(classId, true);
            
            // Update records
            const recordsUpdate: Record<number, AttendanceRecord> = {};
            report.records.forEach(record => {
              recordsUpdate[record.id] = record;
            });

            set((state) => ({
              ...state,
              records: { ...state.records, ...recordsUpdate },
              classStatus: { ...state.classStatus, [classId]: {
                class_session_id: classId,
                class_name: report.class_name,
                total_enrolled: report.stats.total_students,
                checked_in_count: report.stats.present_count + report.stats.late_count,
                present_count: report.stats.present_count,
                late_count: report.stats.late_count,
                absent_count: report.stats.absent_count,
                excused_count: report.stats.excused_count,
                last_updated: new Date().toISOString(),
              }},
              loading: { ...state.loading, status: false },
            }));

            return report;
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Failed to load class report';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, status: false },
              errors: { ...state.errors, status: errorMessage }
            }));
            throw error;
          }
        },

        // Real-time updates
        subscribeToUpdates: (classId: number): void => {
          wsManager.connect(classId, get().handleStatusUpdate);
        },

        unsubscribeFromUpdates: (classId: number): void => {
          wsManager.disconnect(classId);
        },

        handleStatusUpdate: (update: AttendanceStatusUpdate): void => {
          set((state) => {
            // Update live updates
            const newUpdates = [update, ...state.liveUpdates.slice(0, 99)]; // Keep last 100 updates

            // Update class status if available
            const classStatus = state.classStatus[update.class_session_id];
            let updatedClassStatus = classStatus;
            if (classStatus) {
              // Recalculate counts based on status change
              const statusChanges: Record<string, number> = {
                present_count: 0,
                late_count: 0,
                absent_count: 0,
                excused_count: 0,
              };

              // Subtract old status
              const oldKey = `${update.old_status.toLowerCase()}_count` as keyof typeof statusChanges;
              if (oldKey in statusChanges) {
                statusChanges[oldKey] = -1;
              }

              // Add new status
              const newKey = `${update.new_status.toLowerCase()}_count` as keyof typeof statusChanges;
              if (newKey in statusChanges) {
                statusChanges[newKey] = 1;
              }

              updatedClassStatus = {
                ...classStatus,
                present_count: Math.max(0, classStatus.present_count + statusChanges.present_count),
                late_count: Math.max(0, classStatus.late_count + statusChanges.late_count),
                absent_count: Math.max(0, classStatus.absent_count + statusChanges.absent_count),
                excused_count: Math.max(0, classStatus.excused_count + statusChanges.excused_count),
                last_updated: update.timestamp,
              };
            }

            return {
              ...state,
              liveUpdates: newUpdates,
              classStatus: updatedClassStatus ? {
                ...state.classStatus,
                [update.class_session_id]: updatedClassStatus,
              } : state.classStatus,
            };
          });
        },

        // Optimistic updates
        performOptimisticCheckIn: (method: CheckInMethod, data: any): string => {
          const optimisticId = generateOptimisticId();
          const now = new Date();

          set((state) => ({
            ...state,
            optimisticUpdates: {
              ...state.optimisticUpdates,
              [optimisticId]: {
                type: 'check_in',
                originalState: {
                  currentSession: state.currentSession,
                },
                timestamp: now,
              },
            },
            currentSession: {
              id: 0, // Will be updated on success
              name: 'Checking in...',
              status: 'PRESENT' as const,
              checkInTime: now.toISOString(),
              isLate: false,
              lateMinutes: 0,
            },
          }));

          return optimisticId;
        },

        rollbackOptimisticUpdate: (updateId: string): void => {
          set((state) => {
            const update = state.optimisticUpdates[updateId];
            if (!update) return state;

            const { [updateId]: removed, ...remainingUpdates } = state.optimisticUpdates;

            return {
              ...state,
              optimisticUpdates: remainingUpdates,
              currentSession: update.originalState.currentSession,
            };
          });
        },

        confirmOptimisticUpdate: (updateId: string): void => {
          set((state) => {
            const { [updateId]: removed, ...remainingUpdates } = state.optimisticUpdates;
            return {
              ...state,
              optimisticUpdates: remainingUpdates,
            };
          });
        },

        // Offline support
        setOfflineStatus: (isOffline: boolean): void => {
          set((state) => ({
            ...state,
            offline: { ...state.offline, isOffline },
          }));
        },

        addPendingOperation: (operation: any): void => {
          set((state) => ({
            ...state,
            offline: {
              ...state.offline,
              pendingOperations: [...state.offline.pendingOperations, {
                id: generateOptimisticId(),
                ...operation,
                timestamp: new Date(),
              }],
            },
          }));
        },

        syncPendingOperations: async (): Promise<void> => {
          const { offline } = get();
          const operations = [...offline.pendingOperations];

          for (const operation of operations) {
            try {
              switch (operation.type) {
                case 'check_in':
                  if (operation.data.method === 'qr_code') {
                    await get().checkInWithQR(operation.data.jwt_token);
                  } else if (operation.data.method === 'verification_code') {
                    await get().checkInWithCode(operation.data.verification_code);
                  }
                  break;
                default:
                  console.warn('Unknown pending operation type:', operation.type);
              }

              // Remove successful operation
              set((state) => ({
                ...state,
                offline: {
                  ...state.offline,
                  pendingOperations: state.offline.pendingOperations.filter(op => op.id !== operation.id),
                },
              }));
            } catch (error) {
              console.error('Failed to sync operation:', operation, error);
            }
          }
        },

        clearPendingOperations: (): void => {
          set((state) => ({
            ...state,
            offline: { ...state.offline, pendingOperations: [] },
          }));
        },

        // Pattern analysis
        loadPatterns: async (studentId?: number): Promise<void> => {
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, patterns: true },
            errors: { ...state.errors, patterns: undefined }
          }));

          try {
            const alerts = await attendanceService.analyzeAttendancePatterns({
              student_id: studentId,
            });

            set((state) => ({
              ...state,
              alerts,
              loading: { ...state.loading, patterns: false },
            }));
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Failed to load patterns';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, patterns: false },
              errors: { ...state.errors, patterns: errorMessage }
            }));
          }
        },

        loadAlerts: async (classId?: number): Promise<void> => {
          set((state) => ({ 
            ...state, 
            loading: { ...state.loading, patterns: true },
            errors: { ...state.errors, patterns: undefined }
          }));

          try {
            const alerts = await attendanceService.analyzeAttendancePatterns({
              class_session_id: classId,
            });

            set((state) => ({
              ...state,
              alerts,
              loading: { ...state.loading, patterns: false },
            }));
          } catch (error) {
            const errorMessage = error instanceof Error ? error.message : 'Failed to load alerts';
            set((state) => ({ 
              ...state, 
              loading: { ...state.loading, patterns: false },
              errors: { ...state.errors, patterns: errorMessage }
            }));
          }
        },

        // Error handling
        setError: (type: string, error: string): void => {
          set((state) => ({
            ...state,
            errors: { ...state.errors, [type]: error },
          }));
        },

        clearError: (type: string): void => {
          set((state) => ({
            ...state,
            errors: { ...state.errors, [type]: undefined },
          }));
        },

        clearAllErrors: (): void => {
          set((state) => ({
            ...state,
            errors: {},
          }));
        },

        // Utility actions
        reset: (): void => {
          wsManager.disconnectAll();
          set(() => ({ ...initialState }));
        },

        setLoading: (type: string, loading: boolean): void => {
          set((state) => ({
            ...state,
            loading: { ...state.loading, [type]: loading },
          }));
        },
      }),
      {
        name: 'attendance-store',
        storage: createJSONStorage(() => localStorage),
        partialize: (state) => ({
          // Only persist non-sensitive, non-temporary data
          myAttendance: state.myAttendance,
          currentSession: state.currentSession,
          offline: state.offline,
        }),
      }
    )
  )
);

// Selectors for easy access to specific parts of state
export const useAttendanceStatus = (classId?: number) => {
  return useAttendanceStore((state) => classId ? state.classStatus[classId] : null);
};

export const useMyAttendance = () => {
  return useAttendanceStore((state) => state.myAttendance);
};

export const useCurrentSession = () => {
  return useAttendanceStore((state) => state.currentSession);
};

export const useAttendanceLoading = () => {
  return useAttendanceStore((state) => state.loading);
};

export const useAttendanceErrors = () => {
  return useAttendanceStore((state) => state.errors);
};

export const useOfflineStatus = () => {
  return useAttendanceStore((state) => state.offline);
};

// Initialize offline detection
if (typeof window !== 'undefined') {
  const store = useAttendanceStore.getState();
  
  window.addEventListener('online', () => {
    store.setOfflineStatus(false);
    store.syncPendingOperations();
  });

  window.addEventListener('offline', () => {
    store.setOfflineStatus(true);
  });

  // Set initial offline status
  store.setOfflineStatus(!navigator.onLine);
}

export default useAttendanceStore;