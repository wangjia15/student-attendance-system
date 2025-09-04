import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { AttendanceAlert } from '../types/attendance';
import attendanceService from '../services/attendance';

interface AttendancePatternData {
  student_id: number;
  student_name: string;
  total_sessions: number;
  present_count: number;
  late_count: number;
  absent_count: number;
  excused_count: number;
  consecutive_absences: number;
  attendance_rate: number;
  late_rate: number;
  risk_level: 'low' | 'medium' | 'high';
  trends: {
    attendance_trend: 'improving' | 'declining' | 'stable';
    punctuality_trend: 'improving' | 'declining' | 'stable';
  };
}

interface PatternVisualizationProps {
  data: AttendancePatternData;
}

const PatternVisualization: React.FC<PatternVisualizationProps> = ({ data }) => {
  const chartWidth = 200;
  const chartHeight = 100;
  
  // Create simple bar chart data
  const categories = [
    { label: 'Present', value: data.present_count, color: '#28a745' },
    { label: 'Late', value: data.late_count, color: '#ffc107' },
    { label: 'Absent', value: data.absent_count, color: '#dc3545' },
    { label: 'Excused', value: data.excused_count, color: '#17a2b8' }
  ];
  
  const maxValue = Math.max(...categories.map(c => c.value), 1);
  const barWidth = chartWidth / categories.length - 10;
  
  return (
    <div className="pattern-visualization">
      <div className="chart-container">
        <svg width={chartWidth} height={chartHeight}>
          {categories.map((category, index) => {
            const barHeight = (category.value / maxValue) * (chartHeight - 30);
            const x = index * (barWidth + 10) + 5;
            const y = chartHeight - barHeight - 20;
            
            return (
              <g key={category.label}>
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={barHeight}
                  fill={category.color}
                  rx={2}
                />
                <text
                  x={x + barWidth / 2}
                  y={chartHeight - 5}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#666"
                >
                  {category.label[0]}
                </text>
                <text
                  x={x + barWidth / 2}
                  y={y - 5}
                  textAnchor="middle"
                  fontSize="12"
                  fontWeight="bold"
                  fill="#333"
                >
                  {category.value}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      
      <div className="pattern-metrics">
        <div className="metric">
          <span className="metric-label">Attendance Rate</span>
          <span className={`metric-value rate-${data.attendance_rate >= 0.9 ? 'high' : data.attendance_rate >= 0.75 ? 'medium' : 'low'}`}>
            {Math.round(data.attendance_rate * 100)}%
          </span>
        </div>
        <div className="metric">
          <span className="metric-label">Late Rate</span>
          <span className={`metric-value rate-${data.late_rate <= 0.1 ? 'high' : data.late_rate <= 0.25 ? 'medium' : 'low'}`}>
            {Math.round(data.late_rate * 100)}%
          </span>
        </div>
      </div>
      
      <div className="trend-indicators">
        <div className={`trend attendance-${data.trends.attendance_trend}`}>
          <span className="trend-icon">
            {data.trends.attendance_trend === 'improving' ? '↗️' : 
             data.trends.attendance_trend === 'declining' ? '↘️' : '➡️'}
          </span>
          <span className="trend-label">Attendance {data.trends.attendance_trend}</span>
        </div>
        <div className={`trend punctuality-${data.trends.punctuality_trend}`}>
          <span className="trend-icon">
            {data.trends.punctuality_trend === 'improving' ? '↗️' : 
             data.trends.punctuality_trend === 'declining' ? '↘️' : '➡️'}
          </span>
          <span className="trend-label">Punctuality {data.trends.punctuality_trend}</span>
        </div>
      </div>
    </div>
  );
};

interface AttendancePatternsProps {
  classSessionId: number;
  alerts: AttendanceAlert[];
  onClose: () => void;
  maxStudentsToAnalyze?: number;
}

const AttendancePatterns: React.FC<AttendancePatternsProps> = ({
  classSessionId,
  alerts,
  onClose,
  maxStudentsToAnalyze = 50
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [patternData, setPatternData] = useState<AttendancePatternData[]>([]);
  const [selectedStudent, setSelectedStudent] = useState<number | null>(null);
  const [filterRisk, setFilterRisk] = useState<'all' | 'high' | 'medium' | 'low'>('all');
  const [sortBy, setSortBy] = useState<'name' | 'attendance_rate' | 'risk' | 'consecutive_absences'>('risk');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [showOnlyAlerts, setShowOnlyAlerts] = useState(false);

  // Load pattern data
  const loadPatternData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // First get the class report to get all students
      const classReport = await attendanceService.getClassAttendanceReport(classSessionId, true);
      
      // Extract unique student IDs from the report
      const studentIds = [...new Set(classReport.records.map(r => r.id))];
      
      // Limit the number of students to analyze for performance
      const limitedStudentIds = studentIds.slice(0, maxStudentsToAnalyze);
      
      // Generate pattern data for each student (mock data for now)
      const patterns: AttendancePatternData[] = classReport.records
        .filter(record => limitedStudentIds.includes(record.id))
        .map(record => {
          // Mock pattern analysis - in real app this would come from analytics API
          const totalSessions = Math.floor(Math.random() * 20) + 10;
          const presentCount = Math.floor(Math.random() * totalSessions * 0.8) + Math.floor(totalSessions * 0.1);
          const lateCount = Math.floor(Math.random() * (totalSessions - presentCount) * 0.5);
          const absentCount = Math.floor(Math.random() * (totalSessions - presentCount - lateCount));
          const excusedCount = totalSessions - presentCount - lateCount - absentCount;
          
          const attendanceRate = (presentCount + lateCount) / totalSessions;
          const lateRate = lateCount / (presentCount + lateCount || 1);
          const consecutiveAbsences = Math.floor(Math.random() * 5);
          
          let riskLevel: 'low' | 'medium' | 'high' = 'low';
          if (attendanceRate < 0.6 || consecutiveAbsences >= 4) riskLevel = 'high';
          else if (attendanceRate < 0.8 || consecutiveAbsences >= 2) riskLevel = 'medium';
          
          return {
            student_id: record.id,
            student_name: record.student_name || 'Unknown Student',
            total_sessions: totalSessions,
            present_count: presentCount,
            late_count: lateCount,
            absent_count: absentCount,
            excused_count: excusedCount,
            consecutive_absences: consecutiveAbsences,
            attendance_rate: attendanceRate,
            late_rate: lateRate,
            risk_level: riskLevel,
            trends: {
              attendance_trend: Math.random() > 0.5 ? 'improving' : Math.random() > 0.5 ? 'declining' : 'stable',
              punctuality_trend: Math.random() > 0.5 ? 'improving' : Math.random() > 0.5 ? 'declining' : 'stable'
            }
          };
        });

      setPatternData(patterns);
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to load pattern data');
    } finally {
      setLoading(false);
    }
  }, [classSessionId, maxStudentsToAnalyze]);

  useEffect(() => {
    loadPatternData();
  }, [loadPatternData]);

  // Filter and sort pattern data
  const filteredAndSortedData = useMemo(() => {
    let filtered = patternData;
    
    // Filter by risk level
    if (filterRisk !== 'all') {
      filtered = filtered.filter(data => data.risk_level === filterRisk);
    }
    
    // Filter by alerts if enabled
    if (showOnlyAlerts) {
      const alertStudentIds = new Set(alerts.map(alert => alert.student_id));
      filtered = filtered.filter(data => alertStudentIds.has(data.student_id));
    }
    
    // Sort
    filtered.sort((a, b) => {
      let comparison = 0;
      
      switch (sortBy) {
        case 'name':
          comparison = a.student_name.localeCompare(b.student_name);
          break;
        case 'attendance_rate':
          comparison = a.attendance_rate - b.attendance_rate;
          break;
        case 'risk':
          const riskOrder = { 'high': 3, 'medium': 2, 'low': 1 };
          comparison = riskOrder[a.risk_level] - riskOrder[b.risk_level];
          break;
        case 'consecutive_absences':
          comparison = a.consecutive_absences - b.consecutive_absences;
          break;
      }
      
      return sortOrder === 'asc' ? comparison : -comparison;
    });
    
    return filtered;
  }, [patternData, filterRisk, showOnlyAlerts, alerts, sortBy, sortOrder]);

  // Get student alerts
  const getStudentAlerts = useCallback((studentId: number) => {
    return alerts.filter(alert => alert.student_id === studentId);
  }, [alerts]);

  // Calculate summary statistics
  const summaryStats = useMemo(() => {
    if (patternData.length === 0) return null;
    
    const highRiskCount = patternData.filter(d => d.risk_level === 'high').length;
    const mediumRiskCount = patternData.filter(d => d.risk_level === 'medium').length;
    const lowRiskCount = patternData.filter(d => d.risk_level === 'low').length;
    const avgAttendanceRate = patternData.reduce((sum, d) => sum + d.attendance_rate, 0) / patternData.length;
    const avgLateRate = patternData.reduce((sum, d) => sum + d.late_rate, 0) / patternData.length;
    
    return {
      total_students: patternData.length,
      high_risk_count: highRiskCount,
      medium_risk_count: mediumRiskCount,
      low_risk_count: lowRiskCount,
      avg_attendance_rate: avgAttendanceRate,
      avg_late_rate: avgLateRate
    };
  }, [patternData]);

  if (loading) {
    return (
      <div className="modal-overlay">
        <div className="modal-content loading">
          <div className="loading-spinner">
            <div className="spinner"></div>
            <p>Analyzing attendance patterns...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-content patterns-modal">
        <div className="modal-header">
          <h2>Attendance Patterns & Analytics</h2>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {error && (
            <div className="alert alert-error">
              {error}
            </div>
          )}

          {/* Summary Statistics */}
          {summaryStats && (
            <div className="summary-stats">
              <div className="stat-card">
                <h4>Students Analyzed</h4>
                <div className="stat-value">{summaryStats.total_students}</div>
              </div>
              <div className="stat-card risk-high">
                <h4>High Risk</h4>
                <div className="stat-value">{summaryStats.high_risk_count}</div>
              </div>
              <div className="stat-card risk-medium">
                <h4>Medium Risk</h4>
                <div className="stat-value">{summaryStats.medium_risk_count}</div>
              </div>
              <div className="stat-card risk-low">
                <h4>Low Risk</h4>
                <div className="stat-value">{summaryStats.low_risk_count}</div>
              </div>
              <div className="stat-card">
                <h4>Avg Attendance</h4>
                <div className="stat-value">{Math.round(summaryStats.avg_attendance_rate * 100)}%</div>
              </div>
              <div className="stat-card">
                <h4>Avg Late Rate</h4>
                <div className="stat-value">{Math.round(summaryStats.avg_late_rate * 100)}%</div>
              </div>
            </div>
          )}

          {/* Controls */}
          <div className="controls-bar">
            <div className="filter-controls">
              <select 
                value={filterRisk} 
                onChange={(e) => setFilterRisk(e.target.value as any)}
              >
                <option value="all">All Risk Levels</option>
                <option value="high">High Risk Only</option>
                <option value="medium">Medium Risk Only</option>
                <option value="low">Low Risk Only</option>
              </select>

              <select 
                value={sortBy} 
                onChange={(e) => setSortBy(e.target.value as any)}
              >
                <option value="risk">Sort by Risk Level</option>
                <option value="name">Sort by Name</option>
                <option value="attendance_rate">Sort by Attendance Rate</option>
                <option value="consecutive_absences">Sort by Consecutive Absences</option>
              </select>

              <button 
                onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
              >
                {sortOrder === 'asc' ? '↑' : '↓'}
              </button>
            </div>

            <div className="toggle-controls">
              <label>
                <input
                  type="checkbox"
                  checked={showOnlyAlerts}
                  onChange={(e) => setShowOnlyAlerts(e.target.checked)}
                />
                Show only students with alerts
              </label>
            </div>
          </div>

          {/* Pattern Cards */}
          <div className="patterns-grid">
            {filteredAndSortedData.map(data => {
              const studentAlerts = getStudentAlerts(data.student_id);
              
              return (
                <div key={data.student_id} className={`pattern-card risk-${data.risk_level}`}>
                  <div className="pattern-header">
                    <h3>{data.student_name}</h3>
                    <div className={`risk-badge risk-${data.risk_level}`}>
                      {data.risk_level.toUpperCase()} RISK
                    </div>
                  </div>

                  {studentAlerts.length > 0 && (
                    <div className="student-alerts">
                      {studentAlerts.map((alert, index) => (
                        <div key={index} className={`alert-badge severity-${alert.severity}`}>
                          <span className="alert-type">{alert.type}</span>
                          <span className="alert-message">{alert.message}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <PatternVisualization data={data} />

                  <div className="pattern-details">
                    <div className="detail-row">
                      <span>Total Sessions:</span>
                      <span>{data.total_sessions}</span>
                    </div>
                    <div className="detail-row">
                      <span>Consecutive Absences:</span>
                      <span className={data.consecutive_absences >= 3 ? 'warning' : ''}>
                        {data.consecutive_absences}
                      </span>
                    </div>
                  </div>

                  <button 
                    className="btn btn-sm"
                    onClick={() => setSelectedStudent(
                      selectedStudent === data.student_id ? null : data.student_id
                    )}
                  >
                    {selectedStudent === data.student_id ? 'Hide Details' : 'View Details'}
                  </button>

                  {selectedStudent === data.student_id && (
                    <div className="expanded-details">
                      <div className="detail-section">
                        <h4>Attendance Breakdown</h4>
                        <div className="breakdown-grid">
                          <div className="breakdown-item">
                            <span className="breakdown-label">Present</span>
                            <span className="breakdown-value present">{data.present_count}</span>
                          </div>
                          <div className="breakdown-item">
                            <span className="breakdown-label">Late</span>
                            <span className="breakdown-value late">{data.late_count}</span>
                          </div>
                          <div className="breakdown-item">
                            <span className="breakdown-label">Absent</span>
                            <span className="breakdown-value absent">{data.absent_count}</span>
                          </div>
                          <div className="breakdown-item">
                            <span className="breakdown-label">Excused</span>
                            <span className="breakdown-value excused">{data.excused_count}</span>
                          </div>
                        </div>
                      </div>

                      <div className="detail-section">
                        <h4>Recommendations</h4>
                        <ul className="recommendations">
                          {data.risk_level === 'high' && (
                            <>
                              <li>Schedule immediate intervention meeting</li>
                              <li>Contact student/parent about attendance concerns</li>
                              <li>Develop attendance improvement plan</li>
                            </>
                          )}
                          {data.risk_level === 'medium' && (
                            <>
                              <li>Monitor attendance closely</li>
                              <li>Provide attendance reminders</li>
                              <li>Check for any attendance barriers</li>
                            </>
                          )}
                          {data.late_rate > 0.3 && (
                            <li>Address punctuality issues with student</li>
                          )}
                          {data.trends.attendance_trend === 'declining' && (
                            <li>Investigate causes of declining attendance</li>
                          )}
                        </ul>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {filteredAndSortedData.length === 0 && (
            <div className="empty-state">
              <p>No students match the current filters.</p>
              <button onClick={() => {
                setFilterRisk('all');
                setShowOnlyAlerts(false);
              }}>
                Clear Filters
              </button>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
          <button className="btn btn-primary" onClick={loadPatternData}>
            Refresh Analysis
          </button>
        </div>
      </div>

      <style jsx>{`
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          display: flex;
          justify-content: center;
          align-items: center;
          z-index: 1000;
          padding: 20px;
        }

        .modal-content {
          background: white;
          border-radius: 8px;
          width: 100%;
          max-width: 1200px;
          max-height: 90vh;
          overflow: hidden;
          box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
          display: flex;
          flex-direction: column;
        }

        .modal-content.loading {
          max-width: 300px;
          height: 200px;
          justify-content: center;
          align-items: center;
        }

        .loading-spinner {
          text-align: center;
        }

        .spinner {
          border: 4px solid #f3f3f3;
          border-top: 4px solid #007bff;
          border-radius: 50%;
          width: 50px;
          height: 50px;
          animation: spin 1s linear infinite;
          margin: 0 auto 20px;
        }

        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }

        .modal-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 20px 24px;
          border-bottom: 1px solid #eee;
        }

        .modal-header h2 {
          margin: 0;
          font-size: 24px;
          color: #333;
        }

        .close-button {
          background: none;
          border: none;
          font-size: 24px;
          cursor: pointer;
          color: #666;
          padding: 0;
          width: 24px;
          height: 24px;
        }

        .modal-body {
          padding: 24px;
          overflow-y: auto;
          flex: 1;
        }

        .alert {
          padding: 12px;
          border-radius: 4px;
          margin-bottom: 20px;
        }

        .alert-error {
          background: #f8d7da;
          color: #721c24;
          border: 1px solid #f5c6cb;
        }

        .summary-stats {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
          gap: 16px;
          margin-bottom: 24px;
        }

        .stat-card {
          background: #f8f9fa;
          border: 1px solid #eee;
          border-radius: 8px;
          padding: 16px;
          text-align: center;
        }

        .stat-card.risk-high {
          background: #f8d7da;
          border-color: #f5c6cb;
        }

        .stat-card.risk-medium {
          background: #fff3cd;
          border-color: #ffeaa7;
        }

        .stat-card.risk-low {
          background: #d4edda;
          border-color: #c3e6cb;
        }

        .stat-card h4 {
          margin: 0 0 8px 0;
          font-size: 12px;
          color: #666;
          text-transform: uppercase;
          font-weight: 600;
        }

        .stat-value {
          font-size: 24px;
          font-weight: bold;
          color: #333;
        }

        .controls-bar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
          flex-wrap: wrap;
          gap: 16px;
        }

        .filter-controls, .toggle-controls {
          display: flex;
          gap: 12px;
          align-items: center;
        }

        .filter-controls select, .filter-controls button {
          padding: 8px 12px;
          border: 1px solid #ddd;
          border-radius: 4px;
          background: white;
          cursor: pointer;
          font-size: 14px;
        }

        .filter-controls button {
          padding: 8px 12px;
          min-width: 40px;
        }

        .toggle-controls label {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
          font-size: 14px;
        }

        .patterns-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
          gap: 20px;
        }

        .pattern-card {
          background: white;
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 20px;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .pattern-card.risk-high {
          border-left: 4px solid #dc3545;
        }

        .pattern-card.risk-medium {
          border-left: 4px solid #ffc107;
        }

        .pattern-card.risk-low {
          border-left: 4px solid #28a745;
        }

        .pattern-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }

        .pattern-header h3 {
          margin: 0;
          font-size: 18px;
          color: #333;
        }

        .risk-badge {
          padding: 4px 8px;
          border-radius: 12px;
          font-size: 10px;
          font-weight: 600;
          text-transform: uppercase;
        }

        .risk-badge.risk-high {
          background: #dc3545;
          color: white;
        }

        .risk-badge.risk-medium {
          background: #ffc107;
          color: #212529;
        }

        .risk-badge.risk-low {
          background: #28a745;
          color: white;
        }

        .student-alerts {
          margin-bottom: 16px;
        }

        .alert-badge {
          display: block;
          padding: 6px 8px;
          border-radius: 4px;
          font-size: 12px;
          margin-bottom: 4px;
        }

        .severity-high { background: #f8d7da; color: #721c24; }
        .severity-medium { background: #fff3cd; color: #856404; }
        .severity-low { background: #d4edda; color: #155724; }

        .alert-type {
          font-weight: 600;
          margin-right: 8px;
        }

        .pattern-visualization {
          margin-bottom: 16px;
        }

        .chart-container {
          text-align: center;
          margin-bottom: 12px;
        }

        .pattern-metrics {
          display: flex;
          justify-content: space-around;
          margin-bottom: 12px;
        }

        .metric {
          text-align: center;
        }

        .metric-label {
          display: block;
          font-size: 12px;
          color: #666;
          margin-bottom: 4px;
        }

        .metric-value {
          font-size: 16px;
          font-weight: bold;
        }

        .rate-high { color: #28a745; }
        .rate-medium { color: #ffc107; }
        .rate-low { color: #dc3545; }

        .trend-indicators {
          display: flex;
          justify-content: space-around;
          font-size: 12px;
        }

        .trend {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .pattern-details {
          margin-bottom: 16px;
        }

        .detail-row {
          display: flex;
          justify-content: space-between;
          padding: 4px 0;
          border-bottom: 1px solid #eee;
        }

        .detail-row span:last-child.warning {
          color: #dc3545;
          font-weight: 600;
        }

        .btn {
          padding: 8px 16px;
          border: 1px solid #ddd;
          border-radius: 4px;
          background: white;
          cursor: pointer;
          font-size: 14px;
          transition: all 0.2s;
        }

        .btn-sm {
          padding: 6px 12px;
          font-size: 12px;
        }

        .btn-primary {
          background: #007bff;
          color: white;
          border-color: #007bff;
        }

        .btn-secondary {
          background: #6c757d;
          color: white;
          border-color: #6c757d;
        }

        .btn:hover {
          opacity: 0.9;
        }

        .expanded-details {
          margin-top: 16px;
          padding-top: 16px;
          border-top: 1px solid #eee;
        }

        .detail-section {
          margin-bottom: 16px;
        }

        .detail-section h4 {
          margin: 0 0 8px 0;
          font-size: 14px;
          color: #333;
        }

        .breakdown-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 8px;
        }

        .breakdown-item {
          display: flex;
          justify-content: space-between;
          padding: 4px 8px;
          background: #f8f9fa;
          border-radius: 4px;
          font-size: 12px;
        }

        .breakdown-value.present { color: #28a745; font-weight: 600; }
        .breakdown-value.late { color: #ffc107; font-weight: 600; }
        .breakdown-value.absent { color: #dc3545; font-weight: 600; }
        .breakdown-value.excused { color: #17a2b8; font-weight: 600; }

        .recommendations {
          margin: 0;
          padding-left: 16px;
          font-size: 14px;
        }

        .recommendations li {
          margin-bottom: 4px;
          color: #666;
        }

        .empty-state {
          text-align: center;
          padding: 40px 20px;
          color: #666;
        }

        .modal-footer {
          display: flex;
          justify-content: flex-end;
          gap: 12px;
          padding: 20px 24px;
          border-top: 1px solid #eee;
          background: #f8f9fa;
        }

        @media (max-width: 768px) {
          .modal-overlay {
            padding: 10px;
          }

          .modal-content {
            max-width: 100%;
          }

          .patterns-grid {
            grid-template-columns: 1fr;
          }

          .summary-stats {
            grid-template-columns: repeat(2, 1fr);
          }

          .controls-bar {
            flex-direction: column;
            align-items: stretch;
          }

          .filter-controls {
            justify-content: center;
          }

          .breakdown-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};

export default AttendancePatterns;