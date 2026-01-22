from libs.dokploy import get_dokploy
import os
import json

def check_compose_details():
    client = get_dokploy()
    compose_id = "A6V-hbJlgHMwgPDoTDnhH"
    
    try:
        compose = client.get_compose(compose_id)
        # 打印完整的 compose 对象以查找部署信息
        print(json.dumps(compose, indent=2))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_compose_details()
