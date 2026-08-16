import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, List, Optional, Any

DATA_DIR = os.getenv("DATA_DIR", "/data")
if not os.path.exists(DATA_DIR):
    # Local dev fallback
    DATA_DIR = os.path.expanduser("~/.config/google-tasks-mcp")
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
CLIENT_SECRET_FILE = os.path.join(DATA_DIR, "client_secret.json")

class GoogleTasksClient:
    def __init__(self, data_dir: str = DATA_DIR):
        self.data_dir = data_dir
        self.accounts_file = os.path.join(self.data_dir, "accounts.json")
        self.client_secret_file = os.path.join(self.data_dir, "client_secret.json")
        self._ensure_files()

    def _ensure_files(self):
        os.makedirs(self.data_dir, exist_ok=True)
        if not os.path.exists(self.accounts_file):
            # Check if existing single-token exists and migrate
            single_token = os.path.join(self.data_dir, "token.json")
            accounts = {}
            if os.path.exists(single_token):
                try:
                    with open(single_token, "r", encoding="utf-8") as f:
                        token_data = json.load(f)
                    accounts["default"] = {
                        "name": "Hoofdaccount",
                        "email": "rthepen@gmail.com",
                        "tokens": token_data,
                        "created_at": time.time()
                    }
                except Exception:
                    pass
            with open(self.accounts_file, "w", encoding="utf-8") as f:
                json.dump(accounts, f, indent=2)

    def get_client_config(self) -> Optional[Dict[str, Any]]:
        # Look in data_dir, or in home directory fallback
        paths = [
            self.client_secret_file,
            os.path.expanduser("~/.config/google-tasks-mcp/client_secret.json"),
            "/data/client_secret.json"
        ]
        for p in paths:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data.get("installed") or data.get("web") or data
                except Exception:
                    pass
        return None

    def save_client_config(self, config_data: Dict[str, Any]):
        with open(self.client_secret_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

    def get_accounts(self) -> Dict[str, Any]:
        if not os.path.exists(self.accounts_file):
            return {}
        try:
            with open(self.accounts_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_account(self, account_id: str, email: str, name: str, token_data: Dict[str, Any]):
        accounts = self.get_accounts()
        accounts[account_id] = {
            "id": account_id,
            "name": name or email,
            "email": email,
            "tokens": token_data,
            "updated_at": time.time()
        }
        with open(self.accounts_file, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)

    def delete_account(self, account_id: str):
        accounts = self.get_accounts()
        if account_id in accounts:
            del accounts[account_id]
            with open(self.accounts_file, "w", encoding="utf-8") as f:
                json.dump(accounts, f, indent=2)

    def get_access_token(self, account_id: str) -> Optional[str]:
        accounts = self.get_accounts()
        if account_id not in accounts:
            return None
        
        token_data = accounts[account_id].get("tokens", {})
        client_cfg = self.get_client_config() or {}
        
        client_id = token_data.get("client_id") or client_cfg.get("client_id")
        client_secret = token_data.get("client_secret") or client_cfg.get("client_secret")
        refresh_token = token_data.get("refresh_token")

        if not refresh_token or not client_id or not client_secret:
            return None

        # Request new access token
        req_data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://oauth2.googleapis.com/token",
            data=req_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)
                return data.get("access_token")
        except Exception as e:
            print(f"Error refreshing access token for {account_id}: {e}")
            return None

    def api_request(self, account_id: str, url: str, method: str = "GET", payload: Any = None) -> Optional[Any]:
        token = self.get_access_token(account_id)
        if not token:
            return None

        for attempt in range(5):
            try:
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                body = json.dumps(payload).encode("utf-8") if payload is not None else (b"" if method in ("POST", "PUT", "PATCH") else None)
                req = urllib.request.Request(url, data=body, headers=headers, method=method)
                
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 204 or resp.length == 0:
                        return True
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 204:
                    return True
                if e.code == 429:
                    time.sleep(1.5 ** attempt)
                elif e.code in (401, 403):
                    # Try refreshing token once
                    token = self.get_access_token(account_id)
                    time.sleep(1)
                else:
                    try:
                        err_content = e.read().decode("utf-8")
                        print(f"API Error {e.code} for {method} {url}: {err_content}")
                    except Exception:
                        pass
                    return None
            except Exception as e:
                time.sleep(1)
        return None

    # Tasks API methods
    def list_tasklists(self, account_id: str) -> List[Dict[str, Any]]:
        res = self.api_request(account_id, "https://tasks.googleapis.com/tasks/v1/users/@me/lists?maxResults=100")
        if res and "items" in res:
            return res["items"]
        return []

    def create_tasklist(self, account_id: str, title: str) -> Optional[Dict[str, Any]]:
        return self.api_request(account_id, "https://tasks.googleapis.com/tasks/v1/users/@me/lists", method="POST", payload={"title": title})

    def update_tasklist(self, account_id: str, tasklist_id: str, title: str) -> Optional[Dict[str, Any]]:
        return self.api_request(account_id, f"https://tasks.googleapis.com/tasks/v1/users/@me/lists/{tasklist_id}", method="PATCH", payload={"title": title})

    def delete_tasklist(self, account_id: str, tasklist_id: str) -> bool:
        return bool(self.api_request(account_id, f"https://tasks.googleapis.com/tasks/v1/users/@me/lists/{tasklist_id}", method="DELETE"))

    def list_tasks(self, account_id: str, tasklist_id: str) -> List[Dict[str, Any]]:
        all_tasks = []
        page_token = None
        while True:
            url = f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks?maxResults=100&showCompleted=true&showHidden=true"
            if page_token:
                url += f"&pageToken={page_token}"
            res = self.api_request(account_id, url)
            if not res or "items" not in res:
                break
            all_tasks.extend(res["items"])
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return all_tasks

    def create_task(self, account_id: str, tasklist_id: str, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.api_request(account_id, f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks", method="POST", payload=task_data)

    def update_task(self, account_id: str, tasklist_id: str, task_id: str, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.api_request(account_id, f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks/{task_id}", method="PATCH", payload=task_data)

    def delete_task(self, account_id: str, tasklist_id: str, task_id: str) -> bool:
        return bool(self.api_request(account_id, f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks/{task_id}", method="DELETE"))

    def move_task(self, account_id: str, tasklist_id: str, task_id: str, parent_id: Optional[str] = None, previous_id: Optional[str] = None) -> bool:
        url = f"https://tasks.googleapis.com/tasks/v1/lists/{tasklist_id}/tasks/{task_id}/move?"
        params = []
        if parent_id:
            params.append(f"parent={parent_id}")
        if previous_id:
            params.append(f"previous={previous_id}")
        url += "&".join(params)
        return bool(self.api_request(account_id, url, method="POST"))
