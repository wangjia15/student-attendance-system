// API Service for Student Attendance System

import {
  ClassSessionCreate,
  ClassSessionResponse,
  QRCodeRegenerateResponse,
  VerificationCodeRegenerateResponse,
  ShareLinkResponse,
  LiveSessionStats,
  APIError
} from '../types/api';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

class APIService {
  private baseURL: string;

  constructor(baseURL: string = API_BASE_URL) {
    this.baseURL = baseURL;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    
    const defaultHeaders = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    const config: RequestInit = {
      ...options,
      headers: defaultHeaders,
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

  // Class Session Management
  async createClassSession(sessionData: ClassSessionCreate): Promise<ClassSessionResponse> {
    return this.request<ClassSessionResponse>('/api/v1/classes/create', {
      method: 'POST',
      body: JSON.stringify(sessionData),
    });
  }

  async getClassSession(classId: string): Promise<ClassSessionResponse> {
    return this.request<ClassSessionResponse>(`/api/v1/classes/${classId}`);
  }

  async updateClassSession(
    classId: string, 
    updates: Partial<ClassSessionCreate>
  ): Promise<ClassSessionResponse> {
    return this.request<ClassSessionResponse>(`/api/v1/classes/${classId}`, {
      method: 'PUT',
      body: JSON.stringify(updates),
    });
  }

  async endClassSession(classId: string): Promise<ClassSessionResponse> {
    return this.updateClassSession(classId, { status: 'ended' } as any);
  }

  // QR Code Management
  async regenerateQRCode(classId: string): Promise<QRCodeRegenerateResponse> {
    return this.request<QRCodeRegenerateResponse>(
      `/api/v1/classes/${classId}/qr-code/regenerate`,
      { method: 'POST' }
    );
  }

  // Verification Code Management
  async regenerateVerificationCode(classId: string): Promise<VerificationCodeRegenerateResponse> {
    return this.request<VerificationCodeRegenerateResponse>(
      `/api/v1/classes/${classId}/verification-code/regenerate`,
      { method: 'POST' }
    );
  }

  // Share Link Management
  async getShareLink(classId: string): Promise<ShareLinkResponse> {
    return this.request<ShareLinkResponse>(`/api/v1/classes/${classId}/share-link`);
  }

  // Session Statistics
  async getSessionStats(classId: string): Promise<LiveSessionStats> {
    return this.request<LiveSessionStats>(`/api/v1/classes/${classId}/stats`);
  }

  // WebSocket URL for live updates
  getWebSocketURL(classId: string, token: string): string {
    const wsProtocol = this.baseURL.startsWith('https') ? 'wss' : 'ws';
    const baseWsURL = this.baseURL.replace(/^https?/, wsProtocol);
    return `${baseWsURL}/api/v1/classes/${classId}/live-updates?token=${encodeURIComponent(token)}`;
  }
}

// Create and export singleton instance
const apiService = new APIService();

// Export individual methods for easier importing
export const createClassSession = (data: ClassSessionCreate) => 
  apiService.createClassSession(data);

export const getClassSession = (classId: string) => 
  apiService.getClassSession(classId);

export const updateClassSession = (classId: string, updates: Partial<ClassSessionCreate>) => 
  apiService.updateClassSession(classId, updates);

export const endClassSession = (classId: string) => 
  apiService.endClassSession(classId);

export const regenerateQRCode = (classId: string) => 
  apiService.regenerateQRCode(classId);

export const regenerateVerificationCode = (classId: string) => 
  apiService.regenerateVerificationCode(classId);

export const getShareLink = (classId: string) => 
  apiService.getShareLink(classId);

export const getSessionStats = (classId: string) => 
  apiService.getSessionStats(classId);

export const getWebSocketURL = (classId: string, token: string) => 
  apiService.getWebSocketURL(classId, token);

export default apiService;