# Helper function to be added to attendance.py

async def broadcast_attendance_update(
    session_id: int,
    session_name: str,
    attendance_record,
    student_name: str,
    verification_method: str,
    is_new_record: bool = True
):
    """
    Broadcast attendance update via WebSocket.
    Safe to call - will not affect API performance if it fails.
    """
    try:
        message_type = MessageType.STUDENT_JOINED if is_new_record else MessageType.ATTENDANCE_UPDATE
        
        await websocket_server.broadcast_to_class(
            str(session_id),
            message_type,
            {
                "student_id": attendance_record.student_id,
                "student_name": student_name,
                "class_session_id": session_id,
                "class_name": session_name,
                "attendance_status": attendance_record.status.value,
                "check_in_time": attendance_record.check_in_time.isoformat() if attendance_record.check_in_time else None,
                "is_late": attendance_record.is_late,
                "late_minutes": attendance_record.late_minutes,
                "verification_method": verification_method,
                "is_manual_override": getattr(attendance_record, 'is_manual_override', False),
                "override_reason": getattr(attendance_record, 'override_reason', None),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        logger.info(f"Successfully broadcast attendance update for student {attendance_record.student_id} in class {session_id}")
    except Exception as ws_error:
        logger.error(f"WebSocket broadcast failed for attendance update: {ws_error}")
        # Continue - WebSocket failures should not affect REST API responses