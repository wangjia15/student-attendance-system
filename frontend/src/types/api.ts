// API Types for Student Attendance System

export interface ClassSessionCreate {
  class_name: string;
  subject?: string;
  expiration_minutes: number;
  max_students?: number;
  allow_late_join: boolean;
}

export interface ClassSessionResponse {
  id: string;
  class_name: string;
  subject?: string;
  teacher_id: string;
  status: SessionStatus;
  
  // Timing
  created_at: string;
  expires_at: string;
  ended_at?: string;
  
  // Access information
  verification_code: string;
  share_link: string;
  qr_code_data: string;
  
  // Statistics
  total_joins: number;
  unique_student_count: number;
  
  // Settings
  max_students?: number;
  allow_late_join: boolean;
}

export interface QRCodeRegenerateResponse {
  class_id: string;
  qr_code_data: string;
  jwt_token: string;
  regenerated_at: string;
  expires_at: string;
}

export interface VerificationCodeRegenerateResponse {
  class_id: string;
  verification_code: string;
  share_link: string;
  regenerated_at: string;
}

export interface ShareLinkResponse {
  class_id: string;
  class_name: string;
  share_link: string;
  verification_code: string;
  deep_link: string;
  qr_code_data: string;
}

export interface StudentJoin {
  student_id: string;
  student_name: string;
  class_id: string;
  joined_at: string;
  join_method: 'qr_code' | 'link' | 'manual_code';
  ip_address?: string;
  user_agent?: string;
  latitude?: number;
  longitude?: number;
}

export interface LiveSessionStats {
  class_id: string;
  class_name: string;
  status: SessionStatus;
  time_remaining_minutes: number;
  total_joins: number;
  unique_students: number;
  recent_joins: StudentJoin[];
  participation_rate?: number;
}

export type SessionStatus = 'active' | 'expired' | 'ended';

export interface APIError {
  detail: string;
  status_code: number;
}

// WebSocket message types
export interface WebSocketMessage {
  type: string;
  timestamp: string;
  class_id?: string;
  data?: any;
}

export interface StudentJoinedMessage extends WebSocketMessage {
  type: 'student_joined';
  data: {
    student_id: string;
    student_name: string;
    joined_at: string;
    join_method: string;
  };
}

export interface SessionUpdatedMessage extends WebSocketMessage {
  type: 'session_updated';
  data: {
    qr_code_regenerated?: boolean;
    verification_code_regenerated?: boolean;
    new_qr_code?: string;
    new_verification_code?: string;
    new_share_link?: string;
    regenerated_at: string;
  };
}

export interface SessionEndedMessage extends WebSocketMessage {
  type: 'session_ended';
  data: {
    final_stats: LiveSessionStats;
  };
}

export interface StatsUpdateMessage extends WebSocketMessage {
  type: 'stats_update';
  data: LiveSessionStats;
}