#!/usr/bin/env python3
"""
Test script to verify the WebSocket attendance route is properly configured.
"""
import sys
import os

# Add the backend directory to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import app

def test_websocket_route_exists():
    """Test that the WebSocket attendance route is configured."""
    
    # Check if the route is in the FastAPI app routes
    websocket_routes = []
    all_routes = []
    
    for route in app.routes:
        if hasattr(route, 'path'):
            methods = "WS" if not hasattr(route, 'methods') else list(route.methods)[0] if route.methods else "WS"
            all_routes.append(f"{methods}: {route.path}")
            if '/ws/' in route.path:
                websocket_routes.append(route.path)
    
    print("WebSocket routes found:")
    for route in websocket_routes:
        print(f"  - {route}")
    
    if not websocket_routes:
        print("  (No WebSocket routes found)")
    
    # Verify our specific route exists
    expected_route = "/ws/attendance/{class_id}"
    route_exists = any(expected_route == route for route in websocket_routes)
    
    if route_exists:
        print(f"\nSUCCESS: WebSocket route {expected_route} is properly configured")
        return True
    else:
        print(f"\nFAILURE: WebSocket route {expected_route} not found")
        print("Available WebSocket routes:")
        for route in websocket_routes:
            print(f"  - {route}")
        return False

def test_websocket_endpoint_function_exists():
    """Test that the WebSocket endpoint function exists."""
    
    try:
        from main import attendance_websocket_endpoint
        print("SUCCESS: attendance_websocket_endpoint function exists")
        print(f"Function: {attendance_websocket_endpoint}")
        return True
    except ImportError:
        print("FAILURE: attendance_websocket_endpoint function not found")
        return False

def test_attendance_manager_import():
    """Test that attendance_ws_manager can be imported."""
    
    try:
        from main import attendance_ws_manager
        print(f"SUCCESS: attendance_ws_manager imported: {type(attendance_ws_manager)}")
        return True
    except ImportError as e:
        print(f"FAILURE: Could not import attendance_ws_manager: {e}")
        return False

def test_app_routes_inspection():
    """Debug: Inspect all app routes."""
    
    print("Inspecting FastAPI app routes:")
    for i, route in enumerate(app.routes):
        route_type = type(route).__name__
        path = getattr(route, 'path', 'No path')
        print(f"  {i+1}. {route_type}: {path}")
        if i > 15:  # Limit output
            print(f"  ... and {len(app.routes) - i - 1} more routes")
            break
    
    return True

def main():
    """Run all tests."""
    print("Testing WebSocket attendance route configuration...")
    print("=" * 60)
    
    test_results = []
    
    # Debug: Inspect all routes
    print("\n0. Inspecting all app routes...")
    test_app_routes_inspection()
    
    # Test 1: Route exists
    print("\n1. Testing route configuration...")
    test_results.append(test_websocket_route_exists())
    
    # Test 2: Endpoint function exists
    print("\n2. Testing endpoint function...")
    test_results.append(test_websocket_endpoint_function_exists())
    
    # Test 3: Manager import works
    print("\n3. Testing attendance manager import...")
    test_results.append(test_attendance_manager_import())
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    passed = sum(test_results)
    total = len(test_results)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("All tests PASSED - WebSocket route is properly configured!")
        return 0
    else:
        print("Some tests FAILED - check configuration")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)