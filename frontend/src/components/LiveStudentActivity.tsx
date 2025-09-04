/**
 * Live Student Activity Component
 * 
 * Displays real-time student join activity with visual indicators,
 * recent joins list, and attendance pattern monitoring.
 */

import React, { useState, useEffect } from 'react';
import { StudentJoinedData, AttendanceUpdateData } from '../services/websocket';
import { useRealtimeEvents, useActivityFeed, useLiveStats } from '../store/realtime';

export interface LiveStudentActivityProps {
  /** Class session ID to filter activity */
  classId: string;
  /** Maximum number of recent activities to show */
  maxActivities?: number;
  /** Show sound toggle control */
  showSoundControl?: boolean;
  /** Compact mode for smaller displays */
  compact?: boolean;
  /** Custom class name */
  className?: string;
}

const LiveStudentActivity: React.FC<LiveStudentActivityProps> = ({
  classId,
  maxActivities = 10,
  showSoundControl = true,
  compact = false,
  className = ''
}) => {
  const [highlightedActivity, setHighlightedActivity] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<'all' | 'joins' | 'updates'>('all');
  
  const events = useRealtimeEvents();
  const activityFeed = useActivityFeed();
  const liveStats = useLiveStats(classId);
  
  // Filter activities for this class
  const classActivities = activityFeed
    .filter(activity => activity.classId === classId || activity.classId === 'system')
    .filter(activity => {
      switch (filterType) {
        case 'joins':
          return activity.type === 'student_joined';
        case 'updates':
          return activity.type === 'attendance_update';
        default:
          return true;
      }
    })
    .slice(0, maxActivities);

  // Recent student joins
  const recentJoins = events.studentJoins.slice(0, 5);
  
  // Highlight new activity
  useEffect(() => {
    if (classActivities.length > 0) {
      const latestActivity = classActivities[0];
      setHighlightedActivity(latestActivity.id);
      
      // Remove highlight after animation
      const timeout = setTimeout(() => {
        setHighlightedActivity(null);
      }, 2000);
      
      return () => clearTimeout(timeout);
    }
  }, [classActivities.length]);
  
  const formatActivityText = (activity: any) => {
    switch (activity.type) {
      case 'student_joined':
        return `${activity.data.student_name} joined via ${activity.data.join_method}`;
      case 'attendance_update':
        return `Student attendance updated to ${activity.data.status}`;
      case 'session_update':
        return 'Session configuration updated';
      case 'system_notification':
        return activity.data.message;
      default:
        return 'Unknown activity';
    }
  };
  
  const getActivityIcon = (type: string) => {
    switch (type) {
      case 'student_joined':
        return '👋';
      case 'attendance_update':
        return '✏️';
      case 'session_update':
        return '⚙️';
      case 'system_notification':
        return '📢';
      default:
        return '📝';
    }
  };
  
  const getActivityColor = (type: string) => {
    switch (type) {
      case 'student_joined':
        return '#28a745';
      case 'attendance_update':
        return '#ffc107';
      case 'session_update':
        return '#17a2b8';
      case 'system_notification':
        return '#6c757d';
      default:
        return '#007bff';
    }
  };

  if (compact) {
    return (
      <div className={`live-activity-compact ${className}`}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '14px', fontWeight: '500' }}>
            Live Activity
          </span>
          {recentJoins.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span style={{ fontSize: '12px', color: '#666' }}>
                Recent joins:
              </span>
              <div style={{ display: 'flex', gap: '4px' }}>
                {recentJoins.slice(0, 3).map((join) => (
                  <span
                    key={join.id}
                    style={{
                      display: 'inline-block',
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      backgroundColor: '#28a745'
                    }}
                    title={`${join.student_name} joined at ${new Date(join.timestamp).toLocaleTimeString()}`}
                  />
                ))}
                {recentJoins.length > 3 && (
                  <span style={{ fontSize: '10px', color: '#666' }}>
                    +{recentJoins.length - 3}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`live-student-activity ${className}`}>
      {/* Header */}
      <div className="activity-header" style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center',
        marginBottom: '16px'
      }}>
        <h3 style={{ margin: 0, fontSize: '18px', color: '#333' }}>
          Live Activity
        </h3>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <select 
            value={filterType}
            onChange={(e) => setFilterType(e.target.value as any)}
            style={{
              padding: '4px 8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              fontSize: '12px'
            }}
          >
            <option value="all">All Activity</option>
            <option value="joins">Student Joins</option>
            <option value="updates">Attendance Updates</option>
          </select>
          {liveStats && (
            <span style={{ 
              fontSize: '12px', 
              color: '#666',
              padding: '4px 8px',
              backgroundColor: '#f8f9fa',
              borderRadius: '4px'
            }}>
              {liveStats.present_count + liveStats.late_count} / {liveStats.total_students} present
            </span>
          )}
        </div>
      </div>

      {/* Recent Joins Summary */}
      {recentJoins.length > 0 && (
        <div className="recent-joins" style={{
          padding: '12px',
          backgroundColor: '#d4edda',
          border: '1px solid #c3e6cb',
          borderRadius: '8px',
          marginBottom: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <span style={{ fontSize: '16px' }}>👋</span>
            <span style={{ fontSize: '14px', fontWeight: '500', color: '#155724' }}>
              Recent Joins ({recentJoins.length})
            </span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {recentJoins.map((join) => (
              <div
                key={join.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '4px 8px',
                  backgroundColor: 'white',
                  borderRadius: '12px',
                  fontSize: '12px',
                  border: '1px solid #c3e6cb'
                }}
              >
                <span>{join.student_name}</span>
                <span style={{ color: '#666' }}>
                  ({new Date(join.timestamp).toLocaleTimeString()})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activity Feed */}
      <div className="activity-feed">
        {classActivities.length > 0 ? (
          <div className="activity-list">
            {classActivities.map((activity) => (
              <div
                key={activity.id}
                className={`activity-item ${highlightedActivity === activity.id ? 'highlighted' : ''}`}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '12px',
                  padding: '12px',
                  backgroundColor: highlightedActivity === activity.id ? '#fff3cd' : '#f8f9fa',
                  border: `1px solid ${highlightedActivity === activity.id ? '#ffeaa7' : '#dee2e6'}`,
                  borderLeft: `4px solid ${getActivityColor(activity.type)}`,
                  borderRadius: '8px',
                  marginBottom: '8px',
                  transition: 'all 0.3s ease',
                  transform: highlightedActivity === activity.id ? 'translateX(4px)' : 'translateX(0)'
                }}
              >
                <span style={{ fontSize: '16px' }}>
                  {getActivityIcon(activity.type)}
                </span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '14px', marginBottom: '4px' }}>
                    {formatActivityText(activity)}
                  </div>
                  <div style={{ fontSize: '12px', color: '#666' }}>
                    {new Date(activity.timestamp).toLocaleString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="no-activity" style={{
            textAlign: 'center',
            padding: '40px 20px',
            color: '#666',
            backgroundColor: '#f8f9fa',
            borderRadius: '8px'
          }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>😴</div>
            <div style={{ fontSize: '16px', marginBottom: '8px' }}>No recent activity</div>
            <div style={{ fontSize: '14px' }}>
              Student joins and attendance updates will appear here in real-time
            </div>
          </div>
        )}
      </div>

      {/* Live Statistics */}
      {liveStats && (
        <div className="live-stats" style={{
          marginTop: '16px',
          padding: '12px',
          backgroundColor: 'white',
          border: '1px solid #dee2e6',
          borderRadius: '8px'
        }}>
          <div style={{ 
            fontSize: '12px', 
            fontWeight: '500', 
            marginBottom: '8px',
            color: '#666',
            textTransform: 'uppercase'
          }}>
            Live Statistics
          </div>
          <div style={{ 
            display: 'grid', 
            gridTemplateColumns: 'repeat(auto-fit, minmax(80px, 1fr))', 
            gap: '12px',
            fontSize: '12px'
          }}>
            <div>
              <div style={{ fontWeight: '600', color: '#28a745' }}>
                {liveStats.present_count}
              </div>
              <div style={{ color: '#666' }}>Present</div>
            </div>
            <div>
              <div style={{ fontWeight: '600', color: '#ffc107' }}>
                {liveStats.late_count}
              </div>
              <div style={{ color: '#666' }}>Late</div>
            </div>
            <div>
              <div style={{ fontWeight: '600', color: '#dc3545' }}>
                {liveStats.absent_count}
              </div>
              <div style={{ color: '#666' }}>Absent</div>
            </div>
            <div>
              <div style={{ fontWeight: '600', color: '#007bff' }}>
                {Math.round(liveStats.attendance_rate * 100)}%
              </div>
              <div style={{ color: '#666' }}>Rate</div>
            </div>
          </div>
          <div style={{ 
            fontSize: '10px', 
            color: '#999', 
            marginTop: '8px',
            textAlign: 'right'
          }}>
            Updated: {new Date(liveStats.updated_at).toLocaleTimeString()}
          </div>
        </div>
      )}

      <style jsx>{`
        .activity-item.highlighted {
          animation: pulse 0.5s ease-in-out;
        }
        
        @keyframes pulse {
          0% { 
            transform: translateX(0) scale(1);
          }
          50% { 
            transform: translateX(4px) scale(1.02);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
          }
          100% { 
            transform: translateX(0) scale(1);
          }
        }
      `}</style>
    </div>
  );
};

export default LiveStudentActivity;