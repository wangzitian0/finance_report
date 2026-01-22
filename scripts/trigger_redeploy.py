from libs.dokploy import get_dokploy
import os

def redeploy():
    client = get_dokploy()
    compose_id = "A6V-hbJlgHMwgPDoTDnhH"
    
    with open("scripts/compose_temp.yaml", "r") as f:
        compose_content = f.read()
    
    print(f"Updating compose {compose_id} to sourceType=raw and pushing new content...")
    client.update_compose(compose_id, compose_file=compose_content, sourceType="raw")
    
    print(f"Triggering deployment...")
    client.deploy_compose(compose_id)
    print("Done.")

if __name__ == "__main__":
    redeploy()
