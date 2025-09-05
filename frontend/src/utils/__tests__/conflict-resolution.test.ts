/**
 * Conflict Resolution Tests
 * 
 * Tests for conflict detection, resolution strategies,
 * and three-way merge algorithms.
 */

import { 
  ConflictResolutionEngine, 
  ConflictType, 
  ResolutionStrategy,
  ConflictData,
  ResolutionResult
} from '../conflict-resolution';

describe('ConflictResolutionEngine', () => {
  let resolver: ConflictResolutionEngine;
  
  beforeEach(() => {
    resolver = new ConflictResolutionEngine();
  });
  
  describe('attendance status conflicts', () => {
    it('should prefer present over absent status', async () => {
      const conflict: ConflictData = {
        type: ConflictType.ATTENDANCE_STATUS,
        entityId: 'student_123_session_456',
        localVersion: { status: 'present', updated_at: '2023-12-01T10:30:00Z' },
        serverVersion: { status: 'absent', updated_at: '2023-12-01T10:29:00Z' },
        timestamp: Date.now(),
        conflictFields: ['status']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.AUTO_MERGE);
      expect(result.resolvedData.status).toBe('present');
      expect(result.confidence).toBeGreaterThan(80);
      expect(result.requiresUserInput).toBe(false);
    });
    
    it('should use timestamp for same-type status conflicts', async () => {
      const conflict: ConflictData = {
        type: ConflictType.ATTENDANCE_STATUS,
        entityId: 'student_123_session_456',
        localVersion: { status: 'late', updated_at: '2023-12-01T10:35:00Z' },
        serverVersion: { status: 'present', updated_at: '2023-12-01T10:30:00Z' },
        timestamp: Date.now(),
        conflictFields: ['status']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.LAST_WRITER_WINS);
      expect(result.resolvedData.status).toBe('late');
      expect(result.explanation).toContain('more recent');
    });
    
    it('should use server version for older local changes', async () => {
      const conflict: ConflictData = {
        type: ConflictType.ATTENDANCE_STATUS,
        entityId: 'student_123_session_456',
        localVersion: { status: 'present', updated_at: '2023-12-01T10:25:00Z' },
        serverVersion: { status: 'late', updated_at: '2023-12-01T10:30:00Z' },
        timestamp: Date.now(),
        conflictFields: ['status']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.LAST_WRITER_WINS);
      expect(result.resolvedData.status).toBe('late');
    });
  });
  
  describe('three-way merge', () => {
    it('should perform three-way merge with base version', async () => {
      const conflict: ConflictData = {
        type: ConflictType.STUDENT_DATA,
        entityId: 'student_123',
        localVersion: { 
          name: 'John Doe', 
          email: 'john.doe@updated.com', 
          status: 'active' 
        },
        serverVersion: { 
          name: 'John Smith', 
          email: 'john.doe@example.com', 
          status: 'active' 
        },
        baseVersion: { 
          name: 'John Doe', 
          email: 'john.doe@example.com', 
          status: 'inactive' 
        },
        timestamp: Date.now(),
        conflictFields: ['name', 'email', 'status']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.AUTO_MERGE);
      expect(result.resolvedData.name).toBe('John Smith'); // Server changed
      expect(result.resolvedData.email).toBe('john.doe@updated.com'); // Local changed
      expect(result.resolvedData.status).toBe('active'); // Both changed to same value
    });
    
    it('should detect conflicting changes in three-way merge', async () => {
      const conflict: ConflictData = {
        type: ConflictType.STUDENT_DATA,
        entityId: 'student_123',
        localVersion: { 
          name: 'John Local', 
          email: 'john@local.com' 
        },
        serverVersion: { 
          name: 'John Server', 
          email: 'john@server.com' 
        },
        baseVersion: { 
          name: 'John Original', 
          email: 'john@original.com' 
        },
        timestamp: Date.now(),
        conflictFields: ['name', 'email']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.conflicts.length).toBe(2); // Both fields have conflicts
      expect(result.confidence).toBeLessThan(70);
    });
  });
  
  describe('timestamp conflicts', () => {
    it('should resolve timestamp conflicts with most recent', async () => {
      const conflict: ConflictData = {
        type: ConflictType.TIMESTAMP_CONFLICT,
        entityId: 'record_123',
        localVersion: { timestamp: '2023-12-01T10:35:00Z', data: 'local' },
        serverVersion: { timestamp: '2023-12-01T10:30:00Z', data: 'server' },
        timestamp: Date.now(),
        conflictFields: ['timestamp', 'data']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.LAST_WRITER_WINS);
      expect(result.resolvedData.timestamp).toBe('2023-12-01T10:35:00Z');
      expect(result.resolvedData.data).toBe('local');
      expect(result.confidence).toBe(95);
    });
  });
  
  describe('bulk operation conflicts', () => {
    it('should merge bulk operations by deduplication and timestamp', async () => {
      const conflict: ConflictData = {
        type: ConflictType.BULK_OPERATION,
        entityId: 'bulk_123',
        localVersion: {
          operations: [
            { id: 'op1', type: 'check_in', timestamp: '2023-12-01T10:30:00Z' },
            { id: 'op2', type: 'status_update', timestamp: '2023-12-01T10:31:00Z' }
          ]
        },
        serverVersion: {
          operations: [
            { id: 'op1', type: 'check_in', timestamp: '2023-12-01T10:30:00Z' }, // Duplicate
            { id: 'op3', type: 'check_in', timestamp: '2023-12-01T10:32:00Z' }
          ]
        },
        timestamp: Date.now(),
        conflictFields: ['operations']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.AUTO_MERGE);
      expect(result.resolvedData.operations).toHaveLength(3); // Deduplicated
      expect(result.confidence).toBe(70);
    });
  });
  
  describe('session configuration conflicts', () => {
    it('should require user input for session config changes', async () => {
      const conflict: ConflictData = {
        type: ConflictType.SESSION_CONFIG,
        entityId: 'session_456',
        localVersion: { 
          name: 'Updated Math Class',
          duration: 90,
          auto_close: true 
        },
        serverVersion: { 
          name: 'Math Class',
          duration: 60,
          auto_close: false 
        },
        timestamp: Date.now(),
        conflictFields: ['name', 'duration', 'auto_close']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.USER_GUIDED);
      expect(result.requiresUserInput).toBe(true);
      expect(result.confidence).toBe(30);
    });
  });
  
  describe('custom resolvers', () => {
    it('should allow registration of custom conflict resolvers', async () => {
      const customResolver = jest.fn().mockResolvedValue({
        strategy: ResolutionStrategy.AUTO_MERGE,
        resolvedData: { custom: 'resolution' },
        requiresUserInput: false,
        conflicts: [],
        confidence: 100,
        explanation: 'Custom resolution applied'
      });
      
      resolver.registerResolver(ConflictType.ATTENDANCE_STATUS, customResolver);
      
      const conflict: ConflictData = {
        type: ConflictType.ATTENDANCE_STATUS,
        entityId: 'test',
        localVersion: { status: 'present' },
        serverVersion: { status: 'absent' },
        timestamp: Date.now(),
        conflictFields: ['status']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(customResolver).toHaveBeenCalledWith(conflict);
      expect(result.resolvedData.custom).toBe('resolution');
    });
  });
  
  describe('user-guided resolution', () => {
    it('should delegate to user handler when required', async () => {
      const userHandler = jest.fn().mockResolvedValue({
        strategy: ResolutionStrategy.LOCAL_WINS,
        resolvedData: { user: 'choice' },
        requiresUserInput: false,
        conflicts: [],
        confidence: 90,
        explanation: 'User selected local version'
      });
      
      resolver.setUserHandler(userHandler);
      
      const conflict: ConflictData = {
        type: ConflictType.SESSION_CONFIG,
        entityId: 'session_456',
        localVersion: { setting: 'local' },
        serverVersion: { setting: 'server' },
        timestamp: Date.now(),
        conflictFields: ['setting']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(userHandler).toHaveBeenCalled();
      expect(result.resolvedData.user).toBe('choice');
    });
  });
  
  describe('batch conflict resolution', () => {
    it('should resolve multiple conflicts in priority order', async () => {
      const conflicts: ConflictData[] = [
        {
          type: ConflictType.ATTENDANCE_STATUS,
          entityId: 'student_1',
          localVersion: { status: 'present' },
          serverVersion: { status: 'absent' },
          timestamp: Date.now(),
          conflictFields: ['status']
        },
        {
          type: ConflictType.TIMESTAMP_CONFLICT,
          entityId: 'record_1',
          localVersion: { timestamp: '2023-12-01T10:35:00Z' },
          serverVersion: { timestamp: '2023-12-01T10:30:00Z' },
          timestamp: Date.now(),
          conflictFields: ['timestamp']
        }
      ];
      
      const results = await resolver.batchResolve(conflicts);
      
      expect(results).toHaveLength(2);
      expect(results[0].resolvedData.status).toBe('present');
      expect(results[1].resolvedData.timestamp).toBe('2023-12-01T10:35:00Z');
    });
    
    it('should handle errors gracefully in batch resolution', async () => {
      const errorConflict: ConflictData = {
        type: ConflictType.ATTENDANCE_STATUS,
        entityId: 'error_case',
        localVersion: null, // This might cause an error
        serverVersion: { status: 'present' },
        timestamp: Date.now(),
        conflictFields: ['status']
      };
      
      const results = await resolver.batchResolve([errorConflict]);
      
      expect(results).toHaveLength(1);
      expect(results[0].strategy).toBe(ResolutionStrategy.REJECT_CHANGES);
      expect(results[0].confidence).toBe(0);
      expect(results[0].explanation).toContain('Failed to resolve');
    });
  });
  
  describe('conflict detection', () => {
    it('should detect potential conflicts before they happen', () => {
      const localChanges = [
        { entityId: 'student_123', id: 'change_1', field: 'status', value: 'present' }
      ];
      
      const serverChanges = [
        { entityId: 'student_123', id: 'change_2', field: 'status', value: 'absent' }
      ];
      
      const conflicts = resolver.detectPotentialConflicts(localChanges, serverChanges);
      
      expect(conflicts).toHaveLength(1);
      expect(conflicts[0].entityId).toBe('student_123');
    });
    
    it('should not detect conflicts for non-overlapping changes', () => {
      const localChanges = [
        { entityId: 'student_123', field: 'status', value: 'present' }
      ];
      
      const serverChanges = [
        { entityId: 'student_456', field: 'status', value: 'absent' }
      ];
      
      const conflicts = resolver.detectPotentialConflicts(localChanges, serverChanges);
      
      expect(conflicts).toHaveLength(0);
    });
  });
  
  describe('field-level conflict resolution', () => {
    it('should merge string fields appropriately', async () => {
      const conflict: ConflictData = {
        type: ConflictType.STUDENT_DATA,
        entityId: 'student_123',
        localVersion: { notes: 'Local note' },
        serverVersion: { notes: 'Server note' },
        timestamp: Date.now(),
        conflictFields: ['notes']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.AUTO_MERGE);
      expect(typeof result.resolvedData.notes).toBe('string');
    });
    
    it('should merge array fields by union', async () => {
      const conflict: ConflictData = {
        type: ConflictType.STUDENT_DATA,
        entityId: 'student_123',
        localVersion: { tags: ['local1', 'shared'] },
        serverVersion: { tags: ['server1', 'shared'] },
        timestamp: Date.now(),
        conflictFields: ['tags']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.strategy).toBe(ResolutionStrategy.AUTO_MERGE);
      expect(result.resolvedData.tags).toContain('local1');
      expect(result.resolvedData.tags).toContain('server1');
      expect(result.resolvedData.tags).toContain('shared');
      expect(result.resolvedData.tags.filter((tag: string) => tag === 'shared')).toHaveLength(1); // No duplicates
    });
  });
  
  describe('confidence scoring', () => {
    it('should provide high confidence for clear-cut resolutions', async () => {
      const conflict: ConflictData = {
        type: ConflictType.TIMESTAMP_CONFLICT,
        entityId: 'record_123',
        localVersion: { timestamp: '2023-12-01T10:35:00Z' },
        serverVersion: { timestamp: '2023-12-01T10:30:00Z' },
        timestamp: Date.now(),
        conflictFields: ['timestamp']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.confidence).toBeGreaterThan(90);
    });
    
    it('should provide low confidence for complex conflicts', async () => {
      const conflict: ConflictData = {
        type: ConflictType.SESSION_CONFIG,
        entityId: 'session_456',
        localVersion: { config: 'complex local config' },
        serverVersion: { config: 'complex server config' },
        timestamp: Date.now(),
        conflictFields: ['config']
      };
      
      const result = await resolver.resolveConflict(conflict);
      
      expect(result.confidence).toBeLessThan(50);
    });
  });
});

// Test utility functions
describe('conflict resolution utilities', () => {
  let resolver: ConflictResolutionEngine;
  
  beforeEach(() => {
    resolver = new ConflictResolutionEngine();
  });
  
  it('should handle malformed conflict data gracefully', async () => {
    const malformedConflict = {
      type: 'invalid_type' as any,
      entityId: 'test',
      localVersion: undefined,
      serverVersion: null,
      timestamp: Date.now(),
      conflictFields: []
    };
    
    const result = await resolver.resolveConflict(malformedConflict);
    
    expect(result.confidence).toBeLessThan(50);
    expect(result.explanation).toContain('Generic resolution');
  });
  
  it('should provide meaningful explanations for all resolutions', async () => {
    const conflict: ConflictData = {
      type: ConflictType.ATTENDANCE_STATUS,
      entityId: 'student_123',
      localVersion: { status: 'present' },
      serverVersion: { status: 'absent' },
      timestamp: Date.now(),
      conflictFields: ['status']
    };
    
    const result = await resolver.resolveConflict(conflict);
    
    expect(result.explanation).toBeTruthy();
    expect(result.explanation.length).toBeGreaterThan(10);
  });
});

// Cleanup
afterAll(() => {
  jest.restoreAllMocks();
});