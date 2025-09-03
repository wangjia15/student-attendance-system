// Real-time service for processing WebSocket data and managing live updates

import { 
  StudentJoinedMessage, 
  SessionUpdatedMessage, 
  StatsUpdateMessage,
  LiveSessionStats,
  StudentJoin 
} from '../types/api';

export interface StudentJoinEvent {
  id: string;
  studentId: string;
  studentName: string;
  joinedAt: Date;
  joinMethod: string;
  isRecent: boolean;
}

export interface SessionMetrics {
  totalJoins: number;
  uniqueStudents: number;
  joinsPerMinute: number;
  participationRate?: number;
  averageJoinTime: number;
  peakJoinTime: string;
}

export interface RealtimeState {
  isActive: boolean;
  studentJoins: StudentJoinEvent[];
  sessionMetrics: SessionMetrics;
  lastUpdate: Date | null;
  notifications: NotificationEvent[];
}

export interface NotificationEvent {
  id: string;
  type: 'student_join' | 'session_update' | 'milestone' | 'warning';
  title: string;
  message: string;
  timestamp: Date;
  priority: 'low' | 'medium' | 'high';
  autoHide?: boolean;
  action?: {
    label: string;
    handler: () => void;
  };
}

export class RealtimeService {
  private listeners: Set<(state: RealtimeState) => void> = new Set();
  private state: RealtimeState = {
    isActive: false,
    studentJoins: [],
    sessionMetrics: {
      totalJoins: 0,
      uniqueStudents: 0,
      joinsPerMinute: 0,
      averageJoinTime: 0,
      peakJoinTime: ''
    },
    lastUpdate: null,
    notifications: []
  };

  // Subscribe to state changes
  subscribe(listener: (state: RealtimeState) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  // Emit state changes to all listeners
  private emit(): void {
    this.listeners.forEach(listener => {
      try {
        listener({ ...this.state });
      } catch (error) {
        console.error('Error in realtime listener:', error);
      }
    });
  }

  // Initialize service for a session
  initialize(initialStats?: LiveSessionStats): void {
    this.state = {
      isActive: true,
      studentJoins: [],
      sessionMetrics: {
        totalJoins: initialStats?.total_joins || 0,
        uniqueStudents: initialStats?.unique_students || 0,
        joinsPerMinute: 0,
        averageJoinTime: 0,
        peakJoinTime: '',
        participationRate: initialStats?.participation_rate
      },
      lastUpdate: new Date(),
      notifications: []
    };

    this.addNotification({
      type: 'session_update',
      title: 'Live Monitoring Active',
      message: 'Real-time attendance tracking is now active',
      priority: 'low',
      autoHide: true
    });

    this.emit();
  }

  // Process student join event
  processStudentJoin(message: StudentJoinedMessage): void {
    const joinEvent: StudentJoinEvent = {
      id: `${message.data.student_id}-${Date.now()}`,
      studentId: message.data.student_id,
      studentName: message.data.student_name,
      joinedAt: new Date(message.data.joined_at),
      joinMethod: message.data.join_method,
      isRecent: true
    };

    // Add to joins list (keep last 50 for performance)
    const updatedJoins = [joinEvent, ...this.state.studentJoins].slice(0, 50);
    
    // Mark older joins as not recent
    updatedJoins.forEach((join, index) => {
      join.isRecent = index === 0;
    });

    // Update metrics
    const metrics = this.calculateMetrics(updatedJoins);

    // Check for milestones
    this.checkMilestones(metrics);

    this.state = {
      ...this.state,
      studentJoins: updatedJoins,
      sessionMetrics: metrics,
      lastUpdate: new Date()
    };

    // Add join notification
    this.addNotification({
      type: 'student_join',
      title: 'Student Joined',
      message: `${message.data.student_name} joined via ${message.data.join_method.replace('_', ' ')}`,
      priority: 'medium',
      autoHide: true
    });

    this.emit();
  }

  // Process session update event
  processSessionUpdate(message: SessionUpdatedMessage): void {
    let notificationMessage = 'Session has been updated';
    
    if (message.data.qr_code_regenerated) {
      notificationMessage = 'QR code has been regenerated for security';
    } else if (message.data.verification_code_regenerated) {
      notificationMessage = 'Verification code has been regenerated';
    }

    this.addNotification({
      type: 'session_update',
      title: 'Session Updated',
      message: notificationMessage,
      priority: 'medium',
      autoHide: true
    });

    this.state = {
      ...this.state,
      lastUpdate: new Date()
    };

    this.emit();
  }

  // Process stats update
  processStatsUpdate(message: StatsUpdateMessage): void {
    const stats = message.data;
    
    this.state = {
      ...this.state,
      sessionMetrics: {
        ...this.state.sessionMetrics,
        totalJoins: stats.total_joins,
        uniqueStudents: stats.unique_students,
        participationRate: stats.participation_rate
      },
      lastUpdate: new Date()
    };

    this.emit();
  }

  // Calculate real-time metrics
  private calculateMetrics(joins: StudentJoinEvent[]): SessionMetrics {
    if (joins.length === 0) {
      return {
        totalJoins: 0,
        uniqueStudents: 0,
        joinsPerMinute: 0,
        averageJoinTime: 0,
        peakJoinTime: ''
      };
    }

    const uniqueStudentIds = new Set(joins.map(j => j.studentId));
    const now = new Date();
    const oneMinuteAgo = new Date(now.getTime() - 60000);
    
    // Joins in last minute
    const recentJoins = joins.filter(j => j.joinedAt >= oneMinuteAgo);
    
    // Calculate average join time (seconds between joins)
    let totalTimeBetweenJoins = 0;
    for (let i = 1; i < joins.length; i++) {
      const timeDiff = joins[i-1].joinedAt.getTime() - joins[i].joinedAt.getTime();
      totalTimeBetweenJoins += Math.abs(timeDiff);
    }
    const averageJoinTime = joins.length > 1 ? 
      totalTimeBetweenJoins / (joins.length - 1) / 1000 : 0;

    // Find peak join time (minute with most joins)
    const joinsByMinute: { [key: string]: number } = {};
    joins.forEach(join => {
      const minute = join.joinedAt.toISOString().slice(0, 16); // YYYY-MM-DDTHH:MM
      joinsByMinute[minute] = (joinsByMinute[minute] || 0) + 1;
    });
    
    const peakJoinTime = Object.entries(joinsByMinute)
      .sort(([,a], [,b]) => b - a)[0]?.[0] || '';

    return {
      totalJoins: joins.length,
      uniqueStudents: uniqueStudentIds.size,
      joinsPerMinute: recentJoins.length,
      averageJoinTime,
      peakJoinTime: peakJoinTime ? new Date(peakJoinTime + ':00').toLocaleTimeString() : '',
      participationRate: this.state.sessionMetrics.participationRate
    };
  }

  // Check for milestone achievements
  private checkMilestones(metrics: SessionMetrics): void {
    const milestones = [10, 25, 50, 75, 100, 150, 200];
    const currentJoins = metrics.totalJoins;
    const previousJoins = this.state.sessionMetrics.totalJoins;

    for (const milestone of milestones) {
      if (currentJoins >= milestone && previousJoins < milestone) {
        this.addNotification({
          type: 'milestone',
          title: 'Milestone Reached! 🎉',
          message: `${milestone} students have joined the session`,
          priority: 'high',
          autoHide: false,
          action: {
            label: 'View Details',
            handler: () => {
              console.log('Show detailed stats');
            }
          }
        });
        break; // Only show one milestone at a time
      }
    }

    // Check for high participation rate
    if (metrics.participationRate && metrics.participationRate >= 90 && 
        (!this.state.sessionMetrics.participationRate || 
         this.state.sessionMetrics.participationRate < 90)) {
      this.addNotification({
        type: 'milestone',
        title: 'Excellent Participation! ⭐',
        message: '90%+ of expected students have joined',
        priority: 'high',
        autoHide: false
      });
    }
  }

  // Add notification
  private addNotification(notification: Omit<NotificationEvent, 'id' | 'timestamp'>): void {
    const newNotification: NotificationEvent = {
      id: `notification-${Date.now()}-${Math.random()}`,
      timestamp: new Date(),
      ...notification
    };

    // Limit to 10 notifications
    const updatedNotifications = [newNotification, ...this.state.notifications].slice(0, 10);

    // Auto-hide notifications after 5 seconds
    if (notification.autoHide) {
      setTimeout(() => {
        this.removeNotification(newNotification.id);
      }, 5000);
    }

    this.state = {
      ...this.state,
      notifications: updatedNotifications
    };
  }

  // Remove notification
  removeNotification(id: string): void {
    this.state = {
      ...this.state,
      notifications: this.state.notifications.filter(n => n.id !== id)
    };
    this.emit();
  }

  // Clear all notifications
  clearNotifications(): void {
    this.state = {
      ...this.state,
      notifications: []
    };
    this.emit();
  }

  // Get current state
  getState(): RealtimeState {
    return { ...this.state };
  }

  // Cleanup when session ends
  cleanup(): void {
    this.state = {
      isActive: false,
      studentJoins: [],
      sessionMetrics: {
        totalJoins: 0,
        uniqueStudents: 0,
        joinsPerMinute: 0,
        averageJoinTime: 0,
        peakJoinTime: ''
      },
      lastUpdate: null,
      notifications: []
    };

    this.listeners.clear();
  }
}

// Export singleton instance
export const realtimeService = new RealtimeService();