"""
Test API response to debug the frontend issue
"""
import asyncio
import aiohttp
import json


async def test_api():
    """Test the API endpoints that frontend is calling."""
    
    # Use the token from frontend's localStorage
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwicm9sZSI6InRlYWNoZXIiLCJleHAiOjE3NTc0MDY1NDMsImlhdCI6MTc1NzQwNDc0MywidHlwZSI6ImFjY2VzcyJ9.tx3vZDNNGtriWAIBcCWZNf14I-wb4YtlgGXjC6SgfE8"
    print(f"=== Using token from frontend ===")
    print(f"Token: {token[:50]}...")
    
    async with aiohttp.ClientSession() as session:
        try:
            
            # Test getting classes list
            print(f"\n=== Testing Classes List API ===")
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            async with session.get(
                'http://localhost:8000/api/v1/classes/',
                headers=headers
            ) as response:
                if response.status == 200:
                    classes = await response.json()
                    print(f"Classes API successful! Got {len(classes)} classes")
                    
                    # Show first few classes
                    for i, cls in enumerate(classes[:3]):
                        print(f"  Class {i+1}: {cls.get('name')} - {cls.get('student_count', 'NO COUNT')} students")
                        print(f"    ID: {cls.get('id')}, Status: {cls.get('status')}")
                else:
                    error_text = await response.text()
                    print(f"Classes API failed: {response.status} - {error_text}")
                    return
            
            # Test getting members for a specific class
            if classes:
                first_class = classes[0]
                class_id = first_class.get('id')
                print(f"\n=== Testing Class Members API for class ID {class_id} ===")
                
                async with session.get(
                    f'http://localhost:8000/api/v1/classes/{class_id}/members',
                    headers=headers
                ) as response:
                    if response.status == 200:
                        members = await response.json()
                        print(f"Members API successful! Got {len(members)} members")
                        for member in members[:3]:
                            print(f"  - {member.get('full_name')} ({member.get('email')})")
                    else:
                        error_text = await response.text()
                        print(f"Members API failed: {response.status} - {error_text}")
        
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_api())