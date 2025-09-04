// Comprehensive Attendance Types for Frontend State Management
import { AttendanceStatus } from './api';

// Enhanced Student Check-in Types
export interface StudentCheckInRequest {
  method: CheckInMethod;
  data: QRCheckInData | CodeCheckInData;
}

export interface QRCheckInData {
  jwt_token: string;
}

export interface CodeCheckInData {
  verification_code: string;
}

export type CheckInMethod = 'qr_code' | 'verification_code';

// Enhanced Response Types with Late Detection
export interface StudentCheckInResponse {
  success: boolean;
  message: string;
  class_session_id: number;
  class_name: string;
  join_time: string;
  attendance_status: AttendanceStatus;
  is_late: boolean;
  late_minutes: number;
}

// Enhanced Attendance Record Types
export interface AttendanceRecord {
  id: number;
  class_session_id: number;
  class_name: string;
  subject?: string;
  teacher_name: string;
  student_name?: string;
  status: AttendanceStatus;
  check_in_time?: string;
  check_out_time?: string;
  verification_method?: string;
  is_late: boolean;
  late_minutes: number;
  is_manual_override: boolean;
  override_reason?: string;
  override_teacher_name?: string;
  notes?: string;
  created_at: string;
  updated_at?: string;
}

// Teacher Override Types
export interface TeacherOverrideRequest {
  student_id: number;
  new_status: AttendanceStatus;
  reason: string;
  notes?: string;
}

// Bulk Operations
export enum BulkAttendanceOperation {
  MARK_PRESENT = 'mark_present',
  MARK_ABSENT = 'mark_absent',
  MARK_LATE = 'mark_late',
  MARK_EXCUSED = 'mark_excused'
}

export interface BulkAttendanceRequest {
  class_session_id: number;
  operation: BulkAttendanceOperation;
  student_ids?: number[];
  reason: string;
  notes?: string;
}

export interface BulkAttendanceResponse {
  success: boolean;
  message: string;
  processed_count: number;
  failed_count: number;
  failed_students: Array<{
    student_id: number;
    error: string;
  }>;
}

// Statistics and Analytics
export interface AttendanceStats {
  total_students: number;
  present_count: number;
  late_count: number;
  absent_count: number;
  excused_count: number;
  attendance_rate: number;
  late_rate: number;
}

export interface StudentAttendancePattern {
  student_id: number;
  student_name: string;
  total_sessions: number;
  present_count: number;
  late_count: number;
  absent_count: number;
  excused_count: number;
  consecutive_absences: number;
  attendance_rate: number;
  is_at_risk: boolean;
  risk_factors: string[];
}

export interface ClassAttendanceReport {
  class_session_id: number;
  class_name: string;
  subject?: string;
  teacher_name: string;
  start_time: string;
  end_time?: string;
  duration_minutes?: number;
  stats: AttendanceStats;
  records: AttendanceRecord[];
  patterns: StudentAttendancePattern[];
}

// Real-time Updates
export interface AttendanceStatusUpdate {
  class_session_id: number;
  student_id: number;
  old_status: AttendanceStatus;
  new_status: AttendanceStatus;
  timestamp: string;
  updated_by: string;
  reason?: string;
}

export interface ClassAttendanceStatus {
  class_session_id: number;
  class_name: string;
  total_enrolled: number;
  checked_in_count: number;
  present_count: number;
  late_count: number;
  absent_count: number;
  excused_count: number;
  last_updated: string;
}

// Pattern Detection and Alerts
export interface AttendancePatternRequest {
  class_session_id?: number;
  student_id?: number;
  date_from?: string;
  date_to?: string;
  min_sessions?: number;
}

export interface AttendanceAlert {
  type: 'consecutive_absence' | 'low_attendance' | 'irregular_pattern';
  severity: 'low' | 'medium' | 'high';
  student_id: number;
  student_name: string;
  message: string;
  data: Record<string, any>;
  created_at: string;
}

// Audit Trail
export interface AttendanceAuditLog {
  id: number;
  attendance_record_id: number;
  user_name: string;
  action: string;
  old_status?: AttendanceStatus;
  new_status: AttendanceStatus;
  reason?: string;
  created_at: string;
}

// Frontend State Management Types
export interface AttendanceState {
  // Current attendance records
  records: Record<number, AttendanceRecord>;
  
  // Class session attendance status
  classStatus: Record<number, ClassAttendanceStatus>;
  
  // Student's own attendance
  myAttendance: AttendanceRecord[];
  
  // Loading states
  loading: {
    checkIn: boolean;
    status: boolean;
    history: boolean;
    patterns: boolean;
  };
  
  // Error states
  errors: {
    checkIn?: string;
    status?: string;
    history?: string;
    patterns?: string;
  };
  
  // Real-time updates
  liveUpdates: AttendanceStatusUpdate[];
  
  // Optimistic updates tracking
  optimisticUpdates: Record<string, {
    type: 'check_in' | 'status_change';
    originalState: any;
    timestamp: Date;
  }>;
  
  // Offline state
  offline: {
    isOffline: boolean;
    pendingOperations: Array<{
      id: string;
      type: 'check_in' | 'status_update';
      data: any;
      timestamp: Date;
    }>;
  };
  
  // Current session info
  currentSession?: {
    id: number;
    name: string;
    status: AttendanceStatus;
    checkInTime?: string;
    isLate?: boolean;
    lateMinutes?: number;
  };
  
  // Pattern analysis cache
  patterns: Record<number, StudentAttendancePattern>;
  
  // Alerts
  alerts: AttendanceAlert[];
}

// Action Types for State Management
export interface AttendanceActions {
  // Student check-in actions
  checkInWithQR: (qrToken: string) => Promise<StudentCheckInResponse>;
  checkInWithCode: (code: string) => Promise<StudentCheckInResponse>;
  checkout: (sessionId: number) => Promise<void>;
  
  // Status and history
  loadMyAttendance: () => Promise<void>;
  loadClassStatus: (classId: number) => Promise<void>;
  loadClassReport: (classId: number) => Promise<ClassAttendanceReport>;
  
  // Real-time updates
  subscribeToUpdates: (classId: number) => void;
  unsubscribeFromUpdates: (classId: number) => void;
  handleStatusUpdate: (update: AttendanceStatusUpdate) => void;
  
  // Optimistic updates
  performOptimisticCheckIn: (method: CheckInMethod, data: any) => string;
  rollbackOptimisticUpdate: (updateId: string) => void;
  confirmOptimisticUpdate: (updateId: string) => void;
  
  // Offline support
  setOfflineStatus: (isOffline: boolean) => void;
  addPendingOperation: (operation: any) => void;
  syncPendingOperations: () => Promise<void>;
  clearPendingOperations: () => void;
  
  // Pattern analysis
  loadPatterns: (studentId?: number) => Promise<void>;
  loadAlerts: (classId?: number) => Promise<void>;
  
  // Error handling
  setError: (type: string, error: string) => void;
  clearError: (type: string) => void;
  clearAllErrors: () => void;
  
  // Utility actions
  reset: () => void;
  setLoading: (type: string, loading: boolean) => void;
}

// Component Props Types
export interface StudentCheckInProps {
  classId?: number;
  onSuccess?: (response: StudentCheckInResponse) => void;
  onError?: (error: string) => void;
  mode?: 'full' | 'qr-only' | 'code-only';
}

export interface AttendanceStatusProps {
  classId?: number;
  studentId?: number;
  showDetails?: boolean;
  showHistory?: boolean;
  refreshInterval?: number;
}

// Event Types
export interface AttendanceEvent {
  type: 'check_in' | 'check_out' | 'status_change' | 'pattern_alert';
  data: any;
  timestamp: Date;
}

// Utility Types
export type AttendanceFilter = {
  status?: AttendanceStatus[];
  dateFrom?: Date;
  dateTo?: Date;
  classId?: number;
  studentId?: number;
};

export type AttendanceSortBy = 'date' | 'class' | 'status' | 'student';
export type AttendanceSortOrder = 'asc' | 'desc';

// Validation Types
export interface ValidationResult {
  isValid: boolean;
  errors: string[];
}

export interface CheckInValidation extends ValidationResult {
  canCheckIn: boolean;
  isLate: boolean;
  lateMinutes: number;
  warnings: string[];
}