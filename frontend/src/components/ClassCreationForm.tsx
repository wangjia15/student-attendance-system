import React, { useState, useEffect } from 'react';
import { ClassSessionCreate, ClassSessionResponse } from '../types/api';
import { createClassSession } from '../services/api';
import './ClassCreationForm.css';

interface ClassCreationFormProps {
  onSessionCreated: (session: ClassSessionResponse) => void;
  onCancel?: () => void;
}

interface ClassTemplate {
  id: string;
  name: string;
  subject: string;
  defaultDuration: number;
  maxStudents?: number;
}

const DEFAULT_TEMPLATES: ClassTemplate[] = [
  { id: 'math', name: 'Mathematics', subject: 'Math', defaultDuration: 45, maxStudents: 30 },
  { id: 'english', name: 'English Literature', subject: 'English', defaultDuration: 50, maxStudents: 25 },
  { id: 'science', name: 'Science Lab', subject: 'Science', defaultDuration: 90, maxStudents: 20 },
  { id: 'history', name: 'History', subject: 'History', defaultDuration: 45, maxStudents: 35 },
  { id: 'custom', name: 'Custom Class', subject: '', defaultDuration: 30 }
];

export const ClassCreationForm: React.FC<ClassCreationFormProps> = ({
  onSessionCreated,
  onCancel
}) => {
  const [formData, setFormData] = useState<ClassSessionCreate>({
    class_name: '',
    subject: '',
    expiration_minutes: 30,
    max_students: undefined,
    allow_late_join: true
  });
  
  const [selectedTemplate, setSelectedTemplate] = useState<string>('');
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string>('');

  // Load previous form data from localStorage for auto-completion
  useEffect(() => {
    const savedFormData = localStorage.getItem('lastClassData');
    if (savedFormData) {
      try {
        const parsed = JSON.parse(savedFormData);
        setFormData(prev => ({
          ...prev,
          class_name: parsed.class_name || '',
          subject: parsed.subject || '',
          max_students: parsed.max_students
        }));
      } catch (e) {
        // Ignore parsing errors
      }
    }
  }, []);

  const handleTemplateSelect = (templateId: string) => {
    const template = DEFAULT_TEMPLATES.find(t => t.id === templateId);
    if (template) {
      setSelectedTemplate(templateId);
      setFormData(prev => ({
        ...prev,
        class_name: template.name,
        subject: template.subject,
        expiration_minutes: template.defaultDuration,
        max_students: template.maxStudents
      }));
    }
  };

  const handleInputChange = (
    field: keyof ClassSessionCreate,
    value: string | number | boolean
  ) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
    setSelectedTemplate(''); // Clear template selection when manually editing
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsCreating(true);
    setError('');

    try {
      // Validate form
      if (!formData.class_name.trim()) {
        throw new Error('Class name is required');
      }

      // Save form data for future auto-completion
      localStorage.setItem('lastClassData', JSON.stringify(formData));

      // Create session
      const session = await createClassSession(formData);
      onSessionCreated(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create class');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="class-creation-form">
      <div className="form-header">
        <h2>Create Class Session</h2>
        <p className="subtitle">Set up attendance tracking in under 15 seconds</p>
      </div>

      {/* Quick Templates */}
      <div className="template-section">
        <h3>Quick Start Templates</h3>
        <div className="template-grid">
          {DEFAULT_TEMPLATES.map(template => (
            <button
              key={template.id}
              type="button"
              className={`template-card ${selectedTemplate === template.id ? 'selected' : ''}`}
              onClick={() => handleTemplateSelect(template.id)}
            >
              <div className="template-name">{template.name}</div>
              <div className="template-details">
                {template.subject && <span>{template.subject}</span>}
                <span>{template.defaultDuration}min</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="creation-form">
        {/* Class Name */}
        <div className="form-group">
          <label htmlFor="className">Class Name *</label>
          <input
            id="className"
            type="text"
            value={formData.class_name}
            onChange={(e) => handleInputChange('class_name', e.target.value)}
            placeholder="Enter class name"
            maxLength={100}
            required
          />
        </div>

        {/* Subject */}
        <div className="form-group">
          <label htmlFor="subject">Subject</label>
          <input
            id="subject"
            type="text"
            value={formData.subject || ''}
            onChange={(e) => handleInputChange('subject', e.target.value)}
            placeholder="Enter subject (optional)"
            maxLength={50}
          />
        </div>

        {/* Duration */}
        <div className="form-group">
          <label htmlFor="duration">Session Duration</label>
          <div className="duration-control">
            <input
              id="duration"
              type="range"
              min="5"
              max="180"
              value={formData.expiration_minutes}
              onChange={(e) => handleInputChange('expiration_minutes', parseInt(e.target.value))}
            />
            <span className="duration-display">{formData.expiration_minutes} minutes</span>
          </div>
        </div>

        {/* Max Students */}
        <div className="form-group">
          <label htmlFor="maxStudents">Maximum Students (optional)</label>
          <input
            id="maxStudents"
            type="number"
            value={formData.max_students || ''}
            onChange={(e) => handleInputChange('max_students', 
              e.target.value ? parseInt(e.target.value) : undefined
            )}
            placeholder="No limit"
            min="1"
            max="500"
          />
        </div>

        {/* Allow Late Join */}
        <div className="form-group checkbox-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={formData.allow_late_join}
              onChange={(e) => handleInputChange('allow_late_join', e.target.checked)}
            />
            <span className="checkmark"></span>
            Allow students to join after session starts
          </label>
        </div>

        {/* Error Display */}
        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        {/* Action Buttons */}
        <div className="form-actions">
          {onCancel && (
            <button
              type="button"
              className="cancel-button"
              onClick={onCancel}
              disabled={isCreating}
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            className="create-button"
            disabled={isCreating || !formData.class_name.trim()}
          >
            {isCreating ? 'Creating...' : 'Create Class Session'}
          </button>
        </div>
      </form>
    </div>
  );
};