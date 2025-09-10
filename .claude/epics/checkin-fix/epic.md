---
name: checkin-fix
status: backlog
created: 2025-09-09T14:39:18Z
progress: 12%
prd: .claude/prds/checkin-fix.md
github: https://github.com/wangjia15/student-attendance-system/issues/10
---

# Epic: Check-in Fix

## Overview

This epic fixes critical real-time attendance issues by leveraging the existing comprehensive WebSocket infrastructure (90% complete) with minimal integration work. The solution enables production WebSocket endpoints, connects attendance APIs to real-time broadcasts, and separates enrollment from daily check-in workflows. The approach maximizes code reuse while delivering immediate value to teachers and students.

## Architecture Decisions

- **Leverage Existing WebSocket Infrastructure**: Enable the production-grade `websocket_server` already built but commented out in main.py
- **Reuse Attendance-Specific Components**: Utilize existing `attendance_ws_manager` and role-based connection handling
- **Minimal API Changes**: Add WebSocket broadcasts to existing attendance endpoints rather than rebuilding APIs
- **Frontend State Continuity**: Build on existing Zustand store and optimistic updates infrastructure
- **Database Schema Preservation**: Work with current attendance/enrollment models, adding clarity through API separation

## Technical Approach

### Frontend Components
**Leverage Existing Infrastructure:**
- Zustand store with attendance state management ✅ (already exists)
- WebSocket connection hooks and error handling ✅ (already exists)  
- Optimistic UI updates ✅ (already exists)

**Minimal Updates Required:**
- Update WebSocket connection URL from `/ws/attendance` to `/ws/attendance/{class_id}`
- Add connection status indicators to AttendanceDashboard
- Separate enrollment UI flow from daily check-in in StudentDashboard

### Backend Services
**Enable Production WebSocket:**
- Uncomment production WebSocket server in main.py (15 lines)
- Add `/ws/attendance/{class_id}` route using existing `attendance_ws_manager`

**API Integration:**
- Add WebSocket broadcast calls to attendance POST endpoints
- Enhance verification code validation in class joining endpoint
- Separate enrollment success messages from check-in confirmations

**Data Models:**
- Current attendance/class_session models are sufficient
- Add database indexes for performance optimization
- Enhance error handling for concurrent attendance updates

### Infrastructure
- **Deployment**: No additional infrastructure changes required
- **Scaling**: Existing WebSocket connection pooling handles 100+ students per class
- **Monitoring**: Reuse existing FastAPI logging and error tracking

## Implementation Strategy

### Development Approach
1. **Incremental Rollout**: Enable WebSocket features progressively to minimize risk
2. **Backward Compatibility**: Maintain current functionality while adding real-time features
3. **Testing-First**: Use existing test infrastructure with Playwright integration
4. **Performance Monitoring**: Leverage existing metrics to validate 2-second update requirements

### Risk Mitigation
- **WebSocket Reliability**: Built-in reconnection logic already exists
- **Database Performance**: Add targeted indexes for attendance queries
- **Browser Compatibility**: Use existing progressive enhancement patterns
- **Concurrent Updates**: Implement optimistic locking for attendance records

## Task Breakdown Preview

High-level task categories (8 total tasks to keep implementation minimal):

- [ ] **Backend WebSocket Integration**: Enable production WebSocket server and add attendance-specific routes
- [ ] **API Enhancement**: Add WebSocket broadcasts to attendance endpoints and separate enrollment logic
- [ ] **Frontend WebSocket Updates**: Update connection URLs and add connection status indicators  
- [ ] **UI Flow Separation**: Clarify enrollment vs check-in workflows in student interface
- [ ] **Database Optimization**: Add performance indexes and enhance concurrent update handling
- [ ] **Error Handling Enhancement**: Improve validation and user feedback for verification codes
- [ ] **Playwright Test Suite**: Create comprehensive end-to-end tests for critical flows
- [ ] **Performance Validation**: Validate real-time update latency and connection reliability

## Dependencies

### External Service Dependencies
- **Browser WebSocket Support**: Standard WebSocket API (universally supported)
- **Database Performance**: SQLite concurrent read/write capabilities (existing)

### Internal Team Dependencies
- **Frontend Team**: React component updates (minimal changes to existing components)
- **Backend Team**: WebSocket integration and API enhancements (leveraging existing infrastructure)
- **QA Team**: Playwright test development and execution

### Prerequisite Work
- None - all required infrastructure already exists in codebase

## Success Criteria (Technical)

### Performance Benchmarks
- **Real-time Update Latency**: 95% of updates delivered within 2 seconds
- **WebSocket Connection Reliability**: 99% uptime during class hours
- **Dashboard Load Time**: < 3 seconds for teacher attendance dashboard
- **Concurrent User Support**: Handle 100+ students per class session

### Quality Gates
- **Test Coverage**: 100% of critical attendance flows covered by Playwright tests
- **Error Handling**: Clear user feedback for all failure scenarios
- **Mobile Compatibility**: Full functionality maintained on touch devices
- **Data Integrity**: Zero attendance record corruption under concurrent access

### Acceptance Criteria
- Teachers see real-time attendance updates without page refresh
- Students successfully join classes using verification codes (98% success rate)
- Enrolled students appear in teacher dashboards immediately
- WebSocket connections recover automatically from network interruptions
- All critical user journeys pass Playwright validation

## Estimated Effort

### Overall Timeline Estimate
**3 weeks total** (reduced from 4 weeks due to extensive existing infrastructure)

- **Week 1**: Backend WebSocket integration and API enhancements (Tasks 1-2)
- **Week 2**: Frontend updates and UI flow improvements (Tasks 3-4)  
- **Week 3**: Database optimization, testing, and validation (Tasks 5-8)

### Resource Requirements
- **1 Full-stack Developer**: Primary implementation
- **0.5 QA Engineer**: Playwright test development and execution
- **0.25 DevOps**: Performance monitoring and deployment validation

### Critical Path Items
1. **WebSocket Server Activation**: Foundational for all real-time features
2. **API-WebSocket Integration**: Core functionality delivery
3. **Frontend Connection Updates**: User-visible improvements
4. **End-to-End Testing**: Quality assurance and deployment readiness

**Risk Factors**: None significant due to extensive existing infrastructure. Main risk is minor configuration issues during WebSocket server activation, mitigated by comprehensive error logging already in place.

## Tasks Created
- [ ] #11 -  (parallel: false)
- [ ] #12 -  (parallel: false)
- [ ] #13 -  (parallel: true)
- [ ] #14 -  (parallel: )
- [ ] #15 -  (parallel: )
- [ ] #16 -  (parallel: )
- [ ] #17 -  (parallel: )
- [ ] #18 -  (parallel: )

Total tasks: 8
Parallel tasks: 1
Sequential tasks: 7
Estimated total effort: 42 hours (just over 1 week full-time)
