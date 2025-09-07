"""
Test only the Members API endpoint to isolate the issue
"""
import asyncio
import aiohttp
import json


async def test_members_api():
    """Test only the members API endpoint."""
    
    # Use the token from frontend's localStorage
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIyIiwicm9sZSI6InRlYWNoZXIiLCJleHAiOjE3NTc0MDY1NDMsImlhdCI6MTc1NzQwNDc0MywidHlwZSI6ImFjY2VzcyJ9.tx3vZDNNGtriWAIBcCWZNf14I-wb4YtlgGXjC6SgfE8"
    
    class_id = 69  # Demo Math Class
    
    async with aiohttp.ClientSession() as session:
        try:
            print(f"=== Testing Members API for class ID {class_id} ===")
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            async with session.get(
                f'http://localhost:8001/api/v1/classes/{class_id}/members',
                headers=headers
            ) as response:
                if response.status == 200:
                    members = await response.json()
                    print(f"Members API successful! Got {len(members)} members")
                    for member in members[:5]:
                        print(f"  - {member.get('full_name')} ({member.get('email')})")
                else:
                    error_text = await response.text()
                    print(f"Members API failed: {response.status}")
                    print(f"Error: {error_text}")
        
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_members_api())