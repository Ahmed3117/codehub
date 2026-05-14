"""Local account management for per-user CodeHub data isolation."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from codehub.utils.constants import CONFIG_DIR


_ACCOUNTS_FILE = "accounts.json"
_ACTIVE_ACCOUNT_FILE = "active_account.json"
_ACCOUNTS_DIR = "accounts"
_PBKDF2_ITERATIONS = 260_000
_LEGACY_FILES = {
    "sessions.json",
    "groups.json",
    "settings.json",
    "modes.json",
    "general_notes.json",
    "session_history.json",
    "templates.json",
}


@dataclass
class Account:
    """A local CodeHub account."""

    id: str
    name: str
    password_hash: str
    password_salt: str
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    def to_dict(self) -> dict:
        return asdict(self)


class AccountManager:
    """Creates, verifies, updates, and deletes local accounts."""

    def __init__(self, root_dir: str = CONFIG_DIR):
        self.root_dir = root_dir
        self.accounts_dir = os.path.join(root_dir, _ACCOUNTS_DIR)
        self.accounts_file = os.path.join(root_dir, _ACCOUNTS_FILE)
        self.active_account_file = os.path.join(root_dir, _ACTIVE_ACCOUNT_FILE)
        os.makedirs(self.accounts_dir, exist_ok=True)

    def get_accounts(self) -> list[Account]:
        return sorted(self._load_accounts(), key=lambda account: account.name.lower())

    def get(self, account_id: str) -> Optional[Account]:
        for account in self._load_accounts():
            if account.id == account_id:
                return account
        return None

    def create_account(self, name: str, password: str) -> Account:
        name = self._validate_name(name)
        self._validate_password(password)

        accounts = self._load_accounts()
        if any(account.name.lower() == name.lower() for account in accounts):
            raise ValueError("An account with this name already exists.")

        now = datetime.now().isoformat(timespec="seconds")
        salt, password_hash = self._hash_password(password)
        account = Account(
            id=self._make_account_id(name),
            name=name,
            password_hash=password_hash,
            password_salt=salt,
            created_at=now,
            updated_at=now,
        )
        accounts.append(account)
        os.makedirs(self.get_account_config_dir(account.id), exist_ok=True)
        self._save_accounts(accounts)
        self.set_last_active_account_id(account.id)
        return account

    def update_account(
        self,
        account_id: str,
        name: str | None = None,
        password: str | None = None,
    ) -> Account:
        accounts = self._load_accounts()
        account = self._find_or_raise(accounts, account_id)

        if name is not None:
            name = self._validate_name(name)
            if any(a.id != account_id and a.name.lower() == name.lower() for a in accounts):
                raise ValueError("An account with this name already exists.")
            account.name = name

        if password is not None:
            self._validate_password(password)
            salt, password_hash = self._hash_password(password)
            account.password_salt = salt
            account.password_hash = password_hash

        account.updated_at = datetime.now().isoformat(timespec="seconds")
        self._save_accounts(accounts)
        return account

    def delete_account(self, account_id: str, password: str) -> None:
        accounts = self._load_accounts()
        account = self._find_or_raise(accounts, account_id)
        if not self.verify_password(account_id, password):
            raise ValueError("Password is incorrect.")

        accounts = [a for a in accounts if a.id != account.id]
        self._save_accounts(accounts)
        account_dir = self.get_account_config_dir(account.id)
        if os.path.isdir(account_dir):
            shutil.rmtree(account_dir)

        if self.get_last_active_account_id() == account.id:
            self.set_last_active_account_id(accounts[0].id if accounts else None)

    def verify_password(self, account_id: str, password: str) -> bool:
        account = self.get(account_id)
        if account is None:
            return False
        salt = base64.b64decode(account.password_salt.encode("ascii"))
        expected = base64.b64decode(account.password_hash.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
        )
        return hmac.compare_digest(actual, expected)

    def get_account_config_dir(self, account_id: str) -> str:
        return os.path.join(self.accounts_dir, account_id)

    def get_last_active_account_id(self) -> Optional[str]:
        if not os.path.exists(self.active_account_file):
            return None
        try:
            with open(self.active_account_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            account_id = data.get("account_id")
            return account_id if isinstance(account_id, str) and account_id else None
        except (json.JSONDecodeError, IOError):
            return None

    def set_last_active_account_id(self, account_id: Optional[str]) -> None:
        os.makedirs(self.root_dir, exist_ok=True)
        with open(self.active_account_file, "w", encoding="utf-8") as f:
            json.dump({"account_id": account_id}, f, indent=2)

    def has_legacy_data(self) -> bool:
        return any(os.path.exists(os.path.join(self.root_dir, name)) for name in _LEGACY_FILES)

    def migrate_legacy_data(self, account_id: str) -> Optional[str]:
        """Copy old shared config files into an account and back them up."""
        legacy_files = [
            name for name in _LEGACY_FILES
            if os.path.isfile(os.path.join(self.root_dir, name))
        ]
        if not legacy_files:
            return None

        account_dir = self.get_account_config_dir(account_id)
        os.makedirs(account_dir, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(self.root_dir, f"legacy-backup-{stamp}")
        os.makedirs(backup_dir, exist_ok=True)

        for name in legacy_files:
            src = os.path.join(self.root_dir, name)
            dst = os.path.join(account_dir, name)
            backup = os.path.join(backup_dir, name)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            shutil.copy2(src, backup)

        return backup_dir

    def _load_accounts(self) -> list[Account]:
        if not os.path.exists(self.accounts_file):
            return []
        try:
            with open(self.accounts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return []
            return [Account.from_dict(item) for item in data if isinstance(item, dict)]
        except (json.JSONDecodeError, IOError, TypeError):
            return []

    def _save_accounts(self, accounts: list[Account]) -> None:
        os.makedirs(self.root_dir, exist_ok=True)
        data = [account.to_dict() for account in accounts]
        with open(self.accounts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _find_or_raise(self, accounts: list[Account], account_id: str) -> Account:
        for account in accounts:
            if account.id == account_id:
                return account
        raise ValueError("Account was not found.")

    @staticmethod
    def _validate_name(name: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValueError("Account name is required.")
        if len(name) > 40:
            raise ValueError("Account name must be 40 characters or less.")
        return name

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password:
            raise ValueError("Password is required.")
        if len(password) < 4:
            raise ValueError("Password must be at least 4 characters.")

    @staticmethod
    def _hash_password(password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
        )
        return (
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )

    @staticmethod
    def _make_account_id(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "account"
        return f"{slug[:24]}-{uuid.uuid4().hex[:6]}"
