#!/usr/bin/env python3
"""
Final script to add clean WebSocket integration to attendance.py
"""

def add_websocket_integration():
    with open('backend/app/api/v1/attendance.py', 'r') as f:
        content = f.read()
    
    # 1. Add imports after the attendance_engine import
    imports_to_add = "from app.core.websocket import websocket_server, MessageType"
    if imports_to_add not in content:
        content = content.replace(
            "from app.services.attendance_engine import AttendanceEngine",
            f"from app.services.attendance_engine import AttendanceEngine\n{imports_to_add}"
        )
    
    # 2. Add AttendanceStatusUpdate to schema imports
    content = content.replace(
        "AttendancePatternRequest\n)",
        "AttendancePatternRequest, AttendanceStatusUpdate\n)"
    )
    
    # 3. Add WebSocket broadcasts after successful operations
    
    # For QR check-in (after await db.refresh(attendance_record))
    qr_checkin_pattern = """        await db.refresh(attendance_record)
        
        status_message = "Successfully checked in\""""
    
    qr_checkin_replacement = """        await db.refresh(attendance_record)
        
        # WebSocket broadcast for QR check-in
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
        except Exception as e:
            logger.error(f"WebSocket broadcast failed: {e}")
        
        status_message = "Successfully checked in\""""
    
    # Apply QR check-in WebSocket only to first occurrence
    if qr_checkin_pattern in content:
        content = content.replace(qr_checkin_pattern, qr_checkin_replacement, 1)
    
    # For verification code check-in (second occurrence)
    # Find the second pattern by looking after the QR function
    verification_parts = content.split('def student_check_in_code(')
    if len(verification_parts) > 1:
        verification_function = verification_parts[1]
        if qr_checkin_pattern in verification_function:
            verification_replacement = """        await db.refresh(attendance_record)
        
        # WebSocket broadcast for verification code check-in
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
        except Exception as e:
            logger.error(f"WebSocket broadcast failed: {e}")
        
        status_message = "Successfully checked in\""""
            
            verification_function_updated = verification_function.replace(qr_checkin_pattern, verification_replacement, 1)
            content = verification_parts[0] + 'def student_check_in_code(' + verification_function_updated
    
    # For teacher override
    override_pattern = """        await db.refresh(attendance_record)
        
        return {"""
    
    override_replacement = """        await db.refresh(attendance_record)
        
        # WebSocket broadcast for teacher override
        try:
            await websocket_server.broadcast_to_class(
                str(class_session_id),
                MessageType.ATTENDANCE_UPDATE,
                {
                    "student_id": override_data.student_id,
                    "class_session_id": class_session_id,
                    "attendance_status": attendance_record.status.value,
                    "is_manual_override": True,
                    "override_reason": override_data.reason,
                    "updated_by": current_user.full_name or current_user.username,
                    "verification_method": "teacher_override"
                }
            )
        except Exception as e:
            logger.error(f"WebSocket broadcast failed: {e}")
        
        return {"""
    
    if override_pattern in content:
        content = content.replace(override_pattern, override_replacement)
    
    # For bulk operations
    bulk_pattern = """        await db.commit()
        
        return BulkAttendanceResponse("""
    
    bulk_replacement = """        await db.commit()
        
        # WebSocket broadcast for bulk operation
        try:
            await websocket_server.broadcast_to_class(
                str(bulk_data.class_session_id),
                MessageType.ATTENDANCE_UPDATE,
                {
                    "bulk_operation": bulk_data.operation.value,
                    "class_session_id": bulk_data.class_session_id,
                    "processed_count": result["processed_count"],
                    "failed_count": result["failed_count"],
                    "updated_by": current_user.full_name or current_user.username,
                    "reason": bulk_data.reason
                }
            )
        except Exception as e:
            logger.error(f"WebSocket broadcast failed: {e}")
        
        return BulkAttendanceResponse("""
    
    if bulk_pattern in content:
        content = content.replace(bulk_pattern, bulk_replacement)
    
    # Write the updated content
    with open('backend/app/api/v1/attendance.py', 'w') as f:
        f.write(content)
    
    print("Successfully added clean WebSocket integration to attendance.py")

if __name__ == "__main__":
    add_websocket_integration()