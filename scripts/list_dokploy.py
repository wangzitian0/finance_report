from libs.dokploy import get_dokploy
import os

def check_all_services():
    client = get_dokploy()
    projects = client.list_projects()
    
    for project in projects:
        print(f"Project: {project.get('name')} ({project.get('projectId')})")
        for env in project.get('environments', []):
            print(f"  Environment: {env.get('name')} ({env.get('environmentId')})")
            for compose in env.get('compose', []):
                print(f"    Compose: {compose.get('name')} ({compose.get('composeId')})")
                # print(f"      Env vars: {compose.get('env')}")

if __name__ == "__main__":
    check_all_services()
