// Attendance Service for API Integration
import {
  StudentCheckInRequest,
  StudentCheckInResponse,
  AttendanceRecord,
  AttendanceStats,
  ClassAttendanceStatus,
  ClassAttendanceReport,
  AttendancePatternRequest,
  AttendanceAlert,
  AttendanceAuditLog,
  TeacherOverrideRequest,
  BulkAttendanceRequest,
  BulkAttendanceResponse,
  QRCheckInData,
  CodeCheckInData
} from '../types/attendance';
import { getAuthToken } from './api';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

class AttendanceService {
  private baseURL: string;

  constructor(baseURL: string = API_BASE_URL) {
    this.baseURL = baseURL;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {},
    requireAuth: boolean = true
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    
    const defaultHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    // Add authentication header if required and token exists
    const authToken = getAuthToken();
    if (requireAuth && authToken) {
      defaultHeaders.Authorization = `Bearer ${authToken}`;
    }

    const config: RequestInit = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      
      if (!response.ok) {
        let errorData: any;
        try {
          errorData = await response.json();
        } catch {
          errorData = {
            detail: `HTTP ${response.status}: ${response.statusText}`,
            status_code: response.status
          };
        }
        throw new Error(errorData.detail || 'An error occurred');
      }

      return await response.json();
    } catch (error) {
      if (error instanceof Error) {
        throw error;
      }
      throw new Error('Network error occurred');
    }
  }

  // Student Check-in Methods
  async checkInWithQR(qrToken: string): Promise<StudentCheckInResponse> {
    return this.request<StudentCheckInResponse>('/api/v1/attendance/check-in/qr', {
      method: 'POST',
      body: JSON.stringify({ jwt_token: qrToken }),
    });
  }

  async checkInWithCode(verificationCode: string): Promise<StudentCheckInResponse> {
    return this.request<StudentCheckInResponse>('/api/v1/attendance/check-in/code', {
      method: 'POST',
      body: JSON.stringify({ verification_code: verificationCode }),
    });
  }

  async checkOut(sessionId: number): Promise<{ message: string; check_out_time: string }> {
    return this.request(`/api/v1/attendance/checkout/${sessionId}`, {
      method: 'POST',
    });
  }

  // Attendance History and Status
  async getMyAttendance(limit: number = 50, offset: number = 0): Promise<AttendanceRecord[]> {
    const params = new URLSearchParams();
    params.append('limit', limit.toString());
    params.append('offset', offset.toString());
    
    return this.request<AttendanceRecord[]>(`/api/v1/attendance/my-attendance?${params.toString()}`);
  }

  async getClassAttendanceStatus(classId: number): Promise<ClassAttendanceStatus> {
    return this.request<ClassAttendanceStatus>(`/api/v1/attendance/class/${classId}/status`);
  }

  async getClassAttendanceReport(
    classId: number, 
    includePatterns: boolean = false
  ): Promise<ClassAttendanceReport> {
    const params = new URLSearchParams();
    if (includePatterns) {
      params.append('include_patterns', 'true');
    }
    
    return this.request<ClassAttendanceReport>(
      `/api/v1/attendance/class/${classId}/report?${params.toString()}`
    );
  }

  // Pattern Analysis and Alerts
  async analyzeAttendancePatterns(request: AttendancePatternRequest): Promise<AttendanceAlert[]> {
    const params = new URLSearchParams();
    
    if (request.class_session_id) {
      params.append('class_session_id', request.class_session_id.toString());
    }
    if (request.student_id) {
      params.append('student_id', request.student_id.toString());
    }
    if (request.date_from) {
      params.append('date_from', request.date_from);
    }
    if (request.date_to) {
      params.append('date_to', request.date_to);
    }
    if (request.min_sessions) {
      params.append('min_sessions', request.min_sessions.toString());
    }

    return this.request<AttendanceAlert[]>(`/api/v1/attendance/patterns/analyze?${params.toString()}`);
  }

  // Audit Trail
  async getAttendanceAuditTrail(attendanceRecordId: number): Promise<AttendanceAuditLog[]> {
    return this.request<AttendanceAuditLog[]>(`/api/v1/attendance/audit/${attendanceRecordId}`);
  }

  // Teacher Override Methods (for completeness, though Stream C focuses on student interface)
  async teacherOverrideAttendance(
    classId: number, 
    override: TeacherOverrideRequest
  ): Promise<{ success: boolean; message: string }> {
    return this.request(`/api/v1/attendance/override/${classId}`, {
      method: 'PUT',
      body: JSON.stringify(override),
    });
  }

  async bulkAttendanceOperation(request: BulkAttendanceRequest): Promise<BulkAttendanceResponse> {
    return this.request<BulkAttendanceResponse>('/api/v1/attendance/bulk-operations', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  // Utility Methods
  async validateCheckIn(sessionId: number): Promise<{
    canCheckIn: boolean;
    isLate: boolean;
    lateMinutes: number;
    sessionStatus: string;
    message: string;
  }> {
    // This would typically be a separate endpoint, but we can derive from class status
    try {
      const status = await this.getClassAttendanceStatus(sessionId);
      const now = new Date();
      
      // Basic validation - in a real implementation, this would come from the backend
      return {
        canCheckIn: true,
        isLate: false,
        lateMinutes: 0,
        sessionStatus: 'active',
        message: 'Ready to check in'
      };
    } catch (error) {
      return {
        canCheckIn: false,
        isLate: false,
        lateMinutes: 0,
        sessionStatus: 'unknown',
        message: error instanceof Error ? error.message : 'Validation failed'
      };
    }
  }

  // Offline Support Utilities
  serializeForOffline(data: any): string {
    return JSON.stringify({
      ...data,
      timestamp: new Date().toISOString(),
      offline: true
    });
  }

  deserializeFromOffline(serialized: string): any {
    try {
      return JSON.parse(serialized);
    } catch {
      return null;
    }
  }

  // Check network connectivity
  async checkConnectivity(): Promise<boolean> {
    try {
      // Simple ping to check if API is reachable
      await this.request('/api/v1/health', { 
        method: 'GET' 
      }, false);
      return true;
    } catch {
      return false;
    }
  }

  // Retry mechanism for failed requests
  async retryRequest<T>(
    requestFn: () => Promise<T>,
    maxRetries: number = 3,
    delay: number = 1000
  ): Promise<T> {
    let lastError: Error;
    
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      try {
        return await requestFn();
      } catch (error) {
        lastError = error instanceof Error ? error : new Error('Unknown error');
        
        if (attempt < maxRetries) {
          // Exponential backoff
          await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, attempt)));
        }
      }
    }
    
    throw lastError!;
  }

  // Batch operations for efficiency
  async batchCheckIn(requests: Array<{ method: 'qr' | 'code'; data: string }>): Promise<StudentCheckInResponse[]> {
    const results = await Promise.allSettled(
      requests.map(req => 
        req.method === 'qr' 
          ? this.checkInWithQR(req.data)
          : this.checkInWithCode(req.data)
      )
    );

    return results.map((result, index) => {
      if (result.status === 'fulfilled') {
        return result.value;
      } else {
        // Return error response in consistent format
        return {
          success: false,
          message: result.reason.message || 'Check-in failed',
          class_session_id: 0,
          class_name: '',
          join_time: new Date().toISOString(),
          attendance_status: 'ABSENT' as const,
          is_late: false,
          late_minutes: 0
        };
      }
    });
  }
}

// Create and export singleton instance
const attendanceService = new AttendanceService();

// Export individual methods for easier importing
export const {
  checkInWithQR,
  checkInWithCode,
  checkOut,
  getMyAttendance,
  getClassAttendanceStatus,
  getClassAttendanceReport,
  analyzeAttendancePatterns,
  getAttendanceAuditTrail,
  teacherOverrideAttendance,
  bulkAttendanceOperation,
  validateCheckIn,
  checkConnectivity,
  retryRequest,
  batchCheckIn
} = attendanceService;

export default attendanceService;