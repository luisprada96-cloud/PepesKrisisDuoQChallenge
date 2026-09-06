"""One background job per integration, shared by manual and scheduled requests."""
import copy
import threading
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class SyncJobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.states = {}

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.states)

    def start(self, name, callback):
        with self.lock:
            previous = self.states.get(name, {})
            if previous.get("running"):
                return {"success": True, "alreadyRunning": True, "job": copy.deepcopy(previous)}
            state = {"running": True, "startedAt": utc_now(), "lastSuccessAt": previous.get("lastSuccessAt"), "error": None}
            self.states[name] = state
            response = copy.deepcopy(state)
        threading.Thread(target=self._run, args=(name, callback), daemon=True).start()
        return {"success": True, "alreadyRunning": False, "job": response}

    def _run(self, name, callback):
        try:
            result = callback() or {"success": False, "error": "La sincronización no devolvió un resultado."}
        except Exception:
            result = {"success": False, "error": "No se pudo completar la sincronización. Consulta el registro del servidor."}
        with self.lock:
            state = self.states[name]
            state.update(running=False, finishedAt=utc_now(), success=bool(result.get("success")), error=result.get("error"))
            if state["success"]:
                state["lastSuccessAt"] = state["finishedAt"]
            state["pending"] = result.get("pending", 0)
