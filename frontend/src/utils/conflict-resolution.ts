/**
 * Conflict Resolution Algorithms
 * 
 * Handles conflicts when simultaneous offline modifications occur:
 * - Three-way merge algorithms for attendance data
 * - Last-writer-wins with timestamps
 * - User-guided conflict resolution
 * - Automatic resolution strategies based on data type
 * - Conflict detection and prevention
 */

export enum ConflictType {
  ATTENDANCE_STATUS = 'attendance_status',
  STUDENT_DATA = 'student_data',
  SESSION_CONFIG = 'session_config',
  BULK_OPERATION = 'bulk_operation',
  TIMESTAMP_CONFLICT = 'timestamp_conflict'
}

export enum ResolutionStrategy {
  AUTO_MERGE = 'auto_merge',
  LAST_WRITER_WINS = 'last_writer_wins',
  FIRST_WRITER_WINS = 'first_writer_wins',
  USER_GUIDED = 'user_guided',
  REJECT_CHANGES = 'reject_changes',
  ACCEPT_BOTH = 'accept_both'
}

export interface ConflictData {
  type: ConflictType;
  entityId: string;
  localVersion: any;
  serverVersion: any;
  baseVersion?: any; // Original version before any changes
  timestamp: number;
  conflictFields: string[];
  metadata?: any;
}

export interface ResolutionResult {
  strategy: ResolutionStrategy;
  resolvedData: any;
  requiresUserInput: boolean;
  conflicts: ConflictField[];
  confidence: number; // 0-100, higher means more confident in resolution
  explanation: string;
}

export interface ConflictField {
  fieldPath: string;
  localValue: any;
  serverValue: any;
  baseValue?: any;
  resolution: any;
  strategy: ResolutionStrategy;
  confidence: number;
}

export type ConflictResolver = (conflict: ConflictData) => Promise<ResolutionResult>;
export type UserConflictHandler = (conflict: ConflictData, suggestions: ResolutionResult[]) => Promise<ResolutionResult>;

/**
 * Main conflict resolution engine
 */
export class ConflictResolutionEngine {
  private resolvers = new Map<ConflictType, ConflictResolver>();
  private userHandler: UserConflictHandler | null = null;
  
  // Default resolution strategies by data type
  private defaultStrategies = new Map<string, ResolutionStrategy>([
    ['attendance_status', ResolutionStrategy.LAST_WRITER_WINS],
    ['timestamp', ResolutionStrategy.LAST_WRITER_WINS],
    ['notes', ResolutionStrategy.AUTO_MERGE],
    ['settings', ResolutionStrategy.USER_GUIDED]
  ]);

  constructor() {
    this.initializeDefaultResolvers();
  }

  /**
   * Resolve a conflict using appropriate strategy
   */
  async resolveConflict(conflict: ConflictData): Promise<ResolutionResult> {
    const resolver = this.resolvers.get(conflict.type);
    
    if (resolver) {
      const result = await resolver(conflict);
      
      // If requires user input and we have a handler, delegate to user
      if (result.requiresUserInput && this.userHandler) {
        const suggestions = [result, ...(await this.generateAlternativeSuggestions(conflict))];
        return await this.userHandler(conflict, suggestions);
      }
      
      return result;
    } else {
      // Fall back to generic resolution
      return await this.genericResolve(conflict);
    }
  }

  /**
   * Detect potential conflicts before they happen
   */
  detectPotentialConflicts(localChanges: any[], serverChanges: any[]): ConflictData[] {
    const conflicts: ConflictData[] = [];
    
    for (const localChange of localChanges) {
      for (const serverChange of serverChanges) {
        if (this.changesOverlap(localChange, serverChange)) {
          conflicts.push(this.createConflictData(localChange, serverChange));
        }
      }
    }
    
    return conflicts;
  }

  /**
   * Register a custom conflict resolver
   */
  registerResolver(type: ConflictType, resolver: ConflictResolver): void {
    this.resolvers.set(type, resolver);
  }

  /**
   * Set user conflict handler for manual resolution
   */
  setUserHandler(handler: UserConflictHandler): void {
    this.userHandler = handler;
  }

  /**
   * Batch resolve multiple conflicts
   */
  async batchResolve(conflicts: ConflictData[]): Promise<ResolutionResult[]> {
    const results: ResolutionResult[] = [];
    
    // Sort by confidence - handle high-confidence auto-resolves first
    const sorted = [...conflicts].sort((a, b) => {
      const aStrategy = this.getPreferredStrategy(a);
      const bStrategy = this.getPreferredStrategy(b);
      
      const aAutoResolvable = this.isAutoResolvable(aStrategy);
      const bAutoResolvable = this.isAutoResolvable(bStrategy);
      
      if (aAutoResolvable && !bAutoResolvable) return -1;
      if (!aAutoResolvable && bAutoResolvable) return 1;
      
      return 0;
    });
    
    // Process conflicts
    for (const conflict of sorted) {
      try {
        const result = await this.resolveConflict(conflict);
        results.push(result);
      } catch (error) {
        console.error('Failed to resolve conflict:', error);
        results.push({
          strategy: ResolutionStrategy.REJECT_CHANGES,
          resolvedData: conflict.serverVersion,
          requiresUserInput: true,
          conflicts: [],
          confidence: 0,
          explanation: `Failed to resolve: ${error instanceof Error ? error.message : 'Unknown error'}`
        });
      }
    }
    
    return results;
  }

  // Private methods for default resolvers
  private initializeDefaultResolvers(): void {
    this.registerResolver(ConflictType.ATTENDANCE_STATUS, this.resolveAttendanceStatus.bind(this));
    this.registerResolver(ConflictType.STUDENT_DATA, this.resolveStudentData.bind(this));
    this.registerResolver(ConflictType.SESSION_CONFIG, this.resolveSessionConfig.bind(this));
    this.registerResolver(ConflictType.BULK_OPERATION, this.resolveBulkOperation.bind(this));
    this.registerResolver(ConflictType.TIMESTAMP_CONFLICT, this.resolveTimestampConflict.bind(this));
  }

  /**
   * Resolve attendance status conflicts
   */
  private async resolveAttendanceStatus(conflict: ConflictData): Promise<ResolutionResult> {
    const { localVersion, serverVersion, timestamp } = conflict;
    
    // For attendance status, generally prefer the most recent update
    const localTimestamp = localVersion.updated_at || localVersion.timestamp || 0;
    const serverTimestamp = serverVersion.updated_at || serverVersion.timestamp || 0;
    
    // Special cases for attendance status transitions
    const localStatus = localVersion.status;
    const serverStatus = serverVersion.status;
    
    // If one is "present" and other is "absent", prefer "present" (someone checked in)
    if ((localStatus === 'present' && serverStatus === 'absent') || 
        (localStatus === 'absent' && serverStatus === 'present')) {
      
      const resolution = localStatus === 'present' ? localVersion : serverVersion;
      
      return {
        strategy: ResolutionStrategy.AUTO_MERGE,
        resolvedData: resolution,
        requiresUserInput: false,
        conflicts: [{
          fieldPath: 'status',
          localValue: localStatus,
          serverValue: serverStatus,
          resolution: resolution.status,
          strategy: ResolutionStrategy.AUTO_MERGE,
          confidence: 85
        }],
        confidence: 85,
        explanation: 'Automatically resolved: Presence takes precedence over absence'
      };
    }
    
    // For other cases, use timestamp-based resolution
    if (localTimestamp > serverTimestamp) {
      return {
        strategy: ResolutionStrategy.LAST_WRITER_WINS,
        resolvedData: localVersion,
        requiresUserInput: false,
        conflicts: [{
          fieldPath: 'status',
          localValue: localStatus,
          serverValue: serverStatus,
          resolution: localStatus,
          strategy: ResolutionStrategy.LAST_WRITER_WINS,
          confidence: 90
        }],
        confidence: 90,
        explanation: 'Local change is more recent'
      };
    } else {
      return {
        strategy: ResolutionStrategy.LAST_WRITER_WINS,
        resolvedData: serverVersion,
        requiresUserInput: false,
        conflicts: [{
          fieldPath: 'status',
          localValue: localStatus,
          serverValue: serverStatus,
          resolution: serverStatus,
          strategy: ResolutionStrategy.LAST_WRITER_WINS,
          confidence: 90
        }],
        confidence: 90,
        explanation: 'Server change is more recent'
      };
    }
  }

  /**
   * Resolve student data conflicts
   */
  private async resolveStudentData(conflict: ConflictData): Promise<ResolutionResult> {
    const { localVersion, serverVersion, baseVersion } = conflict;
    
    if (baseVersion) {
      // Three-way merge
      return await this.threeWayMerge(conflict);
    } else {
      // Two-way merge with field-level resolution
      return await this.fieldLevelMerge(conflict);
    }
  }

  /**
   * Resolve session configuration conflicts
   */
  private async resolveSessionConfig(conflict: ConflictData): Promise<ResolutionResult> {
    // Session config changes usually require user input
    return {
      strategy: ResolutionStrategy.USER_GUIDED,
      resolvedData: conflict.serverVersion,
      requiresUserInput: true,
      conflicts: await this.analyzeFieldConflicts(conflict),
      confidence: 30,
      explanation: 'Session configuration changes require manual review'
    };
  }

  /**
   * Resolve bulk operation conflicts
   */
  private async resolveBulkOperation(conflict: ConflictData): Promise<ResolutionResult> {
    const { localVersion, serverVersion } = conflict;
    
    // For bulk operations, analyze the individual operations
    const localOps = localVersion.operations || [];
    const serverOps = serverVersion.operations || [];
    
    const mergedOps = this.mergeBulkOperations(localOps, serverOps);
    
    return {
      strategy: ResolutionStrategy.AUTO_MERGE,
      resolvedData: {
        ...localVersion,
        operations: mergedOps
      },
      requiresUserInput: false,
      conflicts: [],
      confidence: 70,
      explanation: 'Merged bulk operations automatically'
    };
  }

  /**
   * Resolve timestamp-based conflicts
   */
  private async resolveTimestampConflict(conflict: ConflictData): Promise<ResolutionResult> {
    const { localVersion, serverVersion } = conflict;
    
    const localTime = new Date(localVersion.timestamp || 0).getTime();
    const serverTime = new Date(serverVersion.timestamp || 0).getTime();
    
    const winner = localTime > serverTime ? localVersion : serverVersion;
    
    return {
      strategy: ResolutionStrategy.LAST_WRITER_WINS,
      resolvedData: winner,
      requiresUserInput: false,
      conflicts: [{
        fieldPath: 'timestamp',
        localValue: localVersion.timestamp,
        serverValue: serverVersion.timestamp,
        resolution: winner.timestamp,
        strategy: ResolutionStrategy.LAST_WRITER_WINS,
        confidence: 95
      }],
      confidence: 95,
      explanation: 'Resolved using most recent timestamp'
    };
  }

  /**
   * Perform three-way merge using base version
   */
  private async threeWayMerge(conflict: ConflictData): Promise<ResolutionResult> {
    const { localVersion, serverVersion, baseVersion } = conflict;
    const merged = { ...baseVersion };
    const conflicts: ConflictField[] = [];
    
    const allKeys = new Set([
      ...Object.keys(localVersion || {}),
      ...Object.keys(serverVersion || {}),
      ...Object.keys(baseVersion || {})
    ]);
    
    for (const key of allKeys) {
      const localVal = localVersion?.[key];
      const serverVal = serverVersion?.[key];
      const baseVal = baseVersion?.[key];
      
      if (localVal === serverVal) {
        // No conflict
        merged[key] = localVal;
      } else if (localVal === baseVal) {
        // Local unchanged, use server version
        merged[key] = serverVal;
      } else if (serverVal === baseVal) {
        // Server unchanged, use local version
        merged[key] = localVal;
      } else {
        // Both changed - need resolution strategy
        const fieldResolution = await this.resolveFieldConflict(key, localVal, serverVal, baseVal);
        merged[key] = fieldResolution.resolution;
        conflicts.push(fieldResolution);
      }
    }
    
    return {
      strategy: ResolutionStrategy.AUTO_MERGE,
      resolvedData: merged,
      requiresUserInput: conflicts.some(c => c.confidence < 70),
      conflicts,
      confidence: conflicts.length === 0 ? 95 : Math.min(...conflicts.map(c => c.confidence)),
      explanation: 'Three-way merge completed'
    };
  }

  /**
   * Perform field-level merge without base version
   */
  private async fieldLevelMerge(conflict: ConflictData): Promise<ResolutionResult> {
    const { localVersion, serverVersion } = conflict;
    const merged = { ...serverVersion }; // Start with server version
    const conflicts: ConflictField[] = [];
    
    const allKeys = new Set([
      ...Object.keys(localVersion || {}),
      ...Object.keys(serverVersion || {})
    ]);
    
    for (const key of allKeys) {
      const localVal = localVersion?.[key];
      const serverVal = serverVersion?.[key];
      
      if (localVal !== serverVal) {
        const fieldResolution = await this.resolveFieldConflict(key, localVal, serverVal);
        merged[key] = fieldResolution.resolution;
        conflicts.push(fieldResolution);
      }
    }
    
    return {
      strategy: ResolutionStrategy.AUTO_MERGE,
      resolvedData: merged,
      requiresUserInput: conflicts.some(c => c.confidence < 50),
      conflicts,
      confidence: conflicts.length === 0 ? 80 : Math.min(...conflicts.map(c => c.confidence)),
      explanation: 'Field-level merge completed'
    };
  }

  /**
   * Resolve individual field conflicts
   */
  private async resolveFieldConflict(
    fieldPath: string,
    localValue: any,
    serverValue: any,
    baseValue?: any
  ): Promise<ConflictField> {
    
    // Get preferred strategy for this field type
    const strategy = this.getFieldStrategy(fieldPath);
    
    let resolution: any;
    let confidence: number;
    
    switch (strategy) {
      case ResolutionStrategy.LAST_WRITER_WINS:
        // Use timestamp or other criteria to determine winner
        resolution = this.isLocalNewer(localValue, serverValue) ? localValue : serverValue;
        confidence = 80;
        break;
        
      case ResolutionStrategy.AUTO_MERGE:
        // Attempt automatic merge for compatible types
        if (typeof localValue === 'string' && typeof serverValue === 'string') {
          resolution = this.mergeStrings(localValue, serverValue, baseValue);
          confidence = 60;
        } else if (Array.isArray(localValue) && Array.isArray(serverValue)) {
          resolution = this.mergeArrays(localValue, serverValue);
          confidence = 70;
        } else {
          resolution = serverValue; // Default to server
          confidence = 30;
        }
        break;
        
      case ResolutionStrategy.ACCEPT_BOTH:
        if (Array.isArray(localValue) && Array.isArray(serverValue)) {
          resolution = [...new Set([...localValue, ...serverValue])]; // Merge arrays
          confidence = 85;
        } else {
          resolution = { local: localValue, server: serverValue };
          confidence = 50;
        }
        break;
        
      default:
        resolution = serverValue;
        confidence = 30;
    }
    
    return {
      fieldPath,
      localValue,
      serverValue,
      baseValue,
      resolution,
      strategy,
      confidence
    };
  }

  /**
   * Generic conflict resolution fallback
   */
  private async genericResolve(conflict: ConflictData): Promise<ResolutionResult> {
    // Default to server version with low confidence
    return {
      strategy: ResolutionStrategy.LAST_WRITER_WINS,
      resolvedData: conflict.serverVersion,
      requiresUserInput: true,
      conflicts: await this.analyzeFieldConflicts(conflict),
      confidence: 20,
      explanation: 'Generic resolution: defaulting to server version'
    };
  }

  // Utility methods
  private changesOverlap(localChange: any, serverChange: any): boolean {
    return localChange.entityId === serverChange.entityId ||
           localChange.id === serverChange.id;
  }

  private createConflictData(localChange: any, serverChange: any): ConflictData {
    const conflictFields = this.identifyConflictFields(localChange, serverChange);
    
    return {
      type: this.inferConflictType(localChange, serverChange),
      entityId: localChange.entityId || localChange.id,
      localVersion: localChange,
      serverVersion: serverChange,
      timestamp: Date.now(),
      conflictFields
    };
  }

  private identifyConflictFields(local: any, server: any): string[] {
    const conflicts: string[] = [];
    const allKeys = new Set([...Object.keys(local || {}), ...Object.keys(server || {})]);
    
    for (const key of allKeys) {
      if (local?.[key] !== server?.[key]) {
        conflicts.push(key);
      }
    }
    
    return conflicts;
  }

  private inferConflictType(localChange: any, serverChange: any): ConflictType {
    if (localChange.status || serverChange.status) {
      return ConflictType.ATTENDANCE_STATUS;
    }
    if (localChange.operations && serverChange.operations) {
      return ConflictType.BULK_OPERATION;
    }
    if (localChange.student_id || serverChange.student_id) {
      return ConflictType.STUDENT_DATA;
    }
    if (localChange.timestamp || serverChange.timestamp) {
      return ConflictType.TIMESTAMP_CONFLICT;
    }
    return ConflictType.SESSION_CONFIG;
  }

  private getPreferredStrategy(conflict: ConflictData): ResolutionStrategy {
    switch (conflict.type) {
      case ConflictType.ATTENDANCE_STATUS:
        return ResolutionStrategy.LAST_WRITER_WINS;
      case ConflictType.STUDENT_DATA:
        return ResolutionStrategy.AUTO_MERGE;
      case ConflictType.BULK_OPERATION:
        return ResolutionStrategy.AUTO_MERGE;
      case ConflictType.TIMESTAMP_CONFLICT:
        return ResolutionStrategy.LAST_WRITER_WINS;
      default:
        return ResolutionStrategy.USER_GUIDED;
    }
  }

  private getFieldStrategy(fieldPath: string): ResolutionStrategy {
    const strategy = this.defaultStrategies.get(fieldPath);
    return strategy || ResolutionStrategy.LAST_WRITER_WINS;
  }

  private isAutoResolvable(strategy: ResolutionStrategy): boolean {
    return strategy !== ResolutionStrategy.USER_GUIDED;
  }

  private isLocalNewer(localValue: any, serverValue: any): boolean {
    // Try to extract timestamp information
    if (typeof localValue === 'object' && localValue.timestamp) {
      const serverTimestamp = typeof serverValue === 'object' ? serverValue.timestamp : 0;
      return localValue.timestamp > serverTimestamp;
    }
    
    // Default to false (prefer server)
    return false;
  }

  private mergeStrings(local: string, server: string, base?: string): string {
    // Simple string merge - could be enhanced with diff algorithms
    if (base) {
      if (local === base) return server;
      if (server === base) return local;
    }
    
    // For now, concatenate with separator
    return `${local} | ${server}`;
  }

  private mergeArrays(local: any[], server: any[]): any[] {
    // Merge arrays, removing duplicates
    return [...new Set([...local, ...server])];
  }

  private mergeBulkOperations(localOps: any[], serverOps: any[]): any[] {
    // Merge bulk operations by timestamp and deduplication
    const allOps = [...localOps, ...serverOps];
    
    // Remove duplicates based on operation id
    const uniqueOps = allOps.filter((op, index, arr) => 
      arr.findIndex(o => o.id === op.id) === index
    );
    
    // Sort by timestamp
    return uniqueOps.sort((a, b) => 
      (a.timestamp || 0) - (b.timestamp || 0)
    );
  }

  private async analyzeFieldConflicts(conflict: ConflictData): Promise<ConflictField[]> {
    const conflicts: ConflictField[] = [];
    
    for (const fieldPath of conflict.conflictFields) {
      const localValue = conflict.localVersion?.[fieldPath];
      const serverValue = conflict.serverVersion?.[fieldPath];
      const baseValue = conflict.baseVersion?.[fieldPath];
      
      const fieldConflict = await this.resolveFieldConflict(fieldPath, localValue, serverValue, baseValue);
      conflicts.push(fieldConflict);
    }
    
    return conflicts;
  }

  private async generateAlternativeSuggestions(conflict: ConflictData): Promise<ResolutionResult[]> {
    const suggestions: ResolutionResult[] = [];
    
    // Always offer "keep local" option
    suggestions.push({
      strategy: ResolutionStrategy.FIRST_WRITER_WINS,
      resolvedData: conflict.localVersion,
      requiresUserInput: false,
      conflicts: [],
      confidence: 60,
      explanation: 'Keep local changes'
    });
    
    // Always offer "keep server" option
    suggestions.push({
      strategy: ResolutionStrategy.LAST_WRITER_WINS,
      resolvedData: conflict.serverVersion,
      requiresUserInput: false,
      conflicts: [],
      confidence: 60,
      explanation: 'Keep server changes'
    });
    
    return suggestions;
  }
}

// Singleton instance
export const conflictResolver = new ConflictResolutionEngine();

export default conflictResolver;