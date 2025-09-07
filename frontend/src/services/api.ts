// API Service for Student Attendance System

import {
  ClassSessionCreate,
  ClassSessionResponse,
  QRCodeResponse,
  ShareLinkResponse,
  LoginRequest,
  RegisterRequest,
  Token,
  UserResponse,
  StudentJoinRequest,
  VerificationCodeJoinRequest,
  StudentJoinResponse,
  AttendanceResponse,
  APIError,
  SystemStats,
  User,
  AdminClassSession
} from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Import auth service for unified token management
import { authService } from './auth';

export const setAuthToken = (token: string | null) => {
  if (token) {
    authService.setToken(token);
  } else {
    authService.removeToken();
  }
};

export const getAuthToken = () => authService.getToken();

class APIService {
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
    const token = getAuthToken();
    if (requireAuth && token) {
      defaultHeaders.Authorization = `Bearer ${token}`;
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
        let errorData: APIError;
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

  // Authentication methods
  async login(credentials: LoginRequest): Promise<Token> {
    const token = await this.request<Token>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    }, false);
    
    setAuthToken(token.access_token);
    return token;
  }
  
  async register(userData: RegisterRequest): Promise<UserResponse> {
    return this.request<UserResponse>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    }, false);
  }
  
  async logout(): Promise<void> {
    setAuthToken(null);
  }

  // Class Session Management
  async createClassSession(sessionData: ClassSessionCreate): Promise<ClassSessionResponse> {
    return this.request<ClassSessionResponse>('/api/v1/classes/create', {
      method: 'POST',
      body: JSON.stringify(sessionData),
    });
  }

  async getClassSessions(statusFilter?: string, limit = 50, offset = 0): Promise<ClassSessionResponse[]> {
    const params = new URLSearchParams();
    if (statusFilter) params.append('status_filter', statusFilter);
    params.append('limit', limit.toString());
    params.append('offset', offset.toString());
    
    return this.request<ClassSessionResponse[]>(`/api/v1/classes/?${params.toString()}`);
  }

  async getClassSession(sessionId: number): Promise<ClassSessionResponse> {
    return this.request<ClassSessionResponse>(`/api/v1/classes/${sessionId}`);
  }

  async updateClassSession(sessionId: number, updateData: Partial<ClassSessionCreate>): Promise<ClassSessionResponse> {
    return this.request<ClassSessionResponse>(`/api/v1/classes/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify(updateData),
    });
  }

  async endClassSession(sessionId: number): Promise<any> {
    return this.request(`/api/v1/classes/${sessionId}/end`, {
      method: 'POST',
    });
  }

  // QR Code Management
  async regenerateQRCode(sessionId: number): Promise<QRCodeResponse> {
    return this.request<QRCodeResponse>(`/api/v1/classes/${sessionId}/regenerate-qr`, {
      method: 'POST',
    });
  }

  // Verification Code Management
  async regenerateVerificationCode(sessionId: number): Promise<{ verification_code: string; share_link: string }> {
    return this.request<{ verification_code: string; share_link: string }>(`/api/v1/classes/${sessionId}/regenerate-code`, {
      method: 'POST',
    });
  }

  // Share Link Management
  async getShareLink(sessionId: number): Promise<ShareLinkResponse> {
    return this.request<ShareLinkResponse>(`/api/v1/classes/${sessionId}/share-link`);
  }

  // Class Members Management
  async getClassMembers(sessionId: number): Promise<UserResponse[]> {
    return this.request<UserResponse[]>(`/api/v1/classes/${sessionId}/members`);
  }

  async getClassEnrollmentStats(sessionId: number): Promise<any> {
    return this.request<any>(`/api/v1/classes/${sessionId}/enrollment-stats`);
  }

  // Student Attendance Methods
  async joinClassWithQR(joinData: StudentJoinRequest): Promise<StudentJoinResponse> {
    return this.request<StudentJoinResponse>('/api/v1/attendance/check-in/qr', {
      method: 'POST',
      body: JSON.stringify(joinData),
    });
  }

  async joinClassWithCode(joinData: VerificationCodeJoinRequest): Promise<StudentJoinResponse> {
    return this.request<StudentJoinResponse>('/api/v1/attendance/check-in/code', {
      method: 'POST',
      body: JSON.stringify(joinData),
    });
  }

  async getMyAttendance(limit = 50, offset = 0): Promise<AttendanceResponse[]> {
    const params = new URLSearchParams();
    params.append('limit', limit.toString());
    params.append('offset', offset.toString());
    
    return this.request<AttendanceResponse[]>(`/api/v1/attendance/my-attendance?${params.toString()}`);
  }

  async getMyEnrolledClasses(statusFilter?: string, limit = 50, offset = 0): Promise<any[]> {
    // Use the working my-attendance endpoint and process the data to extract unique classes
    const attendanceRecords = await this.request<AttendanceResponse[]>('/api/v1/attendance/my-attendance?limit=200');
    
    // Group attendance records by class session and extract unique classes
    const classMap = new Map();
    
    for (const record of attendanceRecords) {
      const classKey = record.class_session_id;
      if (!classMap.has(classKey)) {
        classMap.set(classKey, {
          id: record.class_session_id,
          name: record.class_name,
          subject: record.subject,
          teacher_name: record.teacher_name,
          status: 'active', // We don't have this info from attendance records, assume active
          last_attendance_status: record.status,
          last_check_in_time: record.check_in_time,
          created_at: record.created_at
        });
      } else {
        // Update with the latest attendance info if this record is newer
        const existing = classMap.get(classKey);
        if (new Date(record.created_at) > new Date(existing.created_at)) {
          existing.last_attendance_status = record.status;
          existing.last_check_in_time = record.check_in_time;
          existing.created_at = record.created_at;
        }
      }
    }
    
    // Convert map to array and apply filtering/pagination
    let classes = Array.from(classMap.values());
    
    if (statusFilter) {
      classes = classes.filter(cls => cls.status === statusFilter);
    }
    
    // Sort by most recent attendance
    classes.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    
    // Apply pagination
    return classes.slice(offset, offset + limit);
  }

  async getActiveSessionsForStudent(): Promise<any[]> {
    return this.request<any[]>('/api/v1/attendance/active-sessions');
  }

  async checkoutFromClass(sessionId: number): Promise<any> {
    return this.request(`/api/v1/attendance/checkout/${sessionId}`, {
      method: 'POST',
    });
  }

  // Admin Methods
  async getSystemStats(): Promise<SystemStats> {
    return this.request<SystemStats>('/api/v1/admin/stats');
  }

  async getRecentUsers(limit = 10): Promise<User[]> {
    return this.request<User[]>(`/api/v1/admin/recent-users?limit=${limit}`);
  }

  async getActiveClassesAdmin(limit = 10): Promise<AdminClassSession[]> {
    return this.request<AdminClassSession[]>(`/api/v1/admin/active-classes?limit=${limit}`);
  }

  async getAllUsers(role?: string, isActive?: boolean, limit = 50, offset = 0): Promise<User[]> {
    const params = new URLSearchParams();
    if (role) params.append('role', role);
    if (isActive !== undefined) params.append('is_active', isActive.toString());
    params.append('limit', limit.toString());
    params.append('offset', offset.toString());
    
    return this.request<User[]>(`/api/v1/admin/all-users?${params.toString()}`);
  }

  async getAllClassesAdmin(statusFilter?: string, limit = 50, offset = 0): Promise<AdminClassSession[]> {
    const params = new URLSearchParams();
    if (statusFilter) params.append('status_filter', statusFilter);
    params.append('limit', limit.toString());
    params.append('offset', offset.toString());
    
    return this.request<AdminClassSession[]>(`/api/v1/admin/all-classes?${params.toString()}`);
  }

  // User Management Methods
  async createUser(userData: any): Promise<any> {
    return this.request('/api/v1/admin/users', {
      method: 'POST',
      body: JSON.stringify(userData),
    });
  }

  async updateUser(userId: number, userData: any): Promise<any> {
    return this.request(`/api/v1/admin/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify(userData),
    });
  }

  async toggleUserStatus(userId: number): Promise<any> {
    return this.request(`/api/v1/admin/users/${userId}/toggle-status`, {
      method: 'PATCH',
    });
  }

  async searchUsers(query: string = '', role?: string, isActive?: boolean, limit = 50, offset = 0): Promise<User[]> {
    const params = new URLSearchParams();
    if (query) params.append('q', query);
    if (role) params.append('role', role);
    if (isActive !== undefined) params.append('is_active', isActive.toString());
    params.append('limit', limit.toString());
    params.append('offset', offset.toString());
    
    return this.request<User[]>(`/api/v1/admin/users/search?${params.toString()}`);
  }

  async exportUsers(format = 'csv', role?: string, isActive?: boolean): Promise<any> {
    const params = new URLSearchParams();
    params.append('format', format);
    if (role) params.append('role', role);
    if (isActive !== undefined) params.append('is_active', isActive.toString());
    
    const url = `${this.baseURL}/api/v1/admin/users/export?${params.toString()}`;
    const token = getAuthToken();
    
    // For CSV export, we need to handle file download
    if (format.toLowerCase() === 'csv') {
      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      
      if (response.ok) {
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `users_export_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(downloadUrl);
        return { success: true, message: 'Export downloaded successfully' };
      } else {
        throw new Error('Export failed');
      }
    } else {
      return this.request(`/api/v1/admin/users/export?${params.toString()}`);
    }
  }

  async exportClasses(format = 'csv', statusFilter?: string): Promise<any> {
    const params = new URLSearchParams();
    if (statusFilter) params.append('status_filter', statusFilter);
    params.append('format', format);
    
    const url = `${this.baseURL}/api/v1/admin/classes/export?${params.toString()}`;
    const token = getAuthToken();
    
    // For CSV export, we need to handle file download
    if (format.toLowerCase() === 'csv') {
      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      
      if (response.ok) {
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = `classes_export_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(downloadUrl);
        return { success: true, message: 'Export downloaded successfully' };
      } else {
        throw new Error('Export failed');
      }
    } else {
      return this.request(`/api/v1/admin/classes/export?${params.toString()}`);
    }
  }

  // WebSocket URL for live updates
  getWebSocketURL(classId: number): string {
    const wsProtocol = this.baseURL.startsWith('https') ? 'wss' : 'ws';
    const baseWsURL = this.baseURL.replace(/^https?/, wsProtocol);
    return `${baseWsURL}/ws/${classId}`;
  }
}

// Create and export singleton instance
const apiService = new APIService();

// Export individual methods for easier importing (preserving 'this' context)
export const login = (credentials: LoginRequest) => apiService.login(credentials);
export const register = (userData: RegisterRequest) => apiService.register(userData);
export const logout = () => apiService.logout();
export const createClassSession = (sessionData: ClassSessionCreate) => apiService.createClassSession(sessionData);
export const getClassSessions = () => apiService.getClassSessions();
export const getClassSession = (sessionId: number) => apiService.getClassSession(sessionId);
export const getClassMembers = (sessionId: number) => apiService.getClassMembers(sessionId);
export const getClassEnrollmentStats = (sessionId: number) => apiService.getClassEnrollmentStats(sessionId);
export const updateClassSession = (sessionId: number, updates: Partial<ClassSessionCreate>) => apiService.updateClassSession(sessionId, updates);
export const endClassSession = (sessionId: number) => apiService.endClassSession(sessionId);
export const regenerateQRCode = (sessionId: number) => apiService.regenerateQRCode(sessionId);
export const regenerateVerificationCode = (sessionId: number) => apiService.regenerateVerificationCode(sessionId);
export const getShareLink = (sessionId: number) => apiService.getShareLink(sessionId);
export const joinClassWithQR = (joinData: StudentJoinRequest) => apiService.joinClassWithQR(joinData);
export const joinClassWithCode = (joinData: VerificationCodeJoinRequest) => apiService.joinClassWithCode(joinData);
export const getMyAttendance = () => apiService.getMyAttendance();
export const checkoutFromClass = (sessionId: number) => apiService.checkoutFromClass(sessionId);
export const getWebSocketURL = (classId: number) => apiService.getWebSocketURL(classId);

// Student Dashboard aliases
export const checkInWithCode = (code: string) => 
  apiService.joinClassWithCode({ verification_code: code });
export const checkInWithQR = (token: string) => 
  apiService.joinClassWithQR({ jwt_token: token });

// Student Classes and Active Sessions
export const getMyEnrolledClasses = (statusFilter?: string, limit?: number, offset?: number) => 
  apiService.getMyEnrolledClasses(statusFilter, limit, offset);
export const getActiveSessionsForStudent = () => apiService.getActiveSessionsForStudent();

// Admin Dashboard methods
export const getSystemStats = () => apiService.getSystemStats();
export const getRecentUsers = (limit?: number) => apiService.getRecentUsers(limit);
export const getActiveClassesAdmin = (limit?: number) => apiService.getActiveClassesAdmin(limit);
export const getAllUsers = (role?: string, isActive?: boolean, limit?: number, offset?: number) => 
  apiService.getAllUsers(role, isActive, limit, offset);
export const getAllClassesAdmin = (statusFilter?: string, limit?: number, offset?: number) => 
  apiService.getAllClassesAdmin(statusFilter, limit, offset);

// User management methods
export const createUser = (userData: any) => apiService.createUser(userData);
export const updateUser = (userId: number, userData: any) => apiService.updateUser(userId, userData);
export const toggleUserStatus = (userId: number) => apiService.toggleUserStatus(userId);
export const searchUsers = (query: string, role?: string, isActive?: boolean, limit?: number, offset?: number) => 
  apiService.searchUsers(query, role, isActive, limit, offset);
export const exportUsers = (format?: string, role?: string, isActive?: boolean) => 
  apiService.exportUsers(format, role, isActive);
export const exportClasses = (format?: string, statusFilter?: string) => 
  apiService.exportClasses(format, statusFilter);

export default apiService;