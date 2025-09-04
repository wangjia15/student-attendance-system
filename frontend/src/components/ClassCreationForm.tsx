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
    name: '',
    description: '',
    subject: '',
    location: '',
    duration_minutes: 30,
    allow_late_join: true,
    require_verification: true,
    auto_end_minutes: 120
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
          name: parsed.name || '',
          subject: parsed.subject || '',
          location: parsed.location || ''
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
        name: template.name,
        subject: template.subject,
        duration_minutes: template.defaultDuration,
        auto_end_minutes: template.defaultDuration + 30
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
      if (!formData.name.trim()) {
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
            value={formData.name}
            onChange={(e) => handleInputChange('name', e.target.value)}
            placeholder="Enter class name"
            maxLength={100}
            required
          />
        </div>
        
        {/* Description */}
        <div className="form-group">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            value={formData.description || ''}
            onChange={(e) => handleInputChange('description', e.target.value)}
            placeholder="Enter class description (optional)"
            maxLength={500}
            rows={2}
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
        
        {/* Location */}
        <div className="form-group">
          <label htmlFor="location">Location</label>
          <input
            id="location"
            type="text"
            value={formData.location || ''}
            onChange={(e) => handleInputChange('location', e.target.value)}
            placeholder="Enter location (optional)"
            maxLength={100}
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
              value={formData.duration_minutes || 30}
              onChange={(e) => handleInputChange('duration_minutes', parseInt(e.target.value))}
            />
            <span className="duration-display">{formData.duration_minutes || 30} minutes</span>
          </div>
        </div>
        
        {/* Auto End Duration */}
        <div className="form-group">
          <label htmlFor="autoEnd">Auto-end After</label>
          <div className="duration-control">
            <input
              id="autoEnd"
              type="range"
              min="30"
              max="480"
              value={formData.auto_end_minutes}
              onChange={(e) => handleInputChange('auto_end_minutes', parseInt(e.target.value))}
            />
            <span className="duration-display">{formData.auto_end_minutes} minutes</span>
          </div>
        </div>

        {/* Require Verification */}
        <div className="form-group checkbox-group">
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={formData.require_verification}
              onChange={(e) => handleInputChange('require_verification', e.target.checked)}
            />
            <span className="checkmark"></span>
            Require verification code entry
          </label>
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
            disabled={isCreating || !formData.name.trim()}
          >
            {isCreating ? 'Creating...' : 'Create Class Session'}
          </button>
        </div>
      </form>
    </div>
  );
};