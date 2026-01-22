from libs.dokploy import get_dokploy
import os

def check_deployments():
    client = get_dokploy()
    compose_id = "A6V-hbJlgHMwgPDoTDnhH"
    
    try:
        # 获取服务详情
        compose = client.get_compose(compose_id)
        print(f"Service: {compose.get('name')}")
        
        # Dokploy API 可能没有直接列出 deployments 的公开方法在 libs.dokploy 中
        # 但我们可以通过 get_compose 返回的详情查看当前状态
        # 尝试直接调用 api 路径获取部署列表
        endpoint = f"compose.deployments?composeId={compose_id}"
        deployments = client._request("GET", endpoint)
        
        print("\nRecent Deployments:")
        for dep in deployments[:5]:  # 只看最近5个
            print(f"- ID: {dep.get('deploymentId')}")
            print(f"  Status: {dep.get('status')}")
            print(f"  Created: {dep.get('createdAt')}")
            if dep.get('log'):
                print(f"  Log Snippet: {dep.get('log')[:200]}...")
            print("-" * 20)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_deployments()

