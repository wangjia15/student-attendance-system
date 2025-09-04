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
  APIError
} from '../types/api';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Authentication token management
let authToken: string | null = localStorage.getItem('access_token');

export const setAuthToken = (token: string | null) => {
  authToken = token;
  if (token) {
    localStorage.setItem('access_token', token);
  } else {
    localStorage.removeItem('access_token');
  }
};

export const getAuthToken = () => authToken;

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

  // Share Link Management
  async getShareLink(sessionId: number): Promise<ShareLinkResponse> {
    return this.request<ShareLinkResponse>(`/api/v1/classes/${sessionId}/share-link`);
  }

  // Student Attendance Methods
  async joinClassWithQR(joinData: StudentJoinRequest): Promise<StudentJoinResponse> {
    return this.request<StudentJoinResponse>('/api/v1/attendance/join/qr', {
      method: 'POST',
      body: JSON.stringify(joinData),
    });
  }

  async joinClassWithCode(joinData: VerificationCodeJoinRequest): Promise<StudentJoinResponse> {
    return this.request<StudentJoinResponse>('/api/v1/attendance/join/code', {
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

  async checkoutFromClass(sessionId: number): Promise<any> {
    return this.request(`/api/v1/attendance/checkout/${sessionId}`, {
      method: 'POST',
    });
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

// Export individual methods for easier importing
export const {
  login,
  register,
  logout,
  createClassSession,
  getClassSessions,
  getClassSession,
  updateClassSession,
  endClassSession,
  regenerateQRCode,
  getShareLink,
  joinClassWithQR,
  joinClassWithCode,
  getMyAttendance,
  checkoutFromClass,
  getWebSocketURL
} = apiService;

export default apiService;