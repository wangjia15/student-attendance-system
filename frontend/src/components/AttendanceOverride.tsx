import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { 
  AttendanceStatus, 
  BulkAttendanceOperation, 
  TeacherOverrideRequest,
  BulkAttendanceRequest,
  AttendanceRecord 
} from '../types/attendance';
import { attendanceWebSocket } from '../services/websocket';
import attendanceService from '../services/attendance';

interface AttendanceOverrideProps {
  classSessionId: number;
  selectedStudentIds: number[];
  onClose: () => void;
  onSuccess: () => void;
  initialData?: AttendanceRecord[];
}

interface StudentOverrideData {
  id: number;
  name: string;
  currentStatus: AttendanceStatus;
  newStatus: AttendanceStatus;
  reason: string;
  notes: string;
  selected: boolean;
}

const AttendanceOverride: React.FC<AttendanceOverrideProps> = ({
  classSessionId,
  selectedStudentIds,
  onClose,
  onSuccess,
  initialData = []
}) => {
  const [students, setStudents] = useState<StudentOverrideData[]>([]);
  const [bulkOperation, setBulkOperation] = useState<BulkAttendanceOperation | ''>('');
  const [bulkReason, setBulkReason] = useState('');
  const [bulkNotes, setBulkNotes] = useState('');
  const [mode, setMode] = useState<'individual' | 'bulk'>('individual');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);

  // Initialize student data
  useEffect(() => {
    const initializeStudents = async () => {
      try {
        setLoading(true);
        
        // If we have initial data, use that
        if (initialData.length > 0) {
          const studentData = initialData
            .filter(record => selectedStudentIds.includes(record.id))
            .map(record => ({
              id: record.id,
              name: record.student_name || 'Unknown Student',
              currentStatus: record.status,
              newStatus: record.status,
              reason: '',
              notes: '',
              selected: true
            }));
          setStudents(studentData);
        } else {
          // Otherwise, fetch current class data
          const report = await attendanceService.getClassAttendanceReport(classSessionId, false);
          const studentData = report.records
            .filter(record => selectedStudentIds.includes(record.id))
            .map(record => ({
              id: record.id,
              name: record.student_name || 'Unknown Student',
              currentStatus: record.status,
              newStatus: record.status,
              reason: '',
              notes: '',
              selected: true
            }));
          setStudents(studentData);
        }

        // Set mode based on number of students
        setMode(selectedStudentIds.length > 1 ? 'bulk' : 'individual');
      } catch (error) {
        setError(error instanceof Error ? error.message : 'Failed to load student data');
      } finally {
        setLoading(false);
      }
    };

    if (selectedStudentIds.length > 0) {
      initializeStudents();
    }
  }, [selectedStudentIds, classSessionId, initialData]);

  // Handle individual student changes
  const updateStudent = useCallback((studentId: number, field: keyof StudentOverrideData, value: any) => {
    setStudents(prev => prev.map(student => 
      student.id === studentId ? { ...student, [field]: value } : student
    ));
  }, []);

  // Handle bulk status change
  const handleBulkStatusChange = useCallback((operation: BulkAttendanceOperation) => {
    setBulkOperation(operation);
    
    let targetStatus: AttendanceStatus;
    switch (operation) {
      case BulkAttendanceOperation.MARK_PRESENT:
        targetStatus = AttendanceStatus.PRESENT;
        break;
      case BulkAttendanceOperation.MARK_LATE:
        targetStatus = AttendanceStatus.LATE;
        break;
      case BulkAttendanceOperation.MARK_ABSENT:
        targetStatus = AttendanceStatus.ABSENT;
        break;
      case BulkAttendanceOperation.MARK_EXCUSED:
        targetStatus = AttendanceStatus.EXCUSED;
        break;
      default:
        return;
    }

    // Update all selected students
    setStudents(prev => prev.map(student => 
      student.selected ? { ...student, newStatus: targetStatus } : student
    ));
  }, []);

  // Handle individual override submission
  const handleIndividualSubmit = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Start operation for conflict detection
      const opId = attendanceWebSocket.startOperation('individual_override');
      setOperationId(opId);

      const promises = students
        .filter(student => student.selected && student.newStatus !== student.currentStatus)
        .map(student => {
          const overrideRequest: TeacherOverrideRequest = {
            student_id: student.id,
            new_status: student.newStatus,
            reason: student.reason || 'Teacher override',
            notes: student.notes
          };
          
          return attendanceService.overrideAttendance(classSessionId, overrideRequest);
        });

      if (promises.length === 0) {
        setError('No changes to apply');
        return;
      }

      await Promise.all(promises);
      
      setSuccess(`Successfully updated ${promises.length} student(s)`);
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 1500);

    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to update attendance');
    } finally {
      if (operationId) {
        attendanceWebSocket.endOperation(operationId);
      }
      setLoading(false);
    }
  }, [students, classSessionId, onSuccess, onClose, operationId]);

  // Handle bulk operation submission
  const handleBulkSubmit = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      
      if (!bulkOperation) {
        setError('Please select an operation');
        return;
      }

      if (!bulkReason.trim()) {
        setError('Please provide a reason for the bulk operation');
        return;
      }

      // Start operation for conflict detection
      const opId = attendanceWebSocket.startOperation('bulk_operation');
      setOperationId(opId);

      const selectedIds = students.filter(s => s.selected).map(s => s.id);
      
      const bulkRequest: BulkAttendanceRequest = {
        class_session_id: classSessionId,
        operation: bulkOperation,
        student_ids: selectedIds,
        reason: bulkReason,
        notes: bulkNotes || undefined
      };

      const result = await attendanceService.bulkAttendanceOperation(bulkRequest);
      
      if (result.failed_count > 0) {
        setError(`Operation completed with ${result.failed_count} failures. Check the logs for details.`);
      } else {
        setSuccess(`Successfully processed ${result.processed_count} students`);
        setTimeout(() => {
          onSuccess();
          onClose();
        }, 1500);
      }

    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to perform bulk operation');
    } finally {
      if (operationId) {
        attendanceWebSocket.endOperation(operationId);
      }
      setLoading(false);
    }
  }, [bulkOperation, bulkReason, bulkNotes, students, classSessionId, onSuccess, onClose, operationId]);

  // Validate form
  const canSubmit = useMemo(() => {
    if (loading) return false;
    
    if (mode === 'bulk') {
      return bulkOperation && bulkReason.trim() && students.some(s => s.selected);
    } else {
      return students.some(s => s.selected && s.newStatus !== s.currentStatus);
    }
  }, [mode, bulkOperation, bulkReason, students, loading]);

  // Get selected count
  const selectedCount = students.filter(s => s.selected).length;

  if (loading && students.length === 0) {
    return (
      <div className="modal-overlay">
        <div className="modal-content loading">
          <div className="loading-spinner">
            <div className="spinner"></div>
            <p>Loading student data...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal-content override-modal">
        <div className="modal-header">
          <h2>Attendance Override</h2>
          <button className="close-button" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {error && (
            <div className="alert alert-error">
              {error}
            </div>
          )}

          {success && (
            <div className="alert alert-success">
              {success}
            </div>
          )}

          {/* Mode Selection */}
          {students.length > 1 && (
            <div className="mode-selection">
              <label>
                <input
                  type="radio"
                  name="mode"
                  value="individual"
                  checked={mode === 'individual'}
                  onChange={() => setMode('individual')}
                />
                Individual Override
              </label>
              <label>
                <input
                  type="radio"
                  name="mode"
                  value="bulk"
                  checked={mode === 'bulk'}
                  onChange={() => setMode('bulk')}
                />
                Bulk Operation
              </label>
            </div>
          )}

          {mode === 'bulk' ? (
            // Bulk Operation Form
            <div className="bulk-form">
              <div className="form-group">
                <label>Operation</label>
                <select
                  value={bulkOperation}
                  onChange={(e) => handleBulkStatusChange(e.target.value as BulkAttendanceOperation)}
                  required
                >
                  <option value="">Select operation...</option>
                  <option value={BulkAttendanceOperation.MARK_PRESENT}>Mark as Present</option>
                  <option value={BulkAttendanceOperation.MARK_LATE}>Mark as Late</option>
                  <option value={BulkAttendanceOperation.MARK_ABSENT}>Mark as Absent</option>
                  <option value={BulkAttendanceOperation.MARK_EXCUSED}>Mark as Excused</option>
                </select>
              </div>

              <div className="form-group">
                <label>Reason (Required)</label>
                <input
                  type="text"
                  value={bulkReason}
                  onChange={(e) => setBulkReason(e.target.value)}
                  placeholder="Reason for bulk operation..."
                  required
                />
              </div>

              <div className="form-group">
                <label>Additional Notes</label>
                <textarea
                  value={bulkNotes}
                  onChange={(e) => setBulkNotes(e.target.value)}
                  placeholder="Optional additional notes..."
                  rows={3}
                />
              </div>

              {/* Student Selection */}
              <div className="student-selection">
                <h4>Students to Update ({selectedCount} selected)</h4>
                <div className="student-list">
                  {students.map(student => (
                    <div key={student.id} className="student-item">
                      <label className="student-checkbox">
                        <input
                          type="checkbox"
                          checked={student.selected}
                          onChange={(e) => updateStudent(student.id, 'selected', e.target.checked)}
                        />
                        <span className="checkmark"></span>
                        <div className="student-info">
                          <span className="student-name">{student.name}</span>
                          <span className={`current-status status-${student.currentStatus.toLowerCase()}`}>
                            Current: {student.currentStatus}
                          </span>
                          {bulkOperation && student.selected && (
                            <span className={`new-status status-${student.newStatus.toLowerCase()}`}>
                              → {student.newStatus}
                            </span>
                          )}
                        </div>
                      </label>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            // Individual Override Form
            <div className="individual-form">
              <div className="students-grid">
                {students.map(student => (
                  <div key={student.id} className="student-override-card">
                    <div className="student-header">
                      <label className="student-checkbox">
                        <input
                          type="checkbox"
                          checked={student.selected}
                          onChange={(e) => updateStudent(student.id, 'selected', e.target.checked)}
                        />
                        <span className="student-name">{student.name}</span>
                      </label>
                    </div>

                    {student.selected && (
                      <div className="student-form">
                        <div className="status-change">
                          <div className="current-status">
                            <span>Current:</span>
                            <span className={`status-badge status-${student.currentStatus.toLowerCase()}`}>
                              {student.currentStatus}
                            </span>
                          </div>
                          <div className="arrow">→</div>
                          <div className="new-status">
                            <span>New:</span>
                            <select
                              value={student.newStatus}
                              onChange={(e) => updateStudent(student.id, 'newStatus', e.target.value as AttendanceStatus)}
                            >
                              <option value={AttendanceStatus.PRESENT}>Present</option>
                              <option value={AttendanceStatus.LATE}>Late</option>
                              <option value={AttendanceStatus.ABSENT}>Absent</option>
                              <option value={AttendanceStatus.EXCUSED}>Excused</option>
                            </select>
                          </div>
                        </div>

                        <div className="form-group">
                          <label>Reason</label>
                          <input
                            type="text"
                            value={student.reason}
                            onChange={(e) => updateStudent(student.id, 'reason', e.target.value)}
                            placeholder="Reason for override..."
                          />
                        </div>

                        <div className="form-group">
                          <label>Notes</label>
                          <textarea
                            value={student.notes}
                            onChange={(e) => updateStudent(student.id, 'notes', e.target.value)}
                            placeholder="Additional notes..."
                            rows={2}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button 
            className="btn btn-secondary" 
            onClick={onClose}
            disabled={loading}
          >
            Cancel
          </button>
          <button 
            className="btn btn-primary"
            onClick={mode === 'bulk' ? handleBulkSubmit : handleIndividualSubmit}
            disabled={!canSubmit}
          >
            {loading ? 'Processing...' : `Apply ${mode === 'bulk' ? 'Bulk Operation' : 'Changes'}`}
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
          max-width: 800px;
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

        .alert-success {
          background: #d4edda;
          color: #155724;
          border: 1px solid #c3e6cb;
        }

        .mode-selection {
          display: flex;
          gap: 20px;
          margin-bottom: 24px;
          padding: 16px;
          background: #f8f9fa;
          border-radius: 4px;
        }

        .mode-selection label {
          display: flex;
          align-items: center;
          gap: 8px;
          cursor: pointer;
          font-weight: 500;
        }

        .form-group {
          margin-bottom: 20px;
        }

        .form-group label {
          display: block;
          margin-bottom: 8px;
          font-weight: 500;
          color: #333;
        }

        .form-group input,
        .form-group select,
        .form-group textarea {
          width: 100%;
          padding: 10px;
          border: 1px solid #ddd;
          border-radius: 4px;
          font-size: 14px;
          font-family: inherit;
        }

        .form-group textarea {
          resize: vertical;
        }

        .student-selection h4 {
          margin: 20px 0 16px 0;
          color: #333;
        }

        .student-list {
          border: 1px solid #eee;
          border-radius: 4px;
          max-height: 200px;
          overflow-y: auto;
        }

        .student-item {
          padding: 12px;
          border-bottom: 1px solid #eee;
        }

        .student-item:last-child {
          border-bottom: none;
        }

        .student-checkbox {
          display: flex;
          align-items: center;
          gap: 12px;
          cursor: pointer;
        }

        .student-checkbox input[type="checkbox"] {
          width: auto;
          margin: 0;
        }

        .student-info {
          display: flex;
          flex-direction: column;
          gap: 4px;
          flex: 1;
        }

        .student-name {
          font-weight: 500;
          color: #333;
        }

        .current-status, .new-status {
          font-size: 14px;
        }

        .status-badge {
          padding: 2px 8px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 500;
          text-transform: uppercase;
        }

        .status-present { background: #d4edda; color: #155724; }
        .status-late { background: #fff3cd; color: #856404; }
        .status-absent { background: #f8d7da; color: #721c24; }
        .status-excused { background: #d1ecf1; color: #0c5460; }

        .students-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 20px;
        }

        .student-override-card {
          border: 1px solid #ddd;
          border-radius: 8px;
          padding: 16px;
          background: #fafafa;
        }

        .student-header {
          margin-bottom: 16px;
        }

        .student-header .student-checkbox {
          font-weight: 600;
          color: #333;
        }

        .status-change {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;
          padding: 12px;
          background: white;
          border-radius: 4px;
          border: 1px solid #eee;
        }

        .current-status, .new-status {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          flex: 1;
        }

        .current-status span:first-child,
        .new-status span:first-child {
          font-size: 12px;
          color: #666;
          text-transform: uppercase;
          font-weight: 500;
        }

        .new-status select {
          width: auto;
          min-width: 100px;
          padding: 4px 8px;
          font-size: 12px;
        }

        .arrow {
          font-size: 18px;
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

        .btn {
          padding: 10px 20px;
          border: 1px solid #ddd;
          border-radius: 4px;
          background: white;
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
          transition: all 0.2s;
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

        .btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        @media (max-width: 768px) {
          .modal-overlay {
            padding: 10px;
          }

          .modal-content {
            max-width: 100%;
          }

          .students-grid {
            grid-template-columns: 1fr;
          }

          .status-change {
            flex-direction: column;
            text-align: center;
          }

          .arrow {
            transform: rotate(90deg);
          }

          .mode-selection {
            flex-direction: column;
            gap: 12px;
          }
        }
      `}</style>
    </div>
  );
};

export default AttendanceOverride;