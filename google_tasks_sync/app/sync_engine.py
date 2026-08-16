import time
import json
import os
import threading
from typing import Dict, List, Any, Optional
from google_client import GoogleTasksClient

class SyncEngine:
    def __init__(self, client: GoogleTasksClient):
        self.client = client
        self.is_syncing = False
        self.last_sync_time = None
        self.last_sync_status = "Nooit gedraaid"
        self.sync_logs: List[Dict[str, Any]] = []
        self._timer = None
        self._interval_seconds = 15 * 60
        self._running = False

    def start_scheduler(self, interval_minutes: int = 15):
        self._interval_seconds = max(1, interval_minutes) * 60
        self._running = True
        self._schedule_next()
        print(f"SyncEngine scheduler gestart met interval: {interval_minutes} minuten.")

    def _schedule_next(self):
        if not self._running:
            return
        self._timer = threading.Timer(self._interval_seconds, self._on_timer)
        self._timer.daemon = True
        self._timer.start()

    def _on_timer(self):
        try:
            self.run_sync()
        finally:
            self._schedule_next()

    def stop_scheduler(self):
        self._running = False
        if self._timer:
            self._timer.cancel()

    def log(self, message: str, level: str = "info"):
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": message
        }
        self.sync_logs.insert(0, entry)
        if len(self.sync_logs) > 200:
            self.sync_logs.pop()
        print(f"[{entry['timestamp']}] [{level.upper()}] {message}")

    def export_full_json(self, target_account_id: Optional[str] = None) -> Dict[str, Any]:
        accounts = self.client.get_accounts()
        if not accounts:
            return {"error": "Geen accounts gekoppeld", "lijsten": []}

        account_id = target_account_id or list(accounts.keys())[0]
        account_name = accounts[account_id].get("name", account_id)
        account_email = accounts[account_id].get("email", "")

        raw_lists = self.client.list_tasklists(account_id)
        lists_data = []

        for l in raw_lists:
            list_id = l["id"]
            list_title = l["title"]
            raw_tasks = self.client.list_tasks(account_id, list_id)
            
            # Sort by position
            raw_tasks.sort(key=lambda t: t.get("position", ""))
            
            tasks_list = []
            for t in raw_tasks:
                tasks_list.append({
                    "id": t["id"],
                    "title": t.get("title", ""),
                    "notes": t.get("notes", ""),
                    "status": t.get("status", "needsAction"),
                    "due": t.get("due"),
                    "position": t.get("position", ""),
                    "updated": t.get("updated", ""),
                    "webViewLink": t.get("webViewLink", "")
                })

            lists_data.append({
                "list_id": list_id,
                "titel": list_title,
                "aantal_taken": len(tasks_list),
                "taken": tasks_list
            })

        return {
            "bron_account": {
                "id": account_id,
                "naam": account_name,
                "email": account_email
            },
            "export_tijdstip": time.strftime("%Y-%m-%d %H:%M:%S"),
            "totaal_lijsten": len(lists_data),
            "totaal_taken": sum(l["aantal_taken"] for l in lists_data),
            "lijsten": lists_data
        }

    def import_full_json(self, json_payload: Dict[str, Any], target_account_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        accounts = self.client.get_accounts()
        if not accounts:
            return {"success": False, "error": "Geen Google accounts gekoppeld"}

        target_ids = target_account_ids or list(accounts.keys())
        results = {}

        lists_to_import = json_payload.get("lijsten", [])
        if not lists_to_import and "tasks" in json_payload:
            # Fallback format handling
            lists_to_import = [{"titel": json_payload.get("tasklist", "To do"), "taken": json_payload["tasks"]}]

        for acc_id in target_ids:
            acc_name = accounts[acc_id].get("name", acc_id)
            self.log(f"Start import van {len(lists_to_import)} lijsten naar account: {acc_name}")
            
            existing_lists = {l["title"]: l["id"] for l in self.client.list_tasklists(acc_id)}
            stats = {"created_lists": 0, "created_tasks": 0, "updated_tasks": 0}

            for l_item in lists_to_import:
                list_title = l_item.get("titel") or l_item.get("title")
                if not list_title:
                    continue

                if list_title in existing_lists:
                    list_id = existing_lists[list_title]
                else:
                    new_l = self.client.create_tasklist(acc_id, list_title)
                    if new_l:
                        list_id = new_l["id"]
                        existing_lists[list_title] = list_id
                        stats["created_lists"] += 1
                    else:
                        continue

                existing_tasks = {t.get("title"): t for t in self.client.list_tasks(acc_id, list_id)}
                
                tasks_to_import = l_item.get("taken", []) or l_item.get("tasks", []) or l_item.get("subtaken", [])
                for t_item in tasks_to_import:
                    t_title = t_item.get("title")
                    if not t_title:
                        continue
                    t_notes = t_item.get("notes", "")
                    t_status = t_item.get("status", "needsAction")
                    t_due = t_item.get("due")

                    task_body = {
                        "title": t_title,
                        "notes": t_notes,
                        "status": t_status
                    }
                    if t_due:
                        task_body["due"] = t_due

                    if t_title in existing_tasks:
                        # Update existing
                        task_id = existing_tasks[t_title]["id"]
                        self.client.update_task(acc_id, list_id, task_id, task_body)
                        stats["updated_tasks"] += 1
                    else:
                        # Create new
                        self.client.create_task(acc_id, list_id, task_body)
                        stats["created_tasks"] += 1
                    
                    time.sleep(0.05)

            results[acc_id] = stats
            self.log(f"Import voltooid voor {acc_name}: {stats}")

        return {"success": True, "results": results}

    def run_sync(self) -> Dict[str, Any]:
        if self.is_syncing:
            return {"status": "already_syncing"}

        self.is_syncing = True
        self.log("Synchronisatieproces gestart...")
        
        try:
            accounts = self.client.get_accounts()
            account_ids = list(accounts.keys())

            if len(account_ids) < 2:
                msg = f"Synchronisatie overgeslagen: {len(account_ids)} account(s) actief (minimaal 2 nodig voor multi-account sync)."
                self.log(msg, level="warning")
                self.last_sync_status = msg
                self.last_sync_time = time.strftime("%Y-%m-%d %H:%M:%S")
                return {"status": "skipped", "message": msg}

            # Two-way / Multi-account sync
            primary_id = account_ids[0]
            secondary_ids = account_ids[1:]

            self.log(f"Multi-account sync tussen {len(account_ids)} accounts: {', '.join([accounts[a].get('name', a) for a in account_ids])}")
            
            # 1. Export unified data from primary
            primary_data = self.export_full_json(primary_id)
            
            # 2. Sync to all other accounts
            for sec_id in secondary_ids:
                sec_name = accounts[sec_id].get("name", sec_id)
                self.log(f"Synchroniseer naar {sec_name}...")
                self.import_full_json(primary_data, target_account_ids=[sec_id])

            self.last_sync_status = "Succesvol"
            self.last_sync_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log("Synchronisatie succesvol afgerond!")
            return {"status": "success", "time": self.last_sync_time}

        except Exception as e:
            err = f"Fout tijdens synchronisatie: {str(e)}"
            self.log(err, level="error")
            self.last_sync_status = err
            return {"status": "error", "error": str(e)}
        finally:
            self.is_syncing = False
