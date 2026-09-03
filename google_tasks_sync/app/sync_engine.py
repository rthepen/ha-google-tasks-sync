import time
import json
import re
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
            is_todo = (list_title.lower() == "to do")
            raw_tasks = self.client.list_tasks(target_account, list_id)
            for t in raw_tasks:
                if t.get("deleted"):
                    continue
                tit = t.get("title", "").strip()
                has_num = bool(re.search(r"^\d+\.", tit)) or bool(re.search(r"-\s*\d+\.", tit))
                issues = []
                if is_todo:
                    issues.append("Staat in 'To do' lijst")
                if not has_num and not tit.startswith("📂 "):
                    issues.append("Geen volgnummer")

                tasks_pool.append({
                    "id": t.get("id"),
                    "title": tit,
                    "notes": t.get("notes", ""),
                    "status": t.get("status", "needsAction"),
                    "due": t.get("due"),
                    "parent_id": t.get("parent"),
                    "current_list_id": list_id,
                    "current_list_title": list_title,
                    "is_todo": is_todo,
                    "needs_formatting": len(issues) > 0,
                    "issues": issues
                })
        
        # Sorteer: onvolledige taken bovenaan, daarna op lijst en titel
        tasks_pool.sort(key=lambda x: (not x.get("needs_formatting", False), x.get("current_list_title", ""), x.get("title", "")))
        return tasks_pool

    def get_inbox_tasks(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Haalt alle onvolledige taken op uit Google Tasks en genereert slimme suggesties voor formattering."""
        accounts = self.client.get_accounts()
        if not accounts:
            return []

        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)

        inbox_tasks = []

        for tl in tasklists:
            list_id = tl["id"]
            list_title = tl["title"]
            is_todo = (list_title.lower() == "to do")
            raw_tasks = self.client.list_tasks(target_account, list_id)
            
            for t in raw_tasks:
                tit = t.get("title", "").strip()
                if not tit or t.get("deleted") or tit.startswith("📂 "):
                    continue

                has_num = bool(re.search(r"^\d+\.", tit)) or bool(re.search(r"-\s*\d+\.", tit))
                
                issues = []
                if is_todo:
                    issues.append("Staat in de 'To do' lijst")
                if not has_num:
                    issues.append("Geen volgnummer")

                if issues:
                    # Compute smart suggestions
                    clean_core = re.sub(r"^(\d+\.\s*.*?-\s*)?\d+\.\s*", "", tit).strip()
                    
                    # Guess target list
                    suggested_list = list_title
                    if is_todo:
                        t_low = tit.lower()
                        if any(k in t_low for k in ["roy", "zeilboot", "speervissen", "brevet"]):
                            suggested_list = "01. Roy Persoonlijk"
                        elif any(k in t_low for k in ["karen", "anticonceptie"]):
                            suggested_list = "02. Karen Persoonlijk"
                        elif any(k in t_low for k in ["dave", "rahiena", "gezinshuis", "triade", "rapportage"]):
                            suggested_list = "03. Kapitein Roy"
                        elif any(k in t_low for k in ["samen", "overleg", "besluit"]):
                            suggested_list = "06. Twee Kapiteins (Samen Doen)"
                        else:
                            suggested_list = "05. Wisselende Kapiteins"

                    # Guess sublist
                    suggested_sublist = ""
                    t_low = (tit + " " + t.get("notes", "")).lower()
                    if suggested_list == "05. Wisselende Kapiteins":
                        bouw_kw = ['waterzijde', 'luchtleidingen', 'ha regeling', 'elektra', 'gipsplaten', 'xps', 'laminaat', 'keuken', 'naden', 'rachelwerk', 'luchtkanalen', 'muren', 'voorzetwanden', 'leidingen', 'meterkast', '3d-ontwerp', 'packs', 'omvormer', 'pv-panelen', 'ac/dc', 'mqtt', 'esp ', 'dashboard', 'douche', 'afvoer', 'montageband']
                        if any(k in t_low for k in bouw_kw):
                            suggested_sublist = "07. Bouw Woning"
                        elif any(k in t_low for k in ['maandrapportage', 'evaluatie', 'triade', 'bereikbaarheid', 'gastheerschap', 'beschikbaarheid']):
                            suggested_sublist = "08. Gezinshuis"
                        else:
                            suggested_sublist = "09. Wisselend & Gezin"
                    elif suggested_list == "03. Kapitein Roy":
                        suggested_sublist = "01. Gezinshuis"
                    elif suggested_list == "04. Kapitein Karen":
                        suggested_sublist = "03. Huishouden & Zorg"

                    inbox_tasks.append({
                        "id": t["id"],
                        "current_title": tit,
                        "clean_title": clean_core,
                        "current_list_id": list_id,
                        "current_list_title": list_title,
                        "notes": t.get("notes", ""),
                        "due": t.get("due"),
                        "issues": issues,
                        "suggested_list": suggested_list,
                        "suggested_sublist": suggested_sublist
                    })

        return inbox_tasks

    def format_and_assign_task(
        self,
        task_id: str,
        current_list_id: str,
        target_list_title: str,
        sublist_name: Optional[str] = None,
        custom_number: Optional[int] = None,
        clean_title: Optional[str] = None,
        notes: str = "",
        due: Optional[str] = None,
        account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Formateert een onvolledige taak: kent volgnummer toe, voegt optioneel [Sublijst] tag toe, koppelt aan parent folder en verplaatst indien nodig."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts geconfigureerd")

        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        lists_by_title = {l["title"]: l["id"] for l in tasklists}

        dest_list_id = lists_by_title.get(target_list_title)
        if not dest_list_id:
            new_l = self.client.create_tasklist(target_account, target_list_title)
            if new_l:
                dest_list_id = new_l["id"]
                lists_by_title[target_list_title] = dest_list_id
            else:
                raise ValueError(f"Kon doellijst '{target_list_title}' niet vinden of aanmaken")

        base_title = (clean_title or "").strip()
        base_title = re.sub(r"^(\d+\.\s*.*?-\s*)?\d+\.\s*", "", base_title).strip()
        if not base_title:
            raise ValueError("Taaktitel mag niet leeg zijn")

        clean_sub = (sublist_name or "").replace("📂", "").strip()

        # Deduce or format final notes with sublist tag
        final_notes = (notes or "").strip()
        if clean_sub and not clean_sub.lower().startswith("alle"):
            if re.match(r"^\[.*?\]", final_notes):
                final_notes = re.sub(r"^\[.*?\]\s*", f"[{clean_sub}] ", final_notes)
            else:
                final_notes = f"[{clean_sub}] {final_notes}".strip()

        # Get existing tasks in destination list
        raw_dest_tasks = self.client.list_tasks(target_account, dest_list_id)
        parent_folder_id = None

        for t in raw_dest_tasks:
            if t.get("deleted"):
                continue
            t_tit_clean = t.get("title", "").replace("📂", "").strip().lower()
            clean_sub_pure = re.sub(r"^\d+\.\s*", "", clean_sub).strip().lower()
            if clean_sub_pure and (clean_sub_pure in t_tit_clean or t_tit_clean in clean_sub_pure):
                parent_folder_id = t["id"]
                break

        # Calculate number
        if custom_number is not None and custom_number > 0:
            target_num = custom_number
        else:
            max_num = 0
            for t in raw_dest_tasks:
                t_tit = t.get("title", "").strip()
                if t.get("deleted") or t_tit.startswith("📂 ") or t["id"] == task_id:
                    continue
                sub_match = re.match(r"^(\d+\.\s*.*?-\s*)(\d+)\.", t_tit)
                if clean_sub and sub_match:
                    if clean_sub.lower() in sub_match.group(1).lower():
                        cur_n = int(sub_match.group(2))
                        if cur_n > max_num:
                            max_num = cur_n
                else:
                    if parent_folder_id and t.get("parent") == parent_folder_id:
                        m = re.search(r"(\d+)\.", t_tit)
                        if m and int(m.group(1)) > max_num:
                            max_num = int(m.group(1))
                    elif not parent_folder_id:
                        m = re.match(r"^(\d+)\.", t_tit)
                        if m and int(m.group(1)) > max_num:
                            max_num = int(m.group(1))

            target_num = max_num + 1 if max_num > 0 else 1

        sub_prefix = None
        if clean_sub:
            for t in raw_dest_tasks:
                t_tit = t.get("title", "").strip()
                m_p = re.match(r"^(\d+\.\s*" + re.escape(clean_sub) + r"\s*-\s*)", t_tit)
                if m_p:
                    sub_prefix = m_p.group(1)
                    break

        if sub_prefix:
            final_title = f"{sub_prefix}{target_num:02d}. {base_title}"
        else:
            final_title = f"{target_num:02d}. {base_title}"

        task_body = {
            "title": final_title,
            "notes": final_notes,
            "status": "needsAction"
        }
        if due:
            task_body["due"] = f"{due}T00:00:00.000Z" if len(due) == 10 else due
        else:
            task_body["due"] = None

        final_task_id = task_id
        if dest_list_id != current_list_id:
            created = self.client.create_task(target_account, dest_list_id, task_body)
            if not created or "id" not in created:
                raise ValueError("Kon taak niet aanmaken in doellijst")
            final_task_id = created["id"]
            if task_id and current_list_id:
                try:
                    self.client.delete_task(target_account, current_list_id, task_id)
                except Exception:
                    pass
        else:
            updated = self.client.update_task(target_account, dest_list_id, task_id, task_body)
            if not updated:
                raise ValueError("Kon taak niet updaten")

        if parent_folder_id:
            try:
                self.client.move_task(target_account, dest_list_id, final_task_id, parent_id=parent_folder_id)
            except Exception as e:
                self.log(f"Reparenting mislukt: {str(e)}", level="warning")

        self.log(f"Taak '{final_title}' succesvol geformatteerd en opgeslagen in '{target_list_title}'!", level="success")
        return {
            "success": True,
            "task_id": final_task_id,
            "list_id": dest_list_id,
            "final_title": final_title,
            "notes": final_notes
        }

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
                        "due": t.get("due"),
                        "current_list_id": list_id,
                        "current_list_title": list_title
                    })
        
        tasks_pool.sort(key=lambda x: x.get("title", ""))
        return tasks_pool
        
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
        clean_sub_name = (sublist_name or "").replace("📂", "").strip()

        # If clean_sub_name is empty, try to deduce from title keywords if in 05. Wisselende Kapiteins
        if not clean_sub_name and "wisselende kapiteins" in list_title.lower():
            t_low = title.lower()
            bouw_kw = ['waterzijde', 'luchtleidingen', 'ha regeling', 'elektra', 'gipsplaten', 'xps', 'laminaat', 'keuken', 'naden', 'rachelwerk', 'luchtkanalen', 'muren', 'voorzetwanden', 'leidingen', 'meterkast', '3d-ontwerp', 'packs', 'omvormer', 'pv-panelen', 'ac/dc', 'mqtt', 'esp ', 'dashboard', 'douche', 'afvoer', 'montageband']
            if any(k in t_low for k in bouw_kw):
                clean_sub_name = "Bouw Woning"
            elif any(k in t_low for k in ['maandrapportage', 'evaluatie', 'triade', 'bereikbaarheid', 'gastheerschap', 'beschikbaarheid']):
                clean_sub_name = "Gezinshuis"
            else:
                clean_sub_name = "Wisselend & Gezin"

        if clean_sub_name and not clean_sub_name.lower().startswith("alle"):
            if not final_notes.startswith("["):
                final_notes = f"[{clean_sub_name}] {final_notes}".strip()

        # Check existing tasks in target list for deduplication and parent folder
        raw_existing = self.client.list_tasks(target_account, list_id)
        parent_folder_id = None
        
        for t in raw_existing:
            if t.get("deleted"):
                continue
            # Look for matching parent folder header like '📂 Gezinshuis' or '📂 Bouw Woning'
            t_tit_clean = t.get("title", "").replace("📂", "").strip().lower()
            clean_sub_pure = re.sub(r"^\d+\.\s*", "", clean_sub_name).strip().lower()
            if clean_sub_pure and (clean_sub_pure in t_tit_clean or t_tit_clean in clean_sub_pure):
                parent_folder_id = t["id"]
                break

        # Calculate next number if title doesn't already have one
        clean_title = title.strip()
        has_num = bool(re.match(r"^\d+\.\s*", clean_title))
        if not has_num:
            # Find max number among tasks with similar parent or prefix
            max_num = 0
            for t in raw_existing:
                t_tit = t.get("title", "").strip()
                if t.get("deleted") or t_tit.startswith("📂 "):
                    continue
                # If sublist specified and this task has sub-prefix like "04. Eigen Studio - 09. ...", match prefix
                sub_match = re.match(r"^(\d+\.\s*.*?-\s*)(\d+)\.", t_tit)
                if clean_sub_name and sub_match:
                    if clean_sub_name.lower() in sub_match.group(1).lower():
                        cur_n = int(sub_match.group(2))
                        if cur_n > max_num:
                            max_num = cur_n
                else:
                    # If this task belongs to the same parent_folder_id or root
                    if parent_folder_id and t.get("parent") == parent_folder_id:
                        m = re.search(r"(\d+)\.", t_tit)
                        if m:
                            cur_n = int(m.group(1))
                            if cur_n > max_num:
                                max_num = cur_n
                    elif not parent_folder_id:
                        m = re.match(r"^(\d+)\.", t_tit)
                        if m:
                            cur_n = int(m.group(1))
                            if cur_n > max_num:
                                max_num = cur_n

            next_num = max_num + 1 if max_num > 0 else 1
            
            # Check for sub-prefix in existing tasks for this sublist
            sub_prefix = None
            if clean_sub_name:
                for t in raw_existing:
                    t_tit = t.get("title", "").strip()
                    m_p = re.match(r"^(\d+\.\s*" + re.escape(clean_sub_name) + r"\s*-\s*)", t_tit)
                    if m_p:
                        sub_prefix = m_p.group(1)
                        break
            if sub_prefix:
                clean_title = f"{sub_prefix}{next_num:02d}. {clean_title}"
            else:
                clean_title = f"{next_num:02d}. {clean_title}"

        # Avoid duplicate task
        for t in raw_existing:
            if t.get("deleted"):
                continue
            if t.get("title", "").strip() == clean_title or t.get("title", "").strip() == title.strip():
                update_body = {
                    "title": clean_title,
                    "notes": final_notes,
                    "status": "needsAction"
                }
                if due:
                    update_body["due"] = f"{due}T00:00:00.000Z" if len(due) == 10 else due
                self.client.update_task(target_account, list_id, t["id"], update_body)
                self.log(f"Bestaande taak '{clean_title}' bijgewerkt in '{list_title}'")
                return {"success": True, "task_id": t["id"], "action": "updated", "final_title": clean_title}

        # Create new task
        body = {
            "title": clean_title,
            "notes": final_notes,
            "status": "needsAction"
        }
        if due:
            body["due"] = f"{due}T00:00:00.000Z" if len(due) == 10 else due

        created = self.client.create_task(target_account, list_id, body)
        if not created or "id" not in created:
            raise ValueError("Aanmaken van taak mislukt bij Google Tasks")

        new_task_id = created["id"]

        # If we have a parent folder, move task underneath it
        if parent_folder_id:
            try:
                self.client.move_task(target_account, list_id, new_task_id, parent_id=parent_folder_id)
            except Exception as e:
                self.log(f"Move naar parent folder mislukt: {str(e)}", level="warning")

        self.log(f"Nieuwe taak '{clean_title}' aangemaakt in '{list_title}' (sub: {clean_sub_name or 'Geen'}, deadline: {due or 'Geen'})", level="success")
        return {"success": True, "task_id": new_task_id, "action": "created", "final_title": clean_title}

    def delete_single_task(self, task_id: str, list_id: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Verwijdert een taak permanent uit Google Tasks."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts geconfigureerd")
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        success = self.client.delete_task(target_account, list_id, task_id)
        if not success:
            raise ValueError(f"Kon taak '{task_id}' niet verwijderen uit lijst '{list_id}'")
        self.log(f"Taak '{task_id}' succesvol verwijderd uit lijst '{list_id}'", level="success")
        return {"success": True, "task_id": task_id}

    def update_single_task(self, task_id: str, list_id: str, title: str, notes: str = "", due: Optional[str] = None, target_list_title: Optional[str] = None, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Wijzigt titel, notities, deadline of verplaatst een taak naar een andere lijst."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts geconfigureerd")
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        lists_by_title = {l["title"]: l["id"] for l in tasklists}

        body = {
            "title": title.strip(),
            "notes": notes.strip(),
            "status": "needsAction"
        }
        if due:
            body["due"] = f"{due}T00:00:00.000Z" if len(due) == 10 else due
        else:
            body["due"] = None

        dest_list_id = lists_by_title.get(target_list_title) if target_list_title else list_id
        
        if dest_list_id and dest_list_id != list_id:
            # Move to new list
            created = self.client.create_task(target_account, dest_list_id, body)
            if task_id and list_id:
                self.client.delete_task(target_account, list_id, task_id)
            self.log(f"Taak '{title}' gewijzigd en verplaatst naar '{target_list_title}'", level="success")
            return {"success": True, "task_id": created.get("id") if created else None}
        else:
            updated = self.client.update_task(target_account, list_id, task_id, body)
            self.log(f"Taak '{title}' succesvol gewijzigd", level="success")
            return {"success": True, "task_id": task_id}

    def renumber_list_tasks(self, account_id: str, list_id: str, list_title: str) -> None:
        """Her-nummert alle taken binnen een lijst netjes van 01 t/m N (en behoudt sublijst prefix indien aanwezig)."""
        import re
        try:
            raw_tasks = self.client.list_tasks(account_id, list_id)
            active_tasks = [t for t in raw_tasks if not t.get("deleted") and not t.get("title", "").startswith("📂 ")]
            
            # Sorteer taken op basis van hun huidige nummer of positie
            def task_sort_key(t):
                tit = t.get("title", "")
                m = re.search(r"(\d+)", tit)
                return int(m.group(1)) if m else 999
            
            active_tasks.sort(key=task_sort_key)
            
            # Sub-grouping by sub-prefix (bijv. "04. Eigen Studio -") of algemene lijstnummering
            subgroup_counters = {}
            global_counter = 1

            for t in active_tasks:
                old_title = t.get("title", "").strip()
                t_id = t.get("id")
                if not old_title or not t_id:
                    continue

                new_title = old_title
                sub_match = re.match(r"^(\d+\.\s*.*?-\s*)\d*\.?\s*(.*)$", old_title)
                if sub_match:
                    prefix = sub_match.group(1)
                    core_name = sub_match.group(2).strip()
                    subgroup_counters[prefix] = subgroup_counters.get(prefix, 0) + 1
                    num_str = f"{subgroup_counters[prefix]:02d}"
                    new_title = f"{prefix}{num_str}. {core_name}"
                else:
                    main_match = re.match(r"^\d+\.\s*(.*)$", old_title)
                    core_name = main_match.group(1).strip() if main_match else old_title
                    num_str = f"{global_counter:02d}"
                    new_title = f"{num_str}. {core_name}"
                    global_counter += 1

                if new_title != old_title:
                    self.client.update_task(account_id, list_id, t_id, {
                        "title": new_title,
                        "notes": t.get("notes", ""),
                        "status": t.get("status", "needsAction")
                    })
                    self.log(f"Nummering gecorrigeerd in '{list_title}': '{old_title}' ➔ '{new_title}'")
                    time.sleep(0.03)

        except Exception as e:
            self.log(f"Fout bij hernummeren van '{list_title}': {str(e)}", level="error")

    def reassign_tasks_batch(self, moves: List[Dict[str, Any]], account_id: Optional[str] = None) -> Dict[str, Any]:
        """Verplaatst taken naar een andere lijst (doel-lijst), voorkomt duplicaten en maakt nummering sluitend."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts")
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        lists_by_title = {l["title"]: l["id"] for l in tasklists}
        lists_by_id = {l["id"]: l["title"] for l in tasklists}

        # Track all affected lists (both source and target) to renumber them at the end
        affected_lists = set()

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
                    lists_by_id[target_list_id] = target_title

            if target_list_id and cur_list_id != target_list_id:
                affected_lists.add((cur_list_id, lists_by_id.get(cur_list_id, "Bronlijst")))
                affected_lists.add((target_list_id, target_title))

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

        # Automatic Renumbering of all affected lists
        for l_id, l_title in affected_lists:
            if l_id:
                self.renumber_list_tasks(target_account, l_id, l_title)

        self.log(f"Batch herindeling voltooid: {success_count} taken verplaatst en nummering gecorrigeerd.", level="success")
        return {"success": True, "moved_count": success_count}

    def apply_captain_division(self, roy_tasks: List[Dict[str, Any]], karen_tasks: List[Dict[str, Any]], account_id: Optional[str] = None) -> Dict[str, Any]:
        """Past de verdeling toe: verplaatst/zet taken in 03. Kapitein Roy en 04. Kapitein Karen met duplicaat-check en hernummering."""
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

        # 3. Renumber both captain lists to guarantee 01..N sequential numbering
        if roy_list_id:
            self.renumber_list_tasks(target_account, roy_list_id, "03. Kapitein Roy")
        if karen_list_id:
            self.renumber_list_tasks(target_account, karen_list_id, "04. Kapitein Karen")

        self.log("Kapiteinsverdeling succesvol gesynchroniseerd en genummerd!", level="success")
        return {"success": True, "roy_count": len(roy_tasks), "karen_count": len(karen_tasks)}
