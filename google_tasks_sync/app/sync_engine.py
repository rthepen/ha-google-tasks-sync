import time
import json
from typing import Dict, List, Any, Optional
from threading import Timer
from google_client import GoogleTasksClient

class SyncEngine:
    def __init__(self, client: GoogleTasksClient, sync_interval_seconds: int = 900):
        self.client = client
        self.sync_interval = sync_interval_seconds
        self.is_syncing = False
        self.last_sync_time: Optional[str] = None
        self.last_sync_status: str = "Gereed"
        self.logs: List[Dict[str, Any]] = []
        self._timer: Optional[Timer] = None
        self.start_periodic_sync()

    def log(self, message: str, level: str = "info"):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = {"timestamp": timestamp, "level": level, "message": message}
        self.logs.insert(0, entry)
        if len(self.logs) > 100:
            self.logs.pop()
        print(f"[{timestamp}] [{level.upper()}] {message}")

    def start_periodic_sync(self):
        if self._timer:
            self._timer.cancel()
        
        def _job():
            try:
                self.run_sync()
            except Exception as e:
                self.log(f"Periodieke sync fout: {e}", level="error")
            finally:
                self.start_periodic_sync()

        self._timer = Timer(self.sync_interval, _job)
        self._timer.daemon = True
        self._timer.start()

    def export_full_json(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen Google accounts gekoppeld.")
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        account_info = accounts[target_account]

        tasklists = self.client.list_tasklists(target_account)
        export_lists = []
        total_tasks = 0

        for tl in tasklists:
            t_list_id = tl["id"]
            t_list_title = tl["title"]
            
            raw_tasks = self.client.list_tasks(target_account, t_list_id)
            raw_tasks.sort(key=lambda x: x.get("position", ""))

            cleaned_tasks = []
            for t in raw_tasks:
                cleaned_tasks.append({
                    "id": t.get("id"),
                    "title": t.get("title", ""),
                    "notes": t.get("notes", ""),
                    "status": t.get("status", "needsAction"),
                    "due": t.get("due"),
                    "position": t.get("position"),
                    "updated": t.get("updated"),
                    "webViewLink": t.get("webViewLink")
                })

            total_tasks += len(cleaned_tasks)
            export_lists.append({
                "list_id": t_list_id,
                "titel": t_list_title,
                "aantal_taken": len(cleaned_tasks),
                "taken": cleaned_tasks
            })

        return {
            "bron_account": {
                "id": target_account,
                "naam": account_info.get("name"),
                "email": account_info.get("email")
            },
            "export_tijdstip": time.strftime("%Y-%m-%d %H:%M:%S"),
            "totaal_lijsten": len(export_lists),
            "totaal_taken": total_tasks,
            "lijsten": export_lists
        }

    def import_full_json(self, json_data: Dict[str, Any], target_account_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen Google accounts geconfigureerd.")

        targets = target_account_ids if target_account_ids else list(accounts.keys())
        results = {}

        lists_to_import = json_data.get("lijsten") or json_data.get("tasks") or json_data.get("tasklists") or []

        for acc_id in targets:
            if acc_id not in accounts:
                continue

            acc_name = accounts[acc_id].get("name", acc_id)
            self.log(f"Start import van {len(lists_to_import)} lijsten naar account: {acc_name}")
            
            # Fetch existing lists (by id and by title)
            existing_tasklists = self.client.list_tasklists(acc_id)
            existing_lists_by_id = {l["id"]: l["title"] for l in existing_tasklists}
            existing_lists_by_title = {l["title"]: l["id"] for l in existing_tasklists}
            
            stats = {"created_lists": 0, "created_tasks": 0, "updated_tasks": 0, "deleted_tasks": 0}

            for l_item in lists_to_import:
                list_title = l_item.get("titel") or l_item.get("title")
                list_id = l_item.get("list_id") or l_item.get("id")

                if not list_title and not list_id:
                    continue

                # 1. Resolve / Update List Title or Create List
                if list_id and list_id in existing_lists_by_id:
                    # List exists by ID
                    current_title = existing_lists_by_id[list_id]
                    if list_title and list_title != current_title:
                        self.client.update_tasklist(acc_id, list_id, list_title)
                        self.log(f"Lijstnaam gewijzigd van '{current_title}' naar '{list_title}'")
                elif list_title and list_title in existing_lists_by_title:
                    # List exists by title
                    list_id = existing_lists_by_title[list_title]
                else:
                    # Create new list
                    new_title = list_title or "Nieuwe Lijst"
                    new_l = self.client.create_tasklist(acc_id, new_title)
                    if new_l:
                        list_id = new_l["id"]
                        existing_lists_by_title[new_title] = list_id
                        existing_lists_by_id[list_id] = new_title
                        stats["created_lists"] += 1
                        self.log(f"Nieuwe lijst aangemaakt: {new_title}")
                    else:
                        continue

                # 2. Fetch existing tasks in this list (by ID and by Title) and clean up duplicates
                raw_existing_tasks = self.client.list_tasks(acc_id, list_id)
                
                # Check and remove duplicate tasks/folders with identical title in the same list
                seen_titles = {}
                active_existing_tasks = []
                for t in raw_existing_tasks:
                    if t.get("deleted"):
                        continue
                    t_title = t.get("title", "").strip()
                    if not t_title:
                        continue
                    if t_title in seen_titles:
                        # Duplicate found in Google Tasks! Delete redundant copy
                        dup_id = t["id"]
                        self.client.delete_task(acc_id, list_id, dup_id)
                        self.log(f"Dubbele/onzichtbare taak opgeruimd uit '{list_title}': '{t_title}' (id: {dup_id})", level="warning")
                    else:
                        seen_titles[t_title] = t["id"]
                        active_existing_tasks.append(t)

                existing_tasks_by_id = {t["id"]: t for t in active_existing_tasks if "id" in t}
                existing_tasks_by_title = {t.get("title", "").strip(): t for t in active_existing_tasks if "title" in t}
                
                tasks_to_import = l_item.get("taken", []) or l_item.get("tasks", []) or l_item.get("subtaken", [])
                
                ordered_task_ids = []

                for t_item in tasks_to_import:
                    t_id = t_item.get("id")
                    t_title = (t_item.get("title") or "").strip()
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

                    final_task_id = None

                    # Match by task ID first (allows renaming titles!), then fallback to Title
                    if t_id and t_id in existing_tasks_by_id:
                        final_task_id = t_id
                        old_task = existing_tasks_by_id[t_id]
                        # Only PATCH if anything actually changed
                        if (old_task.get("title", "").strip() != t_title or 
                            old_task.get("notes") != t_notes or 
                            old_task.get("status") != t_status):
                            self.client.update_task(acc_id, list_id, t_id, task_body)
                            self.log(f"Taak bijgewerkt [{list_title}]: '{t_title}'")
                        stats["updated_tasks"] += 1
                    elif t_title in existing_tasks_by_title:
                        final_task_id = existing_tasks_by_title[t_title]["id"]
                        old_task = existing_tasks_by_title[t_title]
                        if (old_task.get("notes") != t_notes or 
                            old_task.get("status") != t_status):
                            self.client.update_task(acc_id, list_id, final_task_id, task_body)
                            self.log(f"Taak bijgewerkt [{list_title}]: '{t_title}'")
                        stats["updated_tasks"] += 1
                    else:
                        # Create new task
                        created = self.client.create_task(acc_id, list_id, task_body)
                        if created and "id" in created:
                            final_task_id = created["id"]
                            existing_tasks_by_title[t_title] = created
                            self.log(f"Nieuwe taak aangemaakt [{list_title}]: '{t_title}'")
                        stats["created_tasks"] += 1
                    
                    if final_task_id and final_task_id not in ordered_task_ids:
                        ordered_task_ids.append(final_task_id)
                    
                    time.sleep(0.02)

                # 3. Synchronize task order/position in Google Tasks (Top to Bottom)
                if len(ordered_task_ids) > 1:
                    prev_id = ordered_task_ids[0]
                    # First task moved to top
                    self.client.move_task(acc_id, list_id, prev_id, previous_id=None)
                    time.sleep(0.02)

                    for cur_id in ordered_task_ids[1:]:
                        self.client.move_task(acc_id, list_id, cur_id, previous_id=prev_id)
                        prev_id = cur_id
                        time.sleep(0.02)
                    self.log(f"Volgorde/positie gesynchroniseerd voor {len(ordered_task_ids)} taken in '{list_title}'")

            results[acc_id] = stats
            self.log(f"Import voltooid voor {acc_name}: {stats}", level="success")

        return {"success": True, "results": results}

    def run_sync(self) -> Dict[str, Any]:
        if self.is_syncing:
            return {"status": "already_syncing"}

        self.is_syncing = True
        self.log("Automatisch synchronisatieproces gestart...")
        
        try:
            accounts = self.client.get_accounts()
            account_ids = list(accounts.keys())

            if len(account_ids) < 2:
                msg = f"Multi-account sync overgeslagen ({len(account_ids)} account actief)."
                self.log(msg, level="warning")
                self.last_sync_status = msg
                self.last_sync_time = time.strftime("%Y-%m-%d %H:%M:%S")
                return {"status": "skipped", "message": msg}

            # Multi-account sync
            primary_id = account_ids[0]
            secondary_ids = account_ids[1:]

            self.log(f"Sync tussen {len(account_ids)} accounts: {', '.join([accounts[a].get('name', a) for a in account_ids])}")
            primary_data = self.export_full_json(primary_id)
            
            for sec_id in secondary_ids:
                sec_name = accounts[sec_id].get("name", sec_id)
                self.log(f"Synchroniseer naar {sec_name}...")
                self.import_full_json(primary_data, target_account_ids=[sec_id])

            self.last_sync_status = "Succesvol"
            self.last_sync_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log("Synchronisatie succesvol afgerond!", level="success")
            return {"status": "success", "time": self.last_sync_time}

        except Exception as e:
            err = f"Fout tijdens synchronisatie: {str(e)}"
            self.log(err, level="error")
            self.last_sync_status = err
            return {"status": "error", "error": str(e)}
        finally:
            self.is_syncing = False

    def get_all_tasks(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Haalt alle taken op uit alle lijsten met hun huidige lijstnaam."""
        accounts = self.client.get_accounts()
        if not accounts:
            return []
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        
        tasks_pool = []
        for cl in tasklists:
            list_id = cl["id"]
            list_title = cl["title"]
            if list_title.lower() == "to do":
                continue
            raw_tasks = self.client.list_tasks(target_account, list_id)
            for t in raw_tasks:
                if t.get("deleted"):
                    continue
                tasks_pool.append({
                    "id": t.get("id"),
                    "title": t.get("title", ""),
                    "notes": t.get("notes", ""),
                    "status": t.get("status", "needsAction"),
                    "current_list_id": list_id,
                    "current_list_title": list_title
                })
        
        # Sorteer op huidige lijst en titel
        tasks_pool.sort(key=lambda x: (x.get("current_list_title", ""), x.get("title", "")))
        return tasks_pool

    def get_captain_fixed_tasks(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Haalt alleen de taken op uit '03. Kapitein Roy' en '04. Kapitein Karen'."""
        accounts = self.client.get_accounts()
        if not accounts:
            return []
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        
        tasks_pool = []
        for cl in tasklists:
            list_id = cl["id"]
            list_title = cl["title"]
            l_low = list_title.lower()
            if "kapitein roy" in l_low or "kapitein karen" in l_low:
                raw_tasks = self.client.list_tasks(target_account, list_id)
                for t in raw_tasks:
                    if t.get("deleted") or t.get("title", "").startswith("📂 "):
                        continue
                    tasks_pool.append({
                        "id": t.get("id"),
                        "title": t.get("title", ""),
                        "notes": t.get("notes", ""),
                        "status": t.get("status", "needsAction"),
                        "current_list_id": list_id,
                        "current_list_title": list_title
                    })
        
    def create_single_task(self, title: str, list_title: str, sublist_name: Optional[str] = None, notes: str = "", due: Optional[str] = None, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Maakt een nieuwe taak aan in de opgegeven hoofdlijst, eventueel gekoppeld aan een sublijst map."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts geconfigureerd")
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        lists_by_title = {l["title"]: l["id"] for l in tasklists}

        list_id = lists_by_title.get(list_title)
        if not list_id:
            new_l = self.client.create_tasklist(target_account, list_title)
            if new_l:
                list_id = new_l["id"]
                lists_by_title[list_title] = list_id
            else:
                raise ValueError(f"Kon lijst '{list_title}' niet aanmaken")

        # Format notes with sublist tag if provided
        final_notes = notes.strip()
        if sublist_name and sublist_name.strip() and not sublist_name.lower().startswith("alle"):
            clean_sub = sublist_name.replace("📂", "").strip()
            if not final_notes.startswith("["):
                final_notes = f"[{clean_sub}] {final_notes}".strip()

        # Check existing tasks in target list for deduplication
        raw_existing = self.client.list_tasks(target_account, list_id)
        parent_folder_id = None
        
        clean_sub_name = (sublist_name or "").replace("📂", "").strip()
        for t in raw_existing:
            if t.get("deleted"):
                continue
            # Look for matching parent folder header like '📂 Gezinshuis' or '📂 Bouw Woning'
            if clean_sub_name and t.get("title", "").strip().lower() in (f"📂 {clean_sub_name.lower()}", clean_sub_name.lower()):
                parent_folder_id = t["id"]
            # Avoid duplicate task
            if t.get("title", "").strip() == title.strip():
                # Task already exists, update it instead
                self.client.update_task(target_account, list_id, t["id"], {
                    "title": title.strip(),
                    "notes": final_notes,
                    "status": "needsAction"
                })
                self.log(f"Bestaande taak '{title}' bijgewerkt in '{list_title}'")
                return {"success": True, "task_id": t["id"], "action": "updated"}

        # Create new task
        body = {
            "title": title.strip(),
            "notes": final_notes,
            "status": "needsAction"
        }
        if due:
            body["due"] = due

        created = self.client.create_task(target_account, list_id, body)
        if not created or "id" not in created:
            raise ValueError("Aanmaken van taak mislukt bij Google Tasks")

        new_task_id = created["id"]

        # If we have a parent folder, move task underneath it
        if parent_folder_id:
            try:
                self.client.move_task(target_account, list_id, new_task_id, parent_id=parent_folder_id)
            except Exception:
                pass

        self.log(f"Nieuwe taak '{title}' aangemaakt in '{list_title}' (sub: {clean_sub_name or 'Geen'})", level="success")
        return {"success": True, "task_id": new_task_id, "action": "created"}

    def reassign_tasks_batch(self, moves: List[Dict[str, Any]], account_id: Optional[str] = None) -> Dict[str, Any]:
        """Verplaatst taken naar een andere lijst (doel-lijst) en voorkomt duplicaten."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts")
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        lists_by_title = {l["title"]: l["id"] for l in tasklists}

        # Cache existing tasks in target lists to avoid duplicate creates
        target_tasks_cache = {}

        def get_existing_in_list(list_id):
            if list_id not in target_tasks_cache:
                raw = self.client.list_tasks(target_account, list_id)
                target_tasks_cache[list_id] = {t.get("title", "").strip(): t["id"] for t in raw if not t.get("deleted")}
            return target_tasks_cache[list_id]

        success_count = 0
        self.log(f"Start batch herindeling van {len(moves)} taken...")

        for m in moves:
            t_id = m.get("task_id")
            cur_list_id = m.get("current_list_id")
            target_title = m.get("target_list_title")
            t_title = (m.get("title") or "").strip()
            t_notes = m.get("notes", "")
            t_status = m.get("status", "needsAction")

            target_list_id = lists_by_title.get(target_title)
            if not target_list_id:
                # Maak lijst aan indien niet bestaand
                new_l = self.client.create_tasklist(target_account, target_title)
                if new_l:
                    target_list_id = new_l["id"]
                    lists_by_title[target_title] = target_list_id

            if target_list_id and cur_list_id != target_list_id:
                existing_in_target = get_existing_in_list(target_list_id)

                if t_title in existing_in_target:
                    # Update bestaande taak in doellijst in plaats van dubbel aanmaken
                    existing_id = existing_in_target[t_title]
                    self.client.update_task(target_account, target_list_id, existing_id, {
                        "title": t_title,
                        "notes": t_notes,
                        "status": t_status
                    })
                    self.log(f"Bestaande taak in '{target_title}' bijgewerkt: '{t_title}'")
                else:
                    # Maak aan in nieuwe lijst
                    created = self.client.create_task(target_account, target_list_id, {
                        "title": t_title,
                        "notes": t_notes,
                        "status": t_status
                    })
                    if created and "id" in created:
                        existing_in_target[t_title] = created["id"]
                    self.log(f"Taak '{t_title}' verplaatst naar '{target_title}'")

                # Verwijder uit oude lijst
                if t_id and cur_list_id:
                    self.client.delete_task(target_account, cur_list_id, t_id)
                
                success_count += 1
                time.sleep(0.04)

        self.log(f"Batch herindeling voltooid: {success_count} taken verplaatst.", level="success")
        return {"success": True, "moved_count": success_count}

    def apply_captain_division(self, roy_tasks: List[Dict[str, Any]], karen_tasks: List[Dict[str, Any]], account_id: Optional[str] = None) -> Dict[str, Any]:
        """Past de verdeling toe: verplaatst/zet taken in 03. Kapitein Roy en 04. Kapitein Karen met duplicaat-check."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts")
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        lists_by_title = {l["title"]: l["id"] for l in tasklists}

        roy_list_id = None
        karen_list_id = None
        for title, lid in lists_by_title.items():
            if "kapitein roy" in title.lower():
                roy_list_id = lid
            elif "kapitein karen" in title.lower():
                karen_list_id = lid

        if not roy_list_id:
            rl = self.client.create_tasklist(target_account, "03. Kapitein Roy")
            roy_list_id = rl["id"] if rl else None
        if not karen_list_id:
            kl = self.client.create_tasklist(target_account, "04. Kapitein Karen")
            karen_list_id = kl["id"] if kl else None

        self.log(f"Start toepassen kapiteinsverdeling: {len(roy_tasks)} voor Roy, {len(karen_tasks)} voor Karen...")

        def sync_tasks_to_target_list(target_list_id, task_list, list_name):
            raw_existing = self.client.list_tasks(target_account, target_list_id)
            existing_by_title = {t.get("title", "").strip(): t["id"] for t in raw_existing if not t.get("deleted")}

            for t in task_list:
                t_title = (t.get("title") or "").strip()
                if not t_title:
                    continue
                t_notes = t.get("notes", "")
                t_points = t.get("points")
                t_notes_with_pts = f"Punten: {t_points} | {t_notes}".strip() if t_points else t_notes

                payload = {
                    "title": t_title,
                    "notes": t_notes_with_pts,
                    "status": t.get("status", "needsAction")
                }

                if t_title in existing_by_title:
                    # Update existing task instead of creating duplicate
                    self.client.update_task(target_account, target_list_id, existing_by_title[t_title], payload)
                else:
                    created = self.client.create_task(target_account, target_list_id, payload)
                    if created and "id" in created:
                        existing_by_title[t_title] = created["id"]
                time.sleep(0.04)

        # 1. Update Roy's tasks
        sync_tasks_to_target_list(roy_list_id, roy_tasks, "03. Kapitein Roy")

        # 2. Update Karen's tasks
        sync_tasks_to_target_list(karen_list_id, karen_tasks, "04. Kapitein Karen")

        self.log("Kapiteinsverdeling succesvol gesynchroniseerd met Google Tasks!", level="success")
        return {"success": True, "roy_count": len(roy_tasks), "karen_count": len(karen_tasks)}
