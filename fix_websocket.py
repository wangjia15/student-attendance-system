#!/usr/bin/env python3

# Script to properly add WebSocket broadcasts to attendance.py

def fix_attendance_file():
    with open('backend/app/api/v1/attendance.py', 'r') as f:
        lines = f.readlines()
    
    # WebSocket broadcast code for QR check-in
    websocket_code_qr = """
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

"""
    
    # WebSocket broadcast code for verification code check-in
    websocket_code_verification = """
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

"""
    
    new_lines = []
    qr_inserted = False
    verification_inserted = False
    in_qr_function = False
    in_verification_function = False
    
    i = 0
    while i < len(lines):
        line = lines[i]
        new_lines.append(line)
        
        # Track which function we're in
        if 'def student_check_in_qr(' in line:
            in_qr_function = True
            in_verification_function = False
        elif 'def student_check_in_code(' in line:
            in_qr_function = False
            in_verification_function = True
        elif line.strip().startswith('def ') and not ('student_check_in' in line):
            in_qr_function = False
            in_verification_function = False
        
        # Insert WebSocket broadcast before return statements
        if (line.strip() == 'return StudentJoinResponse(' and 
            i + 1 < len(lines) and 
            'success=True' in lines[i + 1]):
            
            if in_qr_function and not qr_inserted:
                new_lines.insert(-1, websocket_code_qr)
                qr_inserted = True
            elif in_verification_function and not verification_inserted:
                new_lines.insert(-1, websocket_code_verification)
                verification_inserted = True
        
        i += 1
    
    # Write back the file
    with open('backend/app/api/v1/attendance.py', 'w') as f:
        f.writelines(new_lines)
    
    print(f"Inserted WebSocket broadcasts: QR={qr_inserted}, Verification={verification_inserted}")

if __name__ == "__main__":
    fix_attendance_file()