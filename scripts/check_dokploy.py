from libs.dokploy import get_dokploy
import os

def check_service():
    client = get_dokploy()
    compose_id = "A6V-hbJlgHMwgPDoTDnhH"
    
    try:
        compose = client.get_compose(compose_id)
        print(f"Service Name: {compose.get('name')}")
        print(f"Project Name: {compose.get('project', {}).get('name')}")
        print(f"Environment Name: {compose.get('environment', {}).get('name')}")
        print("\nEnvironment Variables:")
        print(compose.get('env', 'No env vars found'))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_service()
