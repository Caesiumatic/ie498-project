import json
import os
from pathlib import Path
import sqlite3
import time

from .memory import digest


def remaining_budget(balance):
    return float('inf') if balance['budget'] is None else balance['budget']-balance['spent']-balance['reserved']


def budget_label(balance):
    return '无上限（用户授权）' if balance['budget'] is None else f"${balance['budget']:.2f}"


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)


class BudgetStop(Exception):
    pass


class Store:
    def __init__(self, root, budget=15.0, readonly=False):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        if readonly:
            self.db=sqlite3.connect(f"file:{(self.root/'experiments.sqlite').resolve()}?mode=ro",uri=True)
            self.db.row_factory=sqlite3.Row
            return
        self.db = sqlite3.connect(self.root / "experiments.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(
          id TEXT PRIMARY KEY, config TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
          parent TEXT REFERENCES runs(id), checkpoint INTEGER NOT NULL DEFAULT 0,
          created REAL NOT NULL, commit_hash TEXT NOT NULL, prompt_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rounds(
          run_id TEXT REFERENCES runs(id), t INTEGER, payload TEXT NOT NULL,
          PRIMARY KEY(run_id,t));
        CREATE TABLE IF NOT EXISTS memory_entries(
          run_id TEXT REFERENCES runs(id), t INTEGER, agent INTEGER, text TEXT NOT NULL,
          call_id TEXT NOT NULL, PRIMARY KEY(run_id,t,agent));
        CREATE TABLE IF NOT EXISTS memory_views(
          run_id TEXT REFERENCES runs(id), t INTEGER, agent INTEGER, payload TEXT NOT NULL,
          PRIMARY KEY(run_id,t,agent));
        CREATE TABLE IF NOT EXISTS api_attempts(
          id TEXT PRIMARY KEY, call_id TEXT NOT NULL, attempt INTEGER NOT NULL,
          run_id TEXT REFERENCES runs(id), t INTEGER, agent INTEGER, purpose TEXT,
          status TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL,
          reserved REAL NOT NULL, cost REAL NOT NULL DEFAULT 0, usage TEXT, parsed TEXT,
          raw_path TEXT, raw_sha256 TEXT, error TEXT, created REAL NOT NULL,
          UNIQUE(call_id,attempt));
        CREATE UNIQUE INDEX IF NOT EXISTS one_accepted ON api_attempts(call_id) WHERE status='accepted';
        CREATE INDEX IF NOT EXISTS budget_totals ON api_attempts(status,cost,reserved);
        CREATE INDEX IF NOT EXISTS recent_call ON api_attempts(run_id,agent,purpose,status,t DESC);
        CREATE INDEX IF NOT EXISTS run_costs ON api_attempts(run_id,t,cost);
        CREATE TABLE IF NOT EXISTS interventions(
          run_id TEXT REFERENCES runs(id), t INTEGER, agent INTEGER, factor REAL,
          PRIMARY KEY(run_id,t,agent));
        CREATE TABLE IF NOT EXISTS execution_epochs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT REFERENCES runs(id),
          checkpoint INTEGER NOT NULL,commit_hash TEXT NOT NULL,prompt_hash TEXT NOT NULL,started REAL NOT NULL);
        ''')
        self.db.execute("INSERT OR IGNORE INTO settings VALUES('budget',?)", ('unlimited' if budget is None else str(budget),))
        self.db.commit()

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def config(self, run):
        return json.loads(self.rows("SELECT config FROM runs WHERE id=?", (run,))[0]["config"])

    def status(self, run, status, error=None):
        with self.db:
            self.db.execute("UPDATE runs SET status=?,error=? WHERE id=?", (status, error, run))

    def epoch(self,run,checkpoint,commit,prompts):
        with self.db:
            self.db.execute('INSERT INTO execution_epochs(run_id,checkpoint,commit_hash,prompt_hash,started) VALUES(?,?,?,?,?)',
                            (run,checkpoint,commit,prompts,time.time()))

    def spending(self):
        row = self.rows("SELECT COALESCE(SUM(cost),0) spent, COALESCE(SUM(CASE WHEN status='pending' THEN reserved ELSE 0 END),0) reserved FROM api_attempts")[0]
        value=self.rows("SELECT value FROM settings WHERE key='budget'")[0]["value"]
        row["budget"] = None if value=='unlimited' else float(value)
        return row

    def add_run(self, run, config, commit, prompts, parent=None, checkpoint=0):
        if not run or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run):
            raise ValueError("Run IDs must be path-safe")
        with self.db:
            self.db.execute("INSERT INTO runs VALUES(?,?,?,NULL,?,?,?,?,?)",
                            (run, json.dumps(config, sort_keys=True), "planned", parent, checkpoint, time.time(), commit, prompts))
            shock = config.get("shock")
            if shock:
                self.db.execute("INSERT INTO interventions VALUES(?,?,?,?)", (run, shock["t"], shock["agent"], shock["factor"]))

    def history(self, run):
        return [json.loads(r["payload"]) for r in self.rows("SELECT payload FROM rounds WHERE run_id=? ORDER BY t", (run,))]

    def archive(self, run, agent):
        return [r["text"] for r in self.rows("SELECT text FROM memory_entries WHERE run_id=? AND agent=? ORDER BY t", (run, agent))]

    def accepted(self, call_id, request_hash):
        rows = self.rows("SELECT * FROM api_attempts WHERE call_id=? AND status='accepted'", (call_id,))
        if not rows:
            return None
        row = rows[0]
        if row["request_hash"] != request_hash:
            raise ValueError("Frozen request changed on resume")
        path = self.root / row["raw_path"]
        if not path.exists() or digest(path.read_text()) != row["raw_sha256"]:
            raise ValueError("Raw response integrity check failed")
        return json.loads(row["parsed"])

    def reserve(self, row):
        with self.db:
            balance = self.spending()
            if row['reserved'] > remaining_budget(balance) + 1e-10:
                raise BudgetStop("Project spending plus in-flight reservations would exceed budget")
            self.db.execute("""INSERT INTO api_attempts(id,call_id,attempt,run_id,t,agent,purpose,status,
              request_hash,request_json,reserved,created) VALUES(?,?,?,?,?,?,?,'pending',?,?,?,?)""",
              tuple(row[k] for k in ["id","call_id","attempt","run_id","t","agent","purpose",
                                     "request_hash","request_json","reserved"]) + (time.time(),))

    def finish_attempt(self, attempt, status, cost, usage=None, parsed=None, raw_path=None, error=None):
        sha = digest((self.root / raw_path).read_text()) if raw_path else None
        with self.db:
            self.db.execute("""UPDATE api_attempts SET status=?,cost=?,usage=?,parsed=?,raw_path=?,raw_sha256=?,error=? WHERE id=?""",
                            (status, cost, json.dumps(usage or {}), json.dumps(parsed), raw_path, sha, error, attempt))

    def view(self, run, t, agent, payload):
        value = json.dumps(payload, sort_keys=True)
        old = self.rows("SELECT payload FROM memory_views WHERE run_id=? AND t=? AND agent=?", (run,t,agent))
        if old and old[0]["payload"] != value:
            raise ValueError("Memory view changed on resume")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO memory_views VALUES(?,?,?,?)", (run,t,agent,value))

    def commit_round(self, run, payload, actions, architecture):
        t = payload["t"]
        with self.db:
            self.db.execute("INSERT INTO rounds VALUES(?,?,?)", (run,t,json.dumps(payload)))
            if architecture == "bullet_memory":
                for agent, action in enumerate(actions):
                    self.db.execute("INSERT INTO memory_entries VALUES(?,?,?,?,?)",
                                    (run,t,agent,action["memory_bullet"],payload.get('action_call_ids',[f'{run}:{t}:0:seller',f'{run}:{t}:1:seller'])[agent]))

    def fork(self, parent, child, checkpoint, config, commit, prompts):
        source = self.rows("SELECT * FROM runs WHERE id=?", (parent,))[0]
        history = self.history(parent)
        if checkpoint < 1 or checkpoint > len(history) or config["T"] <= checkpoint:
            raise ValueError("Invalid checkpoint or child horizon")
        parent_config = json.loads(source["config"])
        for key in ("provider", "model", "architecture", "temperature", "reasoning_effort", "pricing_version"):
            if config[key] != parent_config[key]:
                raise ValueError(f"Fork must preserve {key}")
        if source["prompt_hash"] != prompts:
            raise ValueError("Cannot fork across prompt versions")
        self.add_run(child, config, commit, prompts, parent, checkpoint)
        with self.db:
            self.db.execute("INSERT INTO rounds SELECT ?,t,payload FROM rounds WHERE run_id=? AND t<=?", (child,parent,checkpoint))
            self.db.execute("INSERT INTO memory_entries SELECT ?,t,agent,text,call_id FROM memory_entries WHERE run_id=? AND t<=?", (child,parent,checkpoint))

    def close(self):
        self.db.close()
