"""Bounded, operator-owned post-task learning for both chat surfaces.

Reflection and evaluation run outside the foreground response. Each model call
is reserved durably before starting; learned text never changes the evaluator.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable, Iterator

from .config import load_tako_toml
from .inference import PI_TYPE1_MODEL_DEFAULT, inference_model_for_lane, run_learning_inference
from .learning import LearningError, LearningStore, _guard, redact


LEARN_USAGE = (
    "learn status|review|list|show <revision-id>|feedback <experience-id> "
    "success|failure [note]|evaluate <revision-id>|promote <revision-id>|rollback <revision-id>"
)


class LearningService:
    def __init__(self, workspace_root: Path, state_dir: Path, runtime=None) -> None:
        self.workspace_root = Path(workspace_root)
        self.state_dir = Path(state_dir)
        self._store: LearningStore | None = None
        self.runtime = runtime
        self.runtime_path = Path(state_dir) / "learning" / "runtime.json"
        self._task: asyncio.Task | None = None
        self.paused = False

    @property
    def store(self) -> LearningStore:
        if self._store is None:
            self._store = LearningStore(self.state_dir)
        return self._store

    def _model(self) -> str:
        model = inference_model_for_lane("type1")
        return PI_TYPE1_MODEL_DEFAULT if not model or model == "auto" else model

    def _config(self):
        cfg, warning = load_tako_toml(self.workspace_root / "tako.toml")
        if warning:
            raise LearningError("Learning paused: tako.toml could not be read safely.")
        return cfg.learning

    @contextmanager
    def _state(self) -> Iterator[dict]:
        """Use a nonblocking lock so learning cannot stall a chat response."""
        import fcntl

        path = self.runtime_path
        _guard(path)
        _guard(path.with_suffix(".lock"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LearningError("Learning state is busy; try again shortly.") from exc
            try:
                if path.exists() and path.stat().st_size > 1_000_000:
                    raise LearningError("Learning runtime state is too large; preserved unchanged.")
                state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                if not isinstance(state, dict):
                    raise LearningError("Invalid learning runtime state; operator repair required.")
                if type(state.get("calls_used", 0)) is not int or state.get("calls_used", 0) < 0:
                    raise LearningError("Invalid learning budget; operator repair required.")
                today = datetime.now(timezone.utc).date().isoformat()
                if state.get("budget_day") != today:
                    state.update(budget_day=today, calls_used=0)
                yield state
                descriptor, temporary = tempfile.mkstemp(prefix=".runtime-", suffix=".tmp", dir=path.parent)
                try:
                    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                        handle.write(json.dumps(state, indent=2) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    _guard(path)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _record_error(self, exc: Exception) -> None:
        # Provider output can contain credentials or transcript content. Persist
        # the exception category, never raw model/subprocess error text.
        try:
            with self._state() as state:
                state["last_error"] = (redact(str(exc), 500) if isinstance(exc, LearningError)
                                       else f"{type(exc).__name__}: learning operation failed; see inference diagnostics.")
                state["last_finished_at"] = time.time()
        except Exception:
            pass

    def context(self, query: str, *, operator: bool = True) -> tuple[str, tuple[str, ...]]:
        if not operator or self.paused:
            return "", ()
        try:
            cfg = self._config()
            if not cfg.enabled:
                return "", ()
            return self.store.context(query, max_chars=cfg.max_context_chars,
                                      max_skills=cfg.max_active_skills, model=self._model())
        except Exception as exc:
            self._record_error(exc)
            return "", ()

    def record_turn(
        self, session_key: str, user_text: str, assistant_text: str,
        *, revision_ids: tuple[str, ...] = (), operator: bool = True,
    ) -> str | None:
        if not operator or self.paused:
            return None
        try:
            if not self._config().enabled:
                return None
            # Greetings, acknowledgements and unavailable-provider messages do
            # not contain a reusable task. Successful generation is not proof
            # that the task succeeded: the core records outcome="unknown".
            if len(user_text.strip()) < 24 or len(assistant_text.strip()) < 40:
                return None
            experience_id = self.store.record_turn(
                session_key, user_text, assistant_text, revision_ids=revision_ids, operator=True,
            )
            self.schedule_review()
            return experience_id
        except Exception as exc:
            self._record_error(exc)
            return None

    def _busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def pause(self) -> None:
        """Stop follow-on learning work during safe mode or app shutdown."""
        self.paused = True
        if self._busy():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def resume(self) -> None:
        self.paused = False

    def _queue(self, operation: Callable, *, name: str) -> str:
        if self.paused:
            return "Learning is paused by safe mode or shutdown."
        if self._busy():
            return "Learning is already running; use `learn status`."
        if not self._config().enabled:
            return "Learning is disabled in tako.toml."
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run(operation), name=f"tako-learning-{name}")
        return f"Learning {name} queued in the background; use `learn status`."

    async def _run(self, operation: Callable) -> None:
        try:
            await operation()
        except asyncio.CancelledError:
            try:
                with self._state() as state:
                    state["last_error"] = "Learning interrupted; reserved model calls remain counted."
            except Exception:
                pass
            raise
        except Exception as exc:
            self._record_error(exc)

    def schedule_review(self, *, manual: bool = False) -> str:
        return self._queue(lambda: self._review(manual=manual), name="review")

    async def _infer(self, prompt: str, *, model: str) -> str:
        cfg = self._config()
        if not cfg.enabled or self.paused:
            raise LearningError("Learning is disabled.")
        if self.runtime is None or not self.runtime.ready:
            raise LearningError("Learning inference is unavailable.")
        if self.runtime.selected_provider != "pi":
            raise LearningError("Learning requires the selected pi provider; automatic provider switching is disabled.")
        with self._state() as state:
            used = int(state.get("calls_used", 0))
            if used >= cfg.daily_call_budget:
                raise LearningError("Daily learning call budget exhausted.")
            state["calls_used"] = used + 1
            state["last_call_at"] = time.time()
        return await asyncio.to_thread(
            run_learning_inference, self.runtime, prompt, timeout_s=45, model=model,
        )

    async def _review(self, *, manual: bool) -> None:
        cfg = self._config()
        if not cfg.enabled:
            return
        evidence = self.store.recent_experiences()
        if not evidence:
            raise LearningError("No meaningful operator experiences to review.")
        stamps = [f"{row['id']}:{row.get('outcome', 'unknown')}:{row.get('note', '')}" for row in evidence]
        digest = hashlib.sha256(json.dumps(stamps).encode()).hexdigest()
        now = time.time()
        with self._state() as state:
            reviewed = set(state.get("reviewed_evidence", []))
            fresh = [stamp for stamp in stamps if stamp not in reviewed]
            if state.get("review_fingerprint") == digest:
                state["last_result"] = "No new operator evidence since the last review."
                return
            if not manual and len(fresh) < cfg.review_every:
                return
            if now - float(state.get("last_review_at", 0)) < cfg.cooldown_seconds:
                state["last_result"] = "Review deferred until the configured cooldown expires."
                return
            if int(state.get("calls_used", 0)) >= cfg.daily_call_budget:
                state["last_result"] = "Daily learning call budget exhausted."
                return
            # Persist before inference, including failed attempts. Restarting or
            # repeated commands cannot repeatedly spend on identical evidence.
            state.update(last_review_at=now, review_fingerprint=digest, reviewed_evidence=stamps,
                         last_error="", last_result="Generating a candidate from operator experience.")
        model = self._model()

        async def infer(prompt: str) -> str:
            return await self._infer(prompt, model=model)

        revision = await self.store.propose(infer, model=model)
        with self._state() as state:
            state["last_result"] = (f"Candidate {revision['id']} created; evaluation required before promotion."
                                    if revision else "No reusable procedure found in new operator evidence.")
            state["last_finished_at"] = time.time()
        if revision and not self.paused and self._config().auto_promote:
            await self._evaluate(revision["id"], auto_promote=True)

    async def _evaluate(self, revision_id: str, *, auto_promote: bool = False) -> None:
        cfg = self._config()
        if not cfg.enabled:
            return
        model = self._model()

        async def infer(prompt: str) -> str:
            return await self._infer(prompt, model=model)

        with self._state() as state:
            remaining_calls = max(0, cfg.daily_call_budget - int(state.get("calls_used", 0)))
        report = await self.store.evaluate(
            revision_id, infer, model=model, max_cases=20,
            max_calls=min(40, remaining_calls), deadline_seconds=120,
        )
        with self._state() as state:
            state["last_result"] = f"Evaluation finished for {revision_id}; `learn show {revision_id}` includes the report."
            state["last_finished_at"] = time.time()
            state["last_error"] = report.get("error", "")
        if (auto_promote and not self.paused and self._config().enabled
                and self._config().auto_promote and self._model() == model):
            self.store.promote(revision_id, model=model, operator=True)
            with self._state() as state:
                state["last_result"] = f"Candidate {revision_id} passed fixed gates and was promoted."

    def status(self) -> dict:
        cfg = self._config()
        with self._state() as state:
            runtime = dict(state)
        runtime.pop("reviewed_evidence", None)
        runtime.pop("review_fingerprint", None)
        return {
            **self.store.status(), "enabled": cfg.enabled, "auto_promote": cfg.auto_promote,
            "running": self._busy(), "paused": self.paused, "daily_call_budget": cfg.daily_call_budget,
            "review_every": cfg.review_every, "cooldown_seconds": cfg.cooldown_seconds,
            "model": self._model(), "provider": getattr(self.runtime, "selected_provider", None),
            **runtime,
            "recent_experience_ids": [row["id"] for row in self.store.recent_experiences()[-5:]],
            "recent_experiences": [{"id": row["id"], "outcome": row["outcome"],
                                    "request_preview": redact(row["user_text"], 120),
                                    "revision_ids": row["revision_ids"]}
                                   for row in self.store.recent_experiences()[-5:]],
        }

    async def command(self, rest: str, *, operator: bool) -> str:
        if not operator:
            return "Operator-only: learning experience, evaluation and activation require the operator."
        parts = rest.strip().split(maxsplit=3)
        action = parts[0].lower() if parts else "status"
        try:
            cfg = self._config()
            if action == "status" and len(parts) <= 1:
                result = self.status()
            elif action == "list" and len(parts) == 1:
                result = [{key: row.get(key) for key in ("id", "parent_id", "status", "created_at")}
                          | {"name": row.get("body", {}).get("name", "")} for row in self.store.list_revisions()]
            elif action == "show" and len(parts) == 2:
                result = {"revision": self.store.show(parts[1]), "evaluation": self.store.report(parts[1])}
            elif action == "rollback" and len(parts) == 2:
                result = self.store.rollback(parts[1], operator=True)
            elif not cfg.enabled:
                return "Learning is disabled in tako.toml. Inspection and rollback remain available."
            elif self.paused:
                return "Learning is paused by safe mode or shutdown. Inspection and rollback remain available."
            elif action == "review" and len(parts) == 1:
                return self.schedule_review(manual=True)
            elif action == "evaluate" and len(parts) == 2:
                self.store.show(parts[1])
                return self._queue(lambda: self._evaluate(parts[1]), name="evaluation")
            elif action == "feedback" and len(parts) >= 3 and parts[2] in {"success", "failure"}:
                result = self.store.feedback(parts[1], parts[2], note=parts[3] if len(parts) == 4 else "", operator=True)
                self.schedule_review()
            elif action == "promote" and len(parts) == 2:
                result = self.store.promote(parts[1], model=self._model(), operator=True)
            else:
                return f"Usage: {LEARN_USAGE}"
            return json.dumps(result, indent=2, ensure_ascii=False)
        except LearningError as exc:
            return str(exc)
        except Exception as exc:
            self._record_error(exc)
            return "Learning operation failed; use `learn status` for diagnostics."


_SERVICES: dict[tuple[str, str], LearningService] = {}


def learning_service(workspace_root: Path, state_dir: Path, runtime=None) -> LearningService:
    """Share one background worker/budget between terminal and XMTP chat."""
    key = (str(Path(workspace_root).resolve()), str(Path(state_dir).resolve()))
    service = _SERVICES.get(key)
    if service is None:
        service = LearningService(workspace_root, state_dir, runtime)
        _SERVICES[key] = service
    elif runtime is not None:
        service.runtime = runtime
    return service
