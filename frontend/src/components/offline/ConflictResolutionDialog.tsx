/**
 * Conflict Resolution Dialog Component
 * 
 * Provides user interface for resolving sync conflicts:
 * - Visual comparison of local vs server changes
 * - Multiple resolution strategies
 * - Batch conflict resolution
 * - Preview of resolution effects
 * - Conflict history and audit trail
 */

import React, { useState, useEffect } from 'react';
import { useConflictState, useSyncStore } from '../../store/sync';
import { ConflictData, ResolutionResult } from '../../utils/conflict-resolution';

interface ConflictResolutionDialogProps {
  isOpen: boolean;
  onClose: () => void;
  conflicts?: ConflictData[];
  onResolve?: (resolution: ResolutionResult) => void;
}

const ConflictResolutionDialog: React.FC<ConflictResolutionDialogProps> = ({
  isOpen,
  onClose,
  conflicts: propConflicts,
  onResolve
}) => {
  const { activeConflicts } = useConflictState();
  const { handleConflictResolution } = useSyncStore();
  
  const [currentConflictIndex, setCurrentConflictIndex] = useState(0);
  const [selectedStrategy, setSelectedStrategy] = useState<string>('auto_merge');
  const [resolvedData, setResolvedData] = useState<any>(null);
  const [userNotes, setUserNotes] = useState('');
  const [showPreview, setShowPreview] = useState(false);
  const [isResolving, setIsResolving] = useState(false);
  
  const conflicts = propConflicts || activeConflicts;
  const currentConflict = conflicts[currentConflictIndex];
  
  useEffect(() => {
    if (currentConflict && selectedStrategy === 'auto_merge') {
      generateAutoResolution();
    }
  }, [currentConflict, selectedStrategy]);
  
  const generateAutoResolution = () => {
    if (!currentConflict) return;
    
    // Simple auto-resolution logic
    const { localVersion, serverVersion } = currentConflict;
    
    // Merge non-conflicting fields
    const merged = { ...serverVersion };
    
    Object.keys(localVersion || {}).forEach(key => {
      if (!(key in (serverVersion || {}))) {
        merged[key] = localVersion[key];
      }
    });
    
    setResolvedData(merged);
  };
  
  const handleStrategyChange = (strategy: string) => {
    setSelectedStrategy(strategy);
    
    switch (strategy) {
      case 'local_wins':
        setResolvedData(currentConflict?.localVersion);
        break;
      case 'server_wins':
        setResolvedData(currentConflict?.serverVersion);
        break;
      case 'user_guided':
        setResolvedData(currentConflict?.serverVersion);
        break;
      default:
        generateAutoResolution();
    }
  };
  
  const handleResolve = async () => {
    if (!currentConflict) return;
    
    setIsResolving(true);
    
    try {
      const resolution: ResolutionResult = {
        strategy: selectedStrategy as any,
        resolvedData,
        requiresUserInput: selectedStrategy === 'user_guided',
        conflicts: [],
        confidence: selectedStrategy === 'auto_merge' ? 70 : 95,
        explanation: userNotes || `Resolved using ${selectedStrategy} strategy`
      };
      
      await handleConflictResolution(currentConflict);
      
      if (onResolve) {
        onResolve(resolution);
      }
      
      // Move to next conflict or close
      if (currentConflictIndex < conflicts.length - 1) {
        setCurrentConflictIndex(currentConflictIndex + 1);
        setUserNotes('');
      } else {
        onClose();
      }
      
    } catch (error) {
      console.error('Failed to resolve conflict:', error);
      // Show error message
    } finally {
      setIsResolving(false);
    }
  };
  
  const handleSkip = () => {
    if (currentConflictIndex < conflicts.length - 1) {
      setCurrentConflictIndex(currentConflictIndex + 1);
      setUserNotes('');
    } else {
      onClose();
    }
  };
  
  const formatValue = (value: any): string => {
    if (value === null || value === undefined) return 'null';
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    return String(value);
  };
  
  const renderFieldComparison = (field: string, localValue: any, serverValue: any) => {
    const isDifferent = JSON.stringify(localValue) !== JSON.stringify(serverValue);
    
    return (
      <div key={field} className={`border rounded p-3 ${isDifferent ? 'border-orange-200 bg-orange-50' : 'border-gray-200'}`}>
        <div className="font-medium text-sm text-gray-700 mb-2">{field}</div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-gray-500 mb-1">Local (Your Changes)</div>
            <div className={`text-sm p-2 rounded ${isDifferent ? 'bg-blue-100' : 'bg-gray-100'}`}>
              <pre className="whitespace-pre-wrap font-mono text-xs">
                {formatValue(localValue)}
              </pre>
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1">Server (Current)</div>
            <div className={`text-sm p-2 rounded ${isDifferent ? 'bg-red-100' : 'bg-gray-100'}`}>
              <pre className="whitespace-pre-wrap font-mono text-xs">
                {formatValue(serverValue)}
              </pre>
            </div>
          </div>
        </div>
      </div>
    );
  };
  
  if (!isOpen || !currentConflict) {
    return null;
  }
  
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="bg-gray-50 dark:bg-gray-700 px-6 py-4 border-b">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                Resolve Sync Conflict
              </h2>
              <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
                Conflict {currentConflictIndex + 1} of {conflicts.length} • {currentConflict.type}
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
            >
              ✕
            </button>
          </div>
          
          {/* Progress indicator */}
          <div className="mt-4">
            <div className="w-full bg-gray-200 dark:bg-gray-600 rounded-full h-2">
              <div 
                className="bg-blue-500 h-2 rounded-full transition-all"
                style={{ width: `${((currentConflictIndex + 1) / conflicts.length) * 100}%` }}
              />
            </div>
          </div>
        </div>
        
        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]">
          {/* Conflict description */}
          <div className="mb-6">
            <h3 className="font-medium text-gray-900 dark:text-white mb-2">Conflict Details</h3>
            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded p-4">
              <div className="text-sm">
                <div className="font-medium text-yellow-800 dark:text-yellow-200 mb-1">
                  Entity: {currentConflict.entityId}
                </div>
                <div className="text-yellow-700 dark:text-yellow-300">
                  Conflict occurred at: {new Date(currentConflict.timestamp).toLocaleString()}
                </div>
                {currentConflict.conflictFields && currentConflict.conflictFields.length > 0 && (
                  <div className="text-yellow-700 dark:text-yellow-300 mt-2">
                    Conflicting fields: {currentConflict.conflictFields.join(', ')}
                  </div>
                )}
              </div>
            </div>
          </div>
          
          {/* Field comparison */}
          <div className="mb-6">
            <h3 className="font-medium text-gray-900 dark:text-white mb-3">Data Comparison</h3>
            <div className="space-y-3">
              {currentConflict.conflictFields && currentConflict.conflictFields.length > 0 ? (
                currentConflict.conflictFields.map(field => 
                  renderFieldComparison(
                    field,
                    currentConflict.localVersion?.[field],
                    currentConflict.serverVersion?.[field]
                  )
                )
              ) : (
                renderFieldComparison(
                  'Full Record',
                  currentConflict.localVersion,
                  currentConflict.serverVersion
                )
              )}
            </div>
          </div>
          
          {/* Resolution strategy */}
          <div className="mb-6">
            <h3 className="font-medium text-gray-900 dark:text-white mb-3">Resolution Strategy</h3>
            <div className="space-y-2">
              <label className="flex items-center">
                <input
                  type="radio"
                  name="strategy"
                  value="auto_merge"
                  checked={selectedStrategy === 'auto_merge'}
                  onChange={(e) => handleStrategyChange(e.target.value)}
                  className="mr-2"
                />
                <span className="text-sm">Auto-merge (recommended)</span>
              </label>
              <label className="flex items-center">
                <input
                  type="radio"
                  name="strategy"
                  value="local_wins"
                  checked={selectedStrategy === 'local_wins'}
                  onChange={(e) => handleStrategyChange(e.target.value)}
                  className="mr-2"
                />
                <span className="text-sm">Keep my changes</span>
              </label>
              <label className="flex items-center">
                <input
                  type="radio"
                  name="strategy"
                  value="server_wins"
                  checked={selectedStrategy === 'server_wins'}
                  onChange={(e) => handleStrategyChange(e.target.value)}
                  className="mr-2"
                />
                <span className="text-sm">Keep server changes</span>
              </label>
              <label className="flex items-center">
                <input
                  type="radio"
                  name="strategy"
                  value="user_guided"
                  checked={selectedStrategy === 'user_guided'}
                  onChange={(e) => handleStrategyChange(e.target.value)}
                  className="mr-2"
                />
                <span className="text-sm">Custom resolution</span>
              </label>
            </div>
          </div>
          
          {/* Preview */}
          {showPreview && resolvedData && (
            <div className="mb-6">
              <h3 className="font-medium text-gray-900 dark:text-white mb-3">Resolution Preview</h3>
              <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded p-4">
                <pre className="whitespace-pre-wrap font-mono text-xs text-green-800 dark:text-green-200">
                  {JSON.stringify(resolvedData, null, 2)}
                </pre>
              </div>
            </div>
          )}
          
          {/* User notes */}
          <div className="mb-6">
            <h3 className="font-medium text-gray-900 dark:text-white mb-3">Notes (optional)</h3>
            <textarea
              value={userNotes}
              onChange={(e) => setUserNotes(e.target.value)}
              placeholder="Add any notes about this resolution..."
              className="w-full p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
              rows={3}
            />
          </div>
          
          {/* Custom resolution editor */}
          {selectedStrategy === 'user_guided' && (
            <div className="mb-6">
              <h3 className="font-medium text-gray-900 dark:text-white mb-3">Custom Resolution</h3>
              <textarea
                value={JSON.stringify(resolvedData, null, 2)}
                onChange={(e) => {
                  try {
                    setResolvedData(JSON.parse(e.target.value));
                  } catch (err) {
                    // Invalid JSON, keep the text for user to fix
                  }
                }}
                className="w-full p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white font-mono text-sm"
                rows={10}
              />
              <p className="text-xs text-gray-500 mt-1">
                Edit the JSON above to create your custom resolution
              </p>
            </div>
          )}
        </div>
        
        {/* Footer */}
        <div className="bg-gray-50 dark:bg-gray-700 px-6 py-4 border-t flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <button
              onClick={() => setShowPreview(!showPreview)}
              className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              {showPreview ? 'Hide' : 'Show'} Preview
            </button>
          </div>
          
          <div className="flex items-center space-x-3">
            <button
              onClick={handleSkip}
              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-800 dark:hover:text-white"
            >
              Skip This Conflict
            </button>
            <button
              onClick={handleResolve}
              disabled={isResolving || !resolvedData}
              className="px-6 py-2 bg-blue-500 text-white text-sm rounded-md hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center space-x-2"
            >
              {isResolving && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />}
              <span>{isResolving ? 'Resolving...' : 'Resolve Conflict'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConflictResolutionDialog;