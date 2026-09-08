import time
import json
import re
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional
from threading import Timer
from google_client import GoogleTasksClient

DEFAULT_CATEGORIES = [
    "Bouw",
    "Huishouden",
    "Gezinshuis",
    "Persoonlijk",
    "Ongelabeld"
]

class SyncEngine:
    def __init__(self, client: GoogleTasksClient, sync_interval_seconds: int = 900):
        self.client = client
        self.sync_interval = sync_interval_seconds
        self.is_syncing = False
        self.last_sync_time: Optional[str] = None
        self.last_sync_status: str = "Gereed"
        self.logs: List[Dict[str, Any]] = []
        self._timer: Optional[Timer] = None

        # Persistent completion history store
        self.history_file = "/data/completion_history.json"
        if not os.path.exists("/data") and not os.path.isdir("/data"):
            self.history_file = os.path.join(os.path.dirname(__file__), "completion_history.json")
        self.completion_history: Dict[str, Any] = {}
        self.load_completion_history()

        # Persistent custom categories store
        self.categories_file = "/data/custom_categories.json"
        if not os.path.exists("/data") and not os.path.isdir("/data"):
            self.categories_file = os.path.join(os.path.dirname(__file__), "custom_categories.json")
        self.custom_categories: List[str] = []
        self.load_custom_categories()

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

    # =========================================================================
    # COMPLETION HISTORY & RECURRING TASK LOGIC
    # =========================================================================
    def load_completion_history(self):
        """Laadt de persistente voltooiingsgeschiedenis van taken."""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.completion_history = data.get("tasks", {})
        except Exception as e:
            print(f"Kon completion history niet laden: {e}")
            self.completion_history = {}

    def save_completion_history(self):
        """Slaat de voltooiingsgeschiedenis persistent op in /data (Home Assistant storage)."""
        try:
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump({"tasks": self.completion_history}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Kon completion history niet opslaan: {e}")

    def clean_category_name(self, name: str) -> str:
        if not name:
            return ""
        c = name.replace("📂", "").replace("📁", "").strip()
        c = re.sub(r"^\d+[\.\)]\s*", "", c).strip()
        return c

    def load_custom_categories(self):
        """Laadt handmatig toegevoegde en uitgesloten categorieën van disk."""
        try:
            if os.path.exists(self.categories_file):
                with open(self.categories_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.custom_categories = [self.clean_category_name(x) for x in data.get("categories", []) if x]
                    self.excluded_categories = [self.clean_category_name(x) for x in data.get("excluded", []) if x]
        except Exception as e:
            print(f"Kon custom categories niet laden: {e}")
            self.custom_categories = []
            self.excluded_categories = []

    def save_custom_categories(self):
        """Slaat handmatig toegevoegde en uitgesloten categorieën op disk op."""
        try:
            os.makedirs(os.path.dirname(self.categories_file), exist_ok=True)
            with open(self.categories_file, "w", encoding="utf-8") as f:
                json.dump({
                    "categories": self.custom_categories,
                    "excluded": getattr(self, "excluded_categories", [])
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Kon custom categories niet opslaan: {e}")

    def get_all_categories(self) -> List[str]:
        """Geeft alle unieke categorieën terug (standaard + custom - excluded)."""
        cats = set(DEFAULT_CATEGORIES)
        for c in self.custom_categories:
            if c:
                cats.add(self.clean_category_name(c))
        for ex in getattr(self, "excluded_categories", []):
            if ex in cats:
                cats.remove(ex)
        cats.add("Ongelabeld")
        return sorted(list(cats), key=lambda s: s.lower())

    def delete_category(self, category_name: str, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Verwijdert een categorie en verplaatst alle taken in die categorie naar 'Ongelabeld'."""
        clean_cat = self.clean_category_name(category_name)
        if not clean_cat:
            raise ValueError("Categorienaam mag niet leeg zijn")

        if clean_cat.lower() == "ongelabeld":
            raise ValueError("De categorie 'Ongelabeld' kan niet worden verwijderd")

        accounts = self.client.get_accounts()
        if not accounts:
            return {"success": False, "error": "Geen accounts geconfigureerd"}

        targets = [account_id] if account_id and account_id in accounts else list(accounts.keys())
        reassigned_count = 0

        # Verwijder uit custom categories en sla op
        self.custom_categories = [c for c in self.custom_categories if self.clean_category_name(c).lower() != clean_cat.lower()]
        
        # Voeg toe aan excluded_categories zodat standaard categorieën ook niet terugkeren
        if not hasattr(self, "excluded_categories"):
            self.excluded_categories = []
        if clean_cat not in self.excluded_categories:
            self.excluded_categories.append(clean_cat)
        self.save_custom_categories()

        # Update alle taken die deze categorie hadden
        for acc in targets:
            tasklists = self.client.list_tasklists(acc)
            for tl in tasklists:
                list_id = tl["id"]
                raw_tasks = self.client.list_tasks(acc, list_id)
                for t in raw_tasks:
                    if t.get("deleted"):
                        continue
                    notes = t.get("notes", "") or ""
                    
                    # Check of taak gekoppeld is aan deze categorie via [tag]
                    cat_match = False
                    tags = re.findall(r"\[(.*?)\]", notes)
                    for tag in tags:
                        if self.clean_category_name(tag).lower() == clean_cat.lower():
                            cat_match = True
                            break
                    
                    if cat_match:
                        # Herschrijf de categorie tag in notes naar [Ongelabeld]
                        new_notes = self.format_task_notes(notes=notes, sublist="Ongelabeld")
                        try:
                            self.client.update_task(acc, list_id, t["id"], {"notes": new_notes})
                            reassigned_count += 1
                            self.log(f"Taak '{t.get('title')}' verplaatst van '{clean_cat}' naar 'Ongelabeld'")
                        except Exception as e:
                            self.log(f"Kon taak '{t.get('title')}' niet bijwerken naar 'Ongelabeld': {e}", level="warning")

        self.log(f"🗑️ Categorie '{clean_cat}' verwijderd. {reassigned_count} taken verplaatst naar 'Ongelabeld'.", level="success")
        return {
            "success": True,
            "deleted_category": clean_cat,
            "reassigned_count": reassigned_count,
            "categories": self.get_all_categories()
        }

    def clean_task_title(self, title: str) -> str:
        """Stript hardcoded volgnummers (zoals '05. ', '01. Bouw - Verwarming - 02. ') uit de taaktitel."""
        clean = (title or "").strip()
        clean = clean.replace("📂", "").strip()
        clean = re.sub(r"^\d+\.\s*.*?[-\–]\s*\d+\.\s*", "", clean).strip()
        clean = re.sub(r"^\d+\.\s*.*?[-\–]\s*", "", clean).strip()
        clean = re.sub(r"^\d+[\.\)]\s*", "", clean).strip()
        return clean or (title or "").strip()

    def _normalize_title_key(self, title: str) -> str:
        """Normaliseert taaktitels voor robuuste historie-koppeling (stript volgnummers en prefixes)."""
        return self.clean_task_title(title).lower()

    def record_task_completion(self, task_id: str, title: str, completed_at: Optional[str] = None, frequency: Optional[str] = None):
        """Registreert het tijdstip waarop een taak is voltooid."""
        now_iso = completed_at or datetime.now(timezone.utc).isoformat()
        now_date = now_iso[:10]
        key = self._normalize_title_key(title)
        if not key:
            return

        if key not in self.completion_history:
            self.completion_history[key] = {
                "title": title,
                "task_id": task_id,
                "last_completed_at": now_iso,
                "last_completed_date": now_date,
                "frequency": frequency,
                "history": []
            }
        else:
            self.completion_history[key]["last_completed_at"] = now_iso
            self.completion_history[key]["last_completed_date"] = now_date
            if frequency:
                self.completion_history[key]["frequency"] = frequency
            if task_id:
                self.completion_history[key]["task_id"] = task_id

        hist_list = self.completion_history[key].setdefault("history", [])
        if not hist_list or hist_list[-1].get("completed_at") != now_iso:
            hist_list.append({"completed_at": now_iso, "date": now_date})
            if len(hist_list) > 20:
                self.completion_history[key]["history"] = hist_list[-20:]

        self.save_completion_history()

    def extract_frequency_from_notes(self, notes: str) -> Optional[str]:
        """Haalt de minimale frequentie uit de tags in notities [🔄 ...]."""
        clean = (notes or "").strip()
        while True:
            m = re.match(r"^\[(.*?)\]\s*", clean)
            if not m:
                break
            tag = m.group(1).strip()
            t_low = tag.lower()
            if tag.startswith("🔄") or t_low.startswith("frequentie:") or t_low in ["eenmalig", "dagelijks", "wekelijks", "maandelijks", "per kwartaal", "per half jaar", "eens per jaar"] or t_low.startswith("om de ") or t_low.startswith("elke "):
                clean_f = tag.replace("🔄", "").strip()
                if clean_f.lower().startswith("frequentie:"):
                    clean_f = clean_f[11:].strip()
                return clean_f
            clean = clean[m.end():].strip()
        return None

    def should_reset_task(self, frequency: str, completed_at_str: str) -> bool:
        """Bepaalt of een voltooide herhalende taak opnieuw op onvoltooid gezet moet worden."""
        if not frequency or not completed_at_str:
            return False

        f_low = frequency.strip().lower().replace("🔄", "").strip()
        if f_low in ["eenmalig", "geen", "geen / eenmalig", "none", ""]:
            return False

        try:
            c_clean = completed_at_str.replace("Z", "+00:00")
            if "T" in c_clean:
                comp_dt = datetime.fromisoformat(c_clean)
            else:
                comp_dt = datetime.strptime(c_clean[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)

            now = datetime.now(comp_dt.tzinfo if comp_dt.tzinfo else timezone.utc)
            elapsed = now - comp_dt
            elapsed_days = elapsed.total_seconds() / 86400.0

            if f_low == "dagelijks":
                # Heropen indien op een eerdere kalenderdag voltooid of >= 20 uur verstreken
                return comp_dt.date() < now.date() or elapsed_days >= 0.85

            elif f_low == "wekelijks":
                return elapsed_days >= 6.8

            elif f_low == "maandelijks":
                return elapsed_days >= 27.5

            elif f_low == "per kwartaal":
                return elapsed_days >= 89.0

            elif f_low == "per half jaar":
                return elapsed_days >= 180.0

            elif f_low == "eens per jaar":
                return elapsed_days >= 364.0

            # Aangepast / Custom: bijv. "om de 6 weken", "om de 3 dagen", "elke 14 dagen"
            m = re.search(r"(?:om\s*de|elke)?\s*(\d+)\s*(dag|dagen|week|weken|maand|maanden|mnd|kwartaal|kwartalen|half\s*jaar|jaar|jaren)", f_low)
            if m:
                qty = int(m.group(1))
                unit = m.group(2)
                if "dag" in unit:
                    target_days = qty * 0.95
                elif "week" in unit:
                    target_days = qty * 7.0 - 0.2
                elif "maand" in unit or "mnd" in unit:
                    target_days = qty * 30.0 - 1.0
                elif "kwartaal" in unit:
                    target_days = qty * 90.0 - 2.0
                elif "half" in unit:
                    target_days = qty * 182.0 - 3.0
                elif "jaar" in unit:
                    target_days = qty * 365.0 - 5.0
                else:
                    target_days = qty * 7.0
                return elapsed_days >= target_days

        except Exception as e:
            print(f"Fout bij frequentie reset check voor '{frequency}' ({completed_at_str}): {e}")

        return False

    def toggle_task_status(self, task_id: str, list_id: str, target_status: Optional[str] = None, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Zet een taak op voltooid (completed) of onvoltooid (needsAction) in Google Tasks en registreert het tijdstip."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts geconfigureerd")

        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]

        new_status = target_status
        if not new_status:
            # Haal huidige taak op om status te inverteren
            task_data = self.client.api_request(target_account, f"https://tasks.googleapis.com/tasks/v1/lists/{list_id}/tasks/{task_id}")
            cur = task_data.get("status", "needsAction") if task_data else "needsAction"
            new_status = "needsAction" if cur == "completed" else "completed"

        now_iso = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {"status": new_status}
        if new_status == "completed":
            payload["completed"] = now_iso

        res = self.client.update_task(target_account, list_id, task_id, payload)
        if not res:
            raise ValueError(f"Kon status van taak '{task_id}' niet bijwerken in Google Tasks")

        t_title = res.get("title", "") if isinstance(res, dict) else ""
        t_notes = res.get("notes", "") if isinstance(res, dict) else ""
        freq = self.extract_frequency_from_notes(t_notes)

        if new_status == "completed":
            self.record_task_completion(task_id, t_title, completed_at=now_iso, frequency=freq)
            self.log(f"Taak '{t_title or task_id}' gemarkeerd als voltooid ✓", level="success")
        else:
            self.log(f"Taak '{t_title or task_id}' weer geopend (onvoltooid)", level="info")

        return {
            "success": True,
            "task_id": task_id,
            "status": new_status,
            "completed_at": now_iso if new_status == "completed" else None
        }

    def check_and_reset_recurring_tasks(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Controleert alle voltooide herhalende taken en reset deze naar 'needsAction' zodra de frequentiecriteria verstreken zijn."""
        accounts = self.client.get_accounts()
        if not accounts:
            return {"reset_count": 0, "reset_tasks": []}

        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)

        reset_tasks = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for tl in tasklists:
            list_id = tl["id"]
            list_title = tl["title"]
            raw_tasks = self.client.list_tasks(target_account, list_id)
            for t in raw_tasks:
                if t.get("deleted") or t.get("title", "").startswith("📂 "):
                    continue

                t_status = t.get("status", "needsAction")
                t_title = t.get("title", "").strip()
                t_id = t.get("id")
                t_notes = t.get("notes", "")
                freq = self.extract_frequency_from_notes(t_notes)

                if t_status == "completed":
                    completed_at = t.get("completed")
                    t_key = self._normalize_title_key(t_title)
                    if not completed_at and t_key in self.completion_history:
                        completed_at = self.completion_history[t_key].get("last_completed_at")

                    if completed_at:
                        self.record_task_completion(t_id, t_title, completed_at=completed_at, frequency=freq)

                    if freq and completed_at and self.should_reset_task(freq, completed_at):
                        updated = self.client.update_task(target_account, list_id, t_id, {
                            "status": "needsAction"
                        })
                        if updated:
                            if t_key in self.completion_history:
                                self.completion_history[t_key]["last_reset_at"] = now_iso
                            self.save_completion_history()
                            disp_date = completed_at[:10]
                            self.log(f"🔄 Herhalende taak '{t_title}' in '{list_title}' automatisch weer op onvoltooid gezet (frequentie: {freq}, voltooid op {disp_date})", level="success")
                            reset_tasks.append({
                                "id": t_id,
                                "title": t_title,
                                "list_title": list_title,
                                "frequency": freq,
                                "completed_at": completed_at
                            })

        return {
            "success": True,
            "reset_count": len(reset_tasks),
            "reset_tasks": reset_tasks
        }

    def move_task_position(self, task_id: str, list_id: str, new_position: int, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Verplaatst een taak naar een nieuwe positie in de Google Tasks lijst en herrangschikt de overige taken."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts geconfigureerd")
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]

        raw_tasks = self.client.list_tasks(target_account, list_id)
        active_tasks = [t for t in raw_tasks if not t.get("deleted") and not t.get("title", "").startswith("📂 ")]
        active_tasks.sort(key=lambda x: x.get("position", ""))

        cur_idx = -1
        for idx, t in enumerate(active_tasks):
            if t.get("id") == task_id:
                cur_idx = idx
                break

        if cur_idx == -1:
            raise ValueError(f"Taak '{task_id}' niet gevonden in lijst '{list_id}'")

        target_idx = max(0, min(new_position - 1, len(active_tasks) - 1))
        if cur_idx == target_idx:
            return {"success": True, "position": new_position}

        moved_task = active_tasks.pop(cur_idx)
        active_tasks.insert(target_idx, moved_task)

        # In Google Tasks API:
        # Als target_idx == 0: verplaats naar begin van lijst (previous=None)
        # Anders: verplaats direct achter de taak op target_idx - 1
        previous_id = None
        if target_idx > 0:
            previous_id = active_tasks[target_idx - 1]["id"]

        success = self.client.move_task(target_account, list_id, task_id, previous_id=previous_id)
        clean_tit = self.clean_task_title(moved_task.get("title", ""))
        self.log(f"Taak '{clean_tit}' verplaatst naar positie #{new_position}. Overige taken in de lijst automatisch opnieuw gerangschikt.", level="success")

        # Map nieuwe posities
        new_positions = {t["id"]: i + 1 for i, t in enumerate(active_tasks)}
        return {
            "success": True,
            "task_id": task_id,
            "new_position": new_position,
            "positions": new_positions
        }

    def clean_all_task_titles(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Stript alle hardcoded volgnummers (bijv. '05. ') uit titels in Google Tasks."""
        accounts = self.client.get_accounts()
        if not accounts:
            return {"cleaned_count": 0}
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        cleaned_count = 0

        for tl in tasklists:
            list_id = tl["id"]
            raw_tasks = self.client.list_tasks(target_account, list_id)
            for t in raw_tasks:
                if t.get("deleted") or t.get("title", "").startswith("📂 "):
                    continue
                old_title = t.get("title", "")
                new_title = self.clean_task_title(old_title)
                if new_title and new_title != old_title:
                    self.client.update_task(target_account, list_id, t["id"], {
                        "title": new_title,
                        "notes": t.get("notes", ""),
                        "status": t.get("status", "needsAction")
                    })
                    cleaned_count += 1
                    time.sleep(0.02)

        if cleaned_count > 0:
            self.log(f"Volgnummers succesvol verwijderd uit {cleaned_count} taken in Google Tasks!", level="success")
        return {"success": True, "cleaned_count": cleaned_count}

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
            primary_id = account_ids[0] if account_ids else None

            # Controleer en heropen herhalende taken volgens hun minimale frequentie
            if primary_id:
                try:
                    self.check_and_reset_recurring_tasks(primary_id)
                except Exception as e:
                    self.log(f"Fout bij controle herhalende taken: {e}", level="warning")

            if len(account_ids) < 2:
                msg = f"Multi-account sync overgeslagen ({len(account_ids)} account actief)."
                self.log(msg, level="warning")
                self.last_sync_status = msg
                self.last_sync_time = time.strftime("%Y-%m-%d %H:%M:%S")
                return {"status": "skipped", "message": msg}

            # Multi-account sync
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
        """Haalt alle taken op uit alle lijsten met hun huidige lijstnaam, stript nummers uit titels, berekent lijstposities en levert voltooiingshistorie mee."""
        accounts = self.client.get_accounts()
        if not accounts:
            return []
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        
        tasks_pool = []
        now_iso = datetime.now(timezone.utc).isoformat()

        for cl in tasklists:
            list_id = cl["id"]
            list_title = cl["title"]
            is_todo = (list_title.lower() == "to do")
            raw_tasks = self.client.list_tasks(target_account, list_id)
            active_tasks = [t for t in raw_tasks if not t.get("deleted") and not t.get("title", "").startswith("📂 ")]
            active_tasks.sort(key=lambda x: x.get("position", ""))
            total_in_list = len(active_tasks)

            for idx, t in enumerate(active_tasks):
                position_in_list = idx + 1
                tit = t.get("title", "").strip()
                clean_tit = self.clean_task_title(tit)
                t_id = t.get("id")
                t_notes = t.get("notes", "")
                t_status = t.get("status", "needsAction")
                completed_at = t.get("completed")
                t_key = self._normalize_title_key(clean_tit)
                freq = self.extract_frequency_from_notes(t_notes)

                # Voltooiingsgeschiedenis bijwerken en herhalende taak resetten indien criteria voldaan zijn
                if t_status == "completed":
                    if not completed_at and t_key in self.completion_history:
                        completed_at = self.completion_history[t_key].get("last_completed_at")

                    if completed_at:
                        self.record_task_completion(t_id, clean_tit, completed_at=completed_at, frequency=freq)

                    # Indien herhalend en criteria verstreken: automatisch weer openen
                    if freq and completed_at and self.should_reset_task(freq, completed_at):
                        try:
                            updated = self.client.update_task(target_account, list_id, t_id, {
                                "status": "needsAction"
                            })
                            if updated:
                                t_status = "needsAction"
                                if t_key in self.completion_history:
                                    self.completion_history[t_key]["last_reset_at"] = now_iso
                                self.save_completion_history()
                                disp_date = completed_at[:10]
                                self.log(f"🔄 Taak '{clean_tit}' in '{list_title}' automatisch weer op onvoltooid gezet (frequentie: {freq}, voltooid op {disp_date})", level="success")
                        except Exception as e:
                            print(f"Kon taak '{clean_tit}' niet automatisch resetten: {e}")

                # Bepaal recentste voltooiingstijdstip uit persistentie of API
                last_completed = (self.completion_history.get(t_key) or {}).get("last_completed_at") or completed_at

                issues = []
                if is_todo:
                    issues.append("Staat in 'To do' lijst")

                tasks_pool.append({
                    "id": t_id,
                    "title": clean_tit,
                    "raw_title": tit,
                    "notes": t_notes,
                    "status": t_status,
                    "completed": completed_at if t_status == "completed" else None,
                    "last_completed": last_completed,
                    "frequency": freq,
                    "position": position_in_list,
                    "total_in_list": total_in_list,
                    "due": t.get("due"),
                    "parent_id": t.get("parent"),
                    "current_list_id": list_id,
                    "current_list_title": list_title,
                    "is_todo": is_todo,
                    "needs_formatting": len(issues) > 0,
                    "issues": issues
                })
        
        # Sorteer: onvolledige taken bovenaan, daarna op lijst en positie
        tasks_pool.sort(key=lambda x: (not x.get("needs_formatting", False), x.get("current_list_title", ""), x.get("position", 999)))
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

                issues = []
                if is_todo:
                    issues.append("Staat in de 'To do' lijst")

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

        clean_sub = self.clean_category_name(sublist_name)
        if clean_sub and clean_sub.lower() != "ongelabeld":
            if hasattr(self, "excluded_categories") and any(x.lower() == clean_sub.lower() for x in self.excluded_categories):
                self.excluded_categories = [x for x in self.excluded_categories if x.lower() != clean_sub.lower()]
            if clean_sub not in self.custom_categories:
                self.custom_categories.append(clean_sub)
            self.save_custom_categories()

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

    def format_task_notes(self, notes: str = "", sublist: Optional[str] = None, timing: Optional[str] = None, frequency: Optional[str] = None) -> str:
        """Formatteert notities met gestandaardiseerde tags voor sublijst, timing [Vast in tijd]/[Los in tijd], en minimale frequentie [🔄 Wekelijks]."""
        import re
        clean_notes = (notes or "").strip()
        
        existing_sub = None
        existing_timing = None
        existing_freq = None
        
        # Parse alle leidende [...] tags e.g. [01. Bouw - Verwarming] [Vast in tijd] [🔄 Wekelijks]
        while True:
            m = re.match(r"^\[(.*?)\]\s*", clean_notes)
            if not m:
                break
            tag_content = m.group(1).strip()
            t_low = tag_content.lower()
            if t_low in ["vast in tijd", "vast", "⏰ vast in tijd"]:
                existing_timing = "vast"
            elif t_low in ["los in tijd", "los", "⏳ los in tijd"]:
                existing_timing = "los"
            elif tag_content.startswith("🔄") or t_low.startswith("frequentie:") or t_low in ["eenmalig", "dagelijks", "wekelijks", "maandelijks", "per kwartaal", "per half jaar", "eens per jaar"] or t_low.startswith("om de ") or t_low.startswith("elke "):
                clean_f = tag_content.replace("🔄", "").strip()
                if clean_f.lower().startswith("frequentie:"):
                    clean_f = clean_f[11:].strip()
                existing_freq = clean_f
            else:
                existing_sub = tag_content
            clean_notes = clean_notes[m.end():].strip()
            
        final_sub = sublist if sublist is not None else existing_sub
        final_timing = timing if timing is not None else existing_timing
        final_freq = frequency if frequency is not None else existing_freq
        
        clean_sub = (final_sub or "").replace("📂", "").strip()
        if clean_sub.lower().startswith("alle"):
            clean_sub = None
            
        parts = []
        if clean_sub:
            parts.append(f"[{clean_sub}]")
        if final_timing:
            ft_low = final_timing.lower()
            if "vast" in ft_low:
                parts.append("[Vast in tijd]")
            elif "los" in ft_low:
                parts.append("[Los in tijd]")
        if final_freq:
            cf = final_freq.replace("🔄", "").strip()
            if cf and cf.lower() not in ["geen", "none"]:
                parts.append(f"[🔄 {cf}]")
                
        tag_str = " ".join(parts)
        if tag_str and clean_notes:
            return f"{tag_str} {clean_notes}".strip()
        elif tag_str:
            return tag_str
        return clean_notes

    def create_new_sublist(self, name: str, list_title: Optional[str] = None, category: Optional[str] = None, create_folder_task: bool = False, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Maakt een nieuwe categorie definitie aan als persistente taakeigenschap (zonder thema of nummering)."""
        import re
        clean_name = name.replace("📂", "").replace("📁", "").strip()
        clean_name = re.sub(r"^\d+[\.\)]\s*", "", clean_name).strip()
        if not clean_name:
            raise ValueError("Categorienaam mag niet leeg zijn")

        if hasattr(self, "excluded_categories") and any(x.lower() == clean_name.lower() for x in self.excluded_categories):
            self.excluded_categories = [x for x in self.excluded_categories if x.lower() != clean_name.lower()]
            self.save_custom_categories()

        if clean_name not in self.custom_categories:
            self.custom_categories.append(clean_name)
            self.save_custom_categories()

        self.log(f"Categorie '{clean_name}' permanent geregistreerd", level="success")
        return {
            "success": True,
            "sublist_name": clean_name,
            "category_name": clean_name,
            "categories": self.get_all_categories(),
            "list_title": list_title or "Universeel",
            "folder_task_id": None
        }

    def delete_all_folder_header_tasks(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Verwijdert alle dummy mapkop-taken (startend met 📁 of 📂) uit Google Tasks, nadat eventuele subtaken eerst zijn ontkoppeld naar het hoofdniveau."""
        accounts = self.client.get_accounts()
        if not accounts:
            return {"success": False, "error": "Geen accounts"}

        targets = [account_id] if account_id and account_id in accounts else list(accounts.keys())
        deleted_count = 0
        unparented_count = 0
        deleted_folders = []

        for acc in targets:
            tasklists = self.client.list_tasklists(acc)
            for tl in tasklists:
                list_id = tl["id"]
                list_title = tl["title"]
                raw_tasks = self.client.list_tasks(acc, list_id)
                
                folder_tasks = [
                    t for t in raw_tasks 
                    if not t.get("deleted") and any(t.get("title", "").strip().startswith(p) for p in ["📁", "📂"])
                ]
                if not folder_tasks:
                    continue

                folder_ids = {f["id"]: f.get("title", "").strip() for f in folder_tasks}

                # 1. Ontkoppel eventuele subtaken die naar deze folders wijzen naar het hoofdniveau
                for t in raw_tasks:
                    if not t.get("deleted") and t.get("parent") in folder_ids:
                        t_id = t["id"]
                        f_title = folder_ids[t["parent"]]
                        try:
                            self.client.move_task(acc, list_id, t_id)
                            unparented_count += 1
                            self.log(f"Taak '{t.get('title')}' ontkoppeld van mapkop '{f_title}' naar hoofdniveau")
                        except Exception as e:
                            self.log(f"Kon taak '{t.get('title')}' niet ontkoppelen van mapkop: {e}", level="warning")

                # 2. Verwijder de dummy folder-taken
                for f in folder_tasks:
                    f_id = f["id"]
                    f_title = f.get("title", "").strip()
                    try:
                        self.client.delete_task(acc, list_id, f_id)
                        deleted_count += 1
                        deleted_folders.append(f"{list_title}: {f_title}")
                        self.log(f"🗑️ Mapkop '{f_title}' verwijderd uit lijst '{list_title}'", level="success")
                    except Exception as e:
                        self.log(f"Kon mapkop '{f_title}' niet verwijderen: {e}", level="error")

        return {
            "success": True,
            "deleted_count": deleted_count,
            "unparented_count": unparented_count,
            "deleted_folders": deleted_folders
        }
        
    def create_single_task(self, title: str, list_title: str, sublist_name: Optional[str] = None, notes: str = "", due: Optional[str] = None, timing: Optional[str] = "los", frequency: Optional[str] = None, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Maakt een nieuwe taak aan in de opgegeven hoofdlijst, eventueel gekoppeld aan een sublijst map, timing en frequentie eigenschap."""
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

        clean_sub_name = self.clean_category_name(sublist_name) or "Ongelabeld"
        if clean_sub_name.lower() != "ongelabeld":
            if hasattr(self, "excluded_categories") and any(x.lower() == clean_sub_name.lower() for x in self.excluded_categories):
                self.excluded_categories = [x for x in self.excluded_categories if x.lower() != clean_sub_name.lower()]
            if clean_sub_name not in self.custom_categories:
                self.custom_categories.append(clean_sub_name)
            self.save_custom_categories()


        # Formatteer notities met sublijst, timing en frequentie tags
        final_notes = self.format_task_notes(notes=notes, sublist=clean_sub_name, timing=timing, frequency=frequency)

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

        # Schone titel zonder hardcoded volgnummers
        clean_title = self.clean_task_title(title)

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

    def update_single_task(self, task_id: str, list_id: str, title: str, notes: str = "", due: Optional[str] = None, target_list_title: Optional[str] = None, sublist_name: Optional[str] = None, timing: Optional[str] = None, frequency: Optional[str] = None, status: Optional[str] = None, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Wijzigt titel, notities, deadline, timing, frequentie, status of verplaatst een taak naar een andere lijst of sublijst."""
        accounts = self.client.get_accounts()
        if not accounts:
            raise ValueError("Geen accounts geconfigureerd")
        
        target_account = account_id if account_id and account_id in accounts else list(accounts.keys())[0]
        tasklists = self.client.list_tasklists(target_account)
        lists_by_title = {l["title"]: l["id"] for l in tasklists}
        lists_by_id = {l["id"]: l["title"] for l in tasklists}

        clean_sub = self.clean_category_name(sublist_name)
        if clean_sub and clean_sub.lower() != "ongelabeld":
            if hasattr(self, "excluded_categories") and any(x.lower() == clean_sub.lower() for x in self.excluded_categories):
                self.excluded_categories = [x for x in self.excluded_categories if x.lower() != clean_sub.lower()]
            if clean_sub not in self.custom_categories:
                self.custom_categories.append(clean_sub)
            self.save_custom_categories()

        final_notes = self.format_task_notes(notes=notes, sublist=clean_sub if clean_sub else None, timing=timing, frequency=frequency)

        dest_list_id = lists_by_title.get(target_list_title) if target_list_title else list_id
        effective_dest_title = target_list_title or lists_by_id.get(dest_list_id, "Huidige Lijst")

        # Find matching parent folder in destination list
        parent_folder_id = None
        if dest_list_id and clean_sub:
            raw_dest = self.client.list_tasks(target_account, dest_list_id)
            clean_sub_pure = re.sub(r"^\d+\.\s*", "", clean_sub).strip().lower()
            for dt in raw_dest:
                if dt.get("deleted"):
                    continue
                dt_tit_clean = dt.get("title", "").replace("📂", "").strip().lower()
                if clean_sub_pure and (clean_sub_pure in dt_tit_clean or dt_tit_clean in clean_sub_pure):
                    parent_folder_id = dt["id"]
                    break

        # Schone titel zonder hardcoded volgnummers
        final_title = self.clean_task_title(title)

        body: Dict[str, Any] = {
            "title": final_title,
            "notes": final_notes
        }
        if status:
            body["status"] = status
        elif dest_list_id != list_id:
            body["status"] = "needsAction"

        if due:
            body["due"] = f"{due}T00:00:00.000Z" if len(due) == 10 else due
        else:
            body["due"] = None

        if dest_list_id and dest_list_id != list_id:
            # Move to new list
            created = self.client.create_task(target_account, dest_list_id, body)
            if task_id and list_id:
                self.client.delete_task(target_account, list_id, task_id)
            if parent_folder_id and created and "id" in created:
                try:
                    self.client.move_task(target_account, dest_list_id, created["id"], parent_id=parent_folder_id)
                except Exception:
                    pass
            self.renumber_list_tasks(target_account, list_id, lists_by_id.get(list_id, "Bronlijst"))
            self.renumber_list_tasks(target_account, dest_list_id, effective_dest_title)
            self.log(f"Taak '{final_title}' gewijzigd en verplaatst naar '{target_list_title}'", level="success")
            return {"success": True, "task_id": created.get("id") if created else None}
        else:
            updated = self.client.update_task(target_account, list_id, task_id, body)
            if parent_folder_id:
                try:
                    self.client.move_task(target_account, list_id, task_id, parent_id=parent_folder_id)
                except Exception:
                    pass
            self.renumber_list_tasks(target_account, list_id, effective_dest_title)
            self.log(f"Taak '{final_title}' succesvol gewijzigd", level="success")
            return {"success": True, "task_id": task_id}

    def renumber_list_tasks(self, account_id: str, list_id: str, list_title: str) -> None:
        """Houdt taaktitels schoon zonder hardcoded volgnummers."""
        try:
            raw_tasks = self.client.list_tasks(account_id, list_id)
            active_tasks = [t for t in raw_tasks if not t.get("deleted") and not t.get("title", "").startswith("📂 ")]
            for t in active_tasks:
                old_title = t.get("title", "").strip()
                t_id = t.get("id")
                if not old_title or not t_id:
                    continue
                new_title = self.clean_task_title(old_title)
                if new_title != old_title:
                    self.client.update_task(account_id, list_id, t_id, {
                        "title": new_title,
                        "notes": t.get("notes", ""),
                        "status": t.get("status", "needsAction")
                    })
                    time.sleep(0.02)
        except Exception as e:
            self.log(f"Fout bij opschonen titels in '{list_title}': {str(e)}", level="error")

    def reassign_tasks_batch(self, moves: List[Dict[str, Any]], account_id: Optional[str] = None) -> Dict[str, Any]:
        """Verplaatst taken naar een andere lijst of sub-lijst, voorkomt duplicaten en maakt nummering sluitend."""
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
            target_sub = m.get("target_sublist")
            target_timing = m.get("target_timing")
            target_frequency = m.get("target_frequency")
            t_title = (m.get("title") or "").strip()
            t_notes = m.get("notes", "")
            t_status = m.get("status", "needsAction")

            target_list_id = lists_by_title.get(target_title) if target_title else None
            if not target_list_id and target_title:
                # Maak lijst aan indien niet bestaand
                new_l = self.client.create_tasklist(target_account, target_title)
                if new_l:
                    target_list_id = new_l["id"]
                    lists_by_title[target_title] = target_list_id
                    lists_by_id[target_list_id] = target_title

            clean_sub = self.clean_category_name(target_sub)
            if clean_sub and clean_sub.lower() != "ongelabeld":
                if hasattr(self, "excluded_categories") and any(x.lower() == clean_sub.lower() for x in self.excluded_categories):
                    self.excluded_categories = [x for x in self.excluded_categories if x.lower() != clean_sub.lower()]
                if clean_sub not in self.custom_categories:
                    self.custom_categories.append(clean_sub)
                self.save_custom_categories()

            final_notes = self.format_task_notes(notes=t_notes, sublist=clean_sub if clean_sub else None, timing=target_timing, frequency=target_frequency)

            # Find matching parent folder in target list if exists
            parent_folder_id = None
            if target_list_id and clean_sub:
                raw_dest_tasks = self.client.list_tasks(target_account, target_list_id)
                clean_sub_pure = re.sub(r"^\d+\.\s*", "", clean_sub).strip().lower()
                for dt in raw_dest_tasks:
                    if dt.get("deleted"):
                        continue
                    dt_tit_clean = dt.get("title", "").replace("📂", "").strip().lower()
                    if clean_sub_pure and (clean_sub_pure in dt_tit_clean or dt_tit_clean in clean_sub_pure):
                        parent_folder_id = dt["id"]
                        break

            # Schone titel zonder hardcoded volgnummers
            final_title = self.clean_task_title(t_title)

            if target_list_id and cur_list_id != target_list_id:
                affected_lists.add((cur_list_id, lists_by_id.get(cur_list_id, "Bronlijst")))
                affected_lists.add((target_list_id, target_title))

                existing_in_target = get_existing_in_list(target_list_id)

                if final_title in existing_in_target:
                    # Update bestaande taak in doellijst in plaats van dubbel aanmaken
                    existing_id = existing_in_target[final_title]
                    self.client.update_task(target_account, target_list_id, existing_id, {
                        "title": final_title,
                        "notes": final_notes,
                        "status": t_status
                    })
                    if parent_folder_id:
                        try:
                            self.client.move_task(target_account, target_list_id, existing_id, parent_id=parent_folder_id)
                        except Exception:
                            pass
                    self.log(f"Bestaande taak in '{target_title}' bijgewerkt: '{final_title}' (sub: {clean_sub or 'onveranderd'}, timing: {target_timing or 'onveranderd'})")
                else:
                    # Maak aan in nieuwe lijst
                    created = self.client.create_task(target_account, target_list_id, {
                        "title": final_title,
                        "notes": final_notes,
                        "status": t_status
                    })
                    if created and "id" in created:
                        existing_in_target[final_title] = created["id"]
                        if parent_folder_id:
                            try:
                                self.client.move_task(target_account, target_list_id, created["id"], parent_id=parent_folder_id)
                            except Exception:
                                pass
                    self.log(f"Taak '{final_title}' verplaatst naar '{target_title}' (sub: {clean_sub or 'onveranderd'}, timing: {target_timing or 'onveranderd'})")

                # Verwijder uit oude lijst
                if t_id and cur_list_id:
                    self.client.delete_task(target_account, cur_list_id, t_id)
                
                success_count += 1
                time.sleep(0.04)

            elif (target_list_id and cur_list_id == target_list_id) or (not target_title and cur_list_id):
                # Taak blijft in dezelfde lijst maar wisselt van sublijst, timing of notities
                effective_lid = target_list_id or cur_list_id
                effective_ltitle = target_title or lists_by_id.get(effective_lid, "Lijst")
                affected_lists.add((effective_lid, effective_ltitle))
                self.client.update_task(target_account, effective_lid, t_id, {
                    "title": final_title,
                    "notes": final_notes,
                    "status": t_status
                })
                if parent_folder_id:
                    try:
                        self.client.move_task(target_account, effective_lid, t_id, parent_id=parent_folder_id)
                    except Exception:
                        pass
                self.log(f"Taak '{final_title}' bijgewerkt (sub: {clean_sub or 'onveranderd'}, timing: {target_timing or 'onveranderd'}) in '{effective_ltitle}'")
                success_count += 1
                time.sleep(0.04)

        # Automatic Renumbering of all affected lists
        for l_id, l_title in affected_lists:
            if l_id:
                self.renumber_list_tasks(target_account, l_id, l_title)

        self.log(f"Batch herindeling voltooid: {success_count} taken verplaatst/gewijzigd en nummering gecorrigeerd.", level="success")
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
