
import os
import json
import sqlite3
import requests

from pathlib import Path
from datetime import datetime, timezone

import msal
import pandas as pd
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "tenant.db"

GRAPH_URL = "https://graph.microsoft.com/v1.0"

load_dotenv(BASE_DIR / ".env")

TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")


# ============================================================
# MAIN APPLICATION
# ============================================================

class TenantExplorer:

    def __init__(self):

        if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
            raise ValueError(
                "Missing TENANT_ID, CLIENT_ID or CLIENT_SECRET in .env"
            )

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        self.tenant_id = TENANT_ID
        self.db_path = DB_PATH
        self.token = None

        self._create_database()


    # ========================================================
    # DATABASE
    # ========================================================

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


    def _create_database(self):

        with self._connect() as conn:

            conn.executescript("""

                CREATE TABLE IF NOT EXISTS organizations (
                    tenant_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    verified_domains TEXT,
                    country TEXT,
                    created_at TEXT,
                    raw_json TEXT,
                    last_synced TEXT
                );

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    display_name TEXT,
                    user_principal_name TEXT,
                    mail TEXT,
                    job_title TEXT,
                    department TEXT,
                    account_enabled INTEGER,
                    user_type TEXT,
                    raw_json TEXT,
                    last_synced TEXT
                );

                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    display_name TEXT,
                    description TEXT,
                    mail TEXT,
                    mail_enabled INTEGER,
                    security_enabled INTEGER,
                    group_types TEXT,
                    raw_json TEXT,
                    last_synced TEXT
                );

                CREATE TABLE IF NOT EXISTS sync_metadata (
                    resource TEXT PRIMARY KEY,
                    last_synced TEXT,
                    record_count INTEGER
                );

            """)


    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat()


    # ========================================================
    # AUTHENTICATION
    # ========================================================

    def authenticate(self):

        app = msal.ConfidentialClientApplication(
            CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            client_credential=CLIENT_SECRET
        )

        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )

        if "access_token" not in result:
            raise RuntimeError(
                result.get("error_description", "Authentication failed")
            )

        self.token = result["access_token"]

        return True


    # ========================================================
    # GRAPH API
    # ========================================================

    def _request(self, url):

        if not self.token:
            self.authenticate()

        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json"
            },
            timeout=60
        )

        if response.status_code == 401:
            self.authenticate()

            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/json"
                },
                timeout=60
            )

        response.raise_for_status()

        return response.json()


    def _get_collection(self, endpoint):

        url = f"{GRAPH_URL}/{endpoint}"
        records = []

        while url:

            result = self._request(url)

            records.extend(result.get("value", []))

            url = result.get("@odata.nextLink")

        return records


    # ========================================================
    # DATA RETRIEVAL
    # ========================================================

    def _get_organization(self):

        result = self._get_collection(
            "organization?$select=id,displayName,"
            "verifiedDomains,country,createdDateTime"
        )

        if not result:
            raise RuntimeError("No organization information returned.")

        return result[0]


    def _get_users(self):

        return self._get_collection(
            "users?$select=id,displayName,userPrincipalName,"
            "mail,jobTitle,department,accountEnabled,userType"
        )


    def _get_groups(self):

        return self._get_collection(
            "groups?$select=id,displayName,description,mail,"
            "mailEnabled,securityEnabled,groupTypes"
        )


    # ========================================================
    # DATABASE SYNCHRONIZATION
    # ========================================================

    def _save_metadata(self, conn, resource, count):

        conn.execute("""
            INSERT INTO sync_metadata
                (resource, last_synced, record_count)
            VALUES (?, ?, ?)
            ON CONFLICT(resource) DO UPDATE SET
                last_synced=excluded.last_synced,
                record_count=excluded.record_count
        """, (resource, self._now(), count))


    def sync_organization(self, conn, org):

        conn.execute("""
            INSERT OR REPLACE INTO organizations
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.tenant_id,
            org.get("displayName"),
            json.dumps(org.get("verifiedDomains", [])),
            org.get("country"),
            org.get("createdDateTime"),
            json.dumps(org),
            self._now()
        ))

        self._save_metadata(conn, "organization", 1)


    def sync_users(self, conn, users):

        now = self._now()

        conn.execute("DELETE FROM users")

        conn.executemany("""
            INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                u["id"],
                u.get("displayName"),
                u.get("userPrincipalName"),
                u.get("mail"),
                u.get("jobTitle"),
                u.get("department"),
                int(u["accountEnabled"])
                    if u.get("accountEnabled") is not None else None,
                u.get("userType"),
                json.dumps(u),
                now
            )
            for u in users
        ])

        self._save_metadata(conn, "users", len(users))


    def sync_groups(self, conn, groups):

        now = self._now()

        conn.execute("DELETE FROM groups")

        conn.executemany("""
    		INSERT INTO groups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
		""", [
            (
                g["id"],
                g.get("displayName"),
                g.get("description"),
                g.get("mail"),
                int(g["mailEnabled"])
                    if g.get("mailEnabled") is not None else None,
                int(g["securityEnabled"])
                    if g.get("securityEnabled") is not None else None,
                json.dumps(g.get("groupTypes", [])),
                json.dumps(g),
                now
            )
            for g in groups
        ])

        self._save_metadata(conn, "groups", len(groups))


    def sync(self):

        print("Connecting to Microsoft Graph...")

        self.authenticate()

        print("Downloading organization...")
        org = self._get_organization()

        print("Downloading users...")
        users = self._get_users()

        print("Downloading groups...")
        groups = self._get_groups()

        # Only update the database after all downloads succeed.
        # The transaction prevents partial synchronization.

        with self._connect() as conn:

            self.sync_organization(conn, org)
            self.sync_users(conn, users)
            self.sync_groups(conn, groups)

        print("Synchronization completed!")

        return self.sync_status()


    # ========================================================
    # LOCAL DATABASE QUERIES
    # ========================================================

    def query(self, sql, params=()):

        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)


    def organization(self):

        return self.query("SELECT * FROM organizations")


    def users(self):

        return self.query("""
            SELECT id, display_name, user_principal_name,
                   mail, job_title, department,
                   account_enabled, user_type, last_synced
            FROM users
            ORDER BY display_name
        """)


    def groups(self):

        return self.query("""
            SELECT id, display_name, description, mail,
                   mail_enabled, security_enabled, last_synced
            FROM groups
            ORDER BY display_name
        """)


    def search_users(self, search_term):

        return self.query("""
            SELECT display_name, user_principal_name,
                   mail, department, job_title, account_enabled
            FROM users
            WHERE display_name LIKE ?
               OR user_principal_name LIKE ?
               OR mail LIKE ?
            ORDER BY display_name
        """, tuple([f"%{search_term}%"] * 3))


    def sync_status(self):

        return self.query("""
            SELECT resource, record_count, last_synced
            FROM sync_metadata
            ORDER BY resource
        """)


    def dashboard(self):

        with self._connect() as conn:

            users = conn.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]

            groups = conn.execute(
                "SELECT COUNT(*) FROM groups"
            ).fetchone()[0]

            enabled = conn.execute(
                "SELECT COUNT(*) FROM users WHERE account_enabled = 1"
            ).fetchone()[0]

            disabled = conn.execute(
                "SELECT COUNT(*) FROM users WHERE account_enabled = 0"
            ).fetchone()[0]

        return pd.DataFrame({
            "Metric": [
                "Total users",
                "Enabled users",
                "Disabled users",
                "Total groups"
            ],
            "Value": [
                users,
                enabled,
                disabled,
                groups
            ]
        })
