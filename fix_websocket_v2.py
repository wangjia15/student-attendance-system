#!/usr/bin/env python3

# Script to properly add WebSocket imports and broadcasts to attendance.py

def fix_attendance_file():
    with open('backend/app/api/v1/attendance.py', 'r') as f:
        lines = f.readlines()
    
    new_lines = []
    
    # First pass: Add imports
    for i, line in enumerate(lines):
        new_lines.append(line)
        
        # Add WebSocket import after attendance_engine import
        if 'from app.services.attendance_engine import AttendanceEngine' in line:
            new_lines.append('from app.core.websocket import websocket_server, MessageType\n')
        
        # Add AttendanceStatusUpdate to imports
        if line.strip() == 'AttendancePatternRequest':
            new_lines[-1] = line.replace('AttendancePatternRequest', 'AttendancePatternRequest, AttendanceStatusUpdate')
    
    # Second pass: Add WebSocket broadcasts
    final_lines = []
    i = 0
    while i < len(new_lines):
        line = new_lines[i]
        final_lines.append(line)
        
        # Check if this is the line before a return StudentJoinResponse with success=True
        if (line.strip() == '' and 
            i + 1 < len(new_lines) and 
            'return StudentJoinResponse(' in new_lines[i + 1] and
            i + 2 < len(new_lines) and 
            'success=True' in new_lines[i + 2]):
            
            # Check if we're in QR function (look back for function definition)
            in_qr_function = False
            in_verification_function = False
            
            for j in range(i, max(0, i - 100), -1):
                if 'def student_check_in_qr(' in new_lines[j]:
                    in_qr_function = True
                    break
                elif 'def student_check_in_code(' in new_lines[j]:
                    in_verification_function = True
                    break
                elif new_lines[j].strip().startswith('def ') and not ('student_check_in' in new_lines[j]):
                    break
            
            # Insert appropriate WebSocket broadcast
            if in_qr_function:
                websocket_code = '''
        # WebSocket broadcast for attendance created
        try:
            await websocket_server.broadcast_to_class(
                str(session.id),
                MessageType.STUDENT_JOINED,
                {
                    "student_id": current_user.id,
                    "student_name": current_user.full_name or current_user.username,
                    "class_session_id": session.id,
                    "class_name": session.name,
                    "attendance_status": attendance_record.status.value,
                    "check_in_time": attendance_record.check_in_time.isoformat() if attendance_record.check_in_time else None,
                    "is_late": attendance_record.is_late,
                    "late_minutes": attendance_record.late_minutes,
                    "verification_method": "qr_code"
                }
            )
        except Exception as ws_error:
            logger.error(f"WebSocket broadcast failed: {ws_error}")
            # Continue with response even if WebSocket fails

'''
                final_lines.append(websocket_code)
            elif in_verification_function:
                websocket_code = '''
        # WebSocket broadcast for attendance created
        try:
            await websocket_server.broadcast_to_class(
                str(session.id),
                MessageType.STUDENT_JOINED,
                {
                    "student_id": current_user.id,
                    "student_name": current_user.full_name or current_user.username,
                    "class_session_id": session.id,
                    "class_name": session.name,
                    "attendance_status": attendance_record.status.value,
                    "check_in_time": attendance_record.check_in_time.isoformat() if attendance_record.check_in_time else None,
                    "is_late": attendance_record.is_late,
                    "late_minutes": attendance_record.late_minutes,
                    "verification_method": "verification_code"
                }
            )
        except Exception as ws_error:
            logger.error(f"WebSocket broadcast failed: {ws_error}")
            # Continue with response even if WebSocket fails

'''
                final_lines.append(websocket_code)
        
        i += 1
    
    # Write back the file
    with open('backend/app/api/v1/attendance.py', 'w') as f:
        f.writelines(final_lines)
    
    print("Successfully added WebSocket imports and broadcasts")

if __name__ == "__main__":
    fix_attendance_file()