// API Types for Student Attendance System

// Session Status Enum
export enum SessionStatus {
  ACTIVE = 'active',
  PAUSED = 'paused',
  ENDED = 'ended',
  EXPIRED = 'expired'
}

// User Role Enum
export enum UserRole {
  TEACHER = 'teacher',
  STUDENT = 'student',
  ADMIN = 'admin'
}

// Attendance Status Enum
export enum AttendanceStatus {
  PRESENT = 'present',
  LATE = 'late',
  ABSENT = 'absent',
  EXCUSED = 'excused'
}

// Class Session Types
export interface ClassSessionCreate {
  name: string;
  description?: string;
  subject?: string;
  location?: string;
  duration_minutes?: number;
  allow_late_join: boolean;
  require_verification: boolean;
  auto_end_minutes: number;
}

export interface ClassSessionResponse {
  id: number;
  name: string;
  description?: string;
  subject?: string;
  location?: string;
  status: SessionStatus;
  verification_code: string;
  qr_data?: string;
  start_time: string;
  end_time?: string;
  duration_minutes?: number;
  allow_late_join: boolean;
  require_verification: boolean;
  created_at: string;
}

export interface QRCodeResponse {
  qr_code_data: string;
  verification_code: string;
  deep_link: string;
  expires_at: string;
}

export interface ShareLinkResponse {
  session_id: number;
  verification_code: string;
  deep_link: string;
  web_link: string;
  sms_text: string;
  email_subject: string;
  email_body: string;
}

// Authentication Types
export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  username: string;
  full_name: string;
  password: string;
  role: UserRole;
}

export interface UserResponse {
  id: number;
  email: string;
  username: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  last_login?: string;
}

export interface Token {
  access_token: string;
  refresh_token?: string;
  token_type: string;
  user?: UserResponse;
}

// Attendance Types
export interface StudentJoinRequest {
  jwt_token: string;
}

export interface VerificationCodeJoinRequest {
  verification_code: string;
}

export interface StudentJoinResponse {
  success: boolean;
  message: string;
  class_session_id: number;
  class_name: string;
  join_time: string;
  attendance_status: AttendanceStatus;
  is_late?: boolean;
  late_minutes?: number;
}

export interface AttendanceResponse {
  id: number;
  class_session_id: number;
  class_name: string;
  subject?: string;
  teacher_name: string;
  status: AttendanceStatus;
  check_in_time: string;
  check_out_time?: string;
  verification_method?: string;
  is_late?: boolean;
  late_minutes?: number;
  is_manual_override?: boolean;
  override_reason?: string;
}

// WebSocket Types (updated for new backend)
export interface StudentJoin {
  student_id: number;
  student_name: string;
  join_time: string;
  verification_method: string;
}

export interface LiveSessionStats {
  class_session_id: number;
  total_students: number;
  present_students: number;
  late_students: number;
  absent_students: number;
  last_updated: string;
}

export interface WebSocketMessage {
  type: string;
  data: any;
  timestamp: string;
}

export interface StudentJoinedMessage extends WebSocketMessage {
  type: 'student_joined';
  data: StudentJoin;
}

export interface SessionStatsMessage extends WebSocketMessage {
  type: 'session_stats';
  data: LiveSessionStats;
}

export interface SessionEndedMessage extends WebSocketMessage {
  type: 'session_ended';
  data: {
    class_session_id: number;
    end_time: string;
    final_stats: LiveSessionStats;
  };
}

// Error Types
export interface APIError {
  detail: string;
  status_code: number;
}