"""Production signing — refuses default keys in production."""
from __future__ import annotations
import hashlib, hmac, os
from dataclasses import dataclass
from typing import Optional

class SigningError(Exception):
    pass

@dataclass
class KeyIdentity:
    key_id: str
    provenance: str
    environment: str
    rotation_policy: str

class ProductionSigner:
    DEV_DEFAULT_MARKER = "INSECURE_DEV_ONLY_DO_NOT_USE_IN_PRODUCTION"
    def __init__(self, secret=None, key_identity=None, production=False):
        self.production = production
        self.key_identity = key_identity
        if production:
            if secret is None:
                raise SigningError("Production mode requires externally supplied secret")
            if key_identity is None:
                raise SigningError("Production mode requires explicit key identity")
            if key_identity.environment != "production":
                raise SigningError(f"Key environment is {key_identity.environment!r}, expected production")
            if not key_identity.provenance:
                raise SigningError("Production key must have provenance")
            if not key_identity.rotation_policy:
                raise SigningError("Production key must declare rotation strategy")
            self._secret = secret
        else:
            if secret is None:
                self._secret = self.DEV_DEFAULT_MARKER.encode("utf-8")
                self.key_identity = KeyIdentity("dev-default", "hardcoded-dev-default", "development", "n/a-dev")
            else:
                self._secret = secret
                self.key_identity = key_identity or KeyIdentity("dev-supplied", "caller-supplied-dev", "development", "n/a-dev")
    def sign(self, message: bytes) -> str:
        if self.production and self._secret == self.DEV_DEFAULT_MARKER.encode("utf-8"):
            raise SigningError("Refusing to sign in production with development default key")
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()
    def verify(self, message: bytes, signature: str) -> bool:
        return hmac.compare_digest(self.sign(message), signature)
    @classmethod
    def from_env(cls, production=True):
        secret = os.environ.get("HORSEMEN_SIGNING_SECRET")
        if production and not secret:
            raise SigningError("HORSEMEN_SIGNING_SECRET not set")
        if production:
            return cls(secret=secret.encode("utf-8"),
                       key_identity=KeyIdentity(
                           os.environ.get("HORSEMEN_KEY_ID", "env-key"),
                           os.environ.get("HORSEMEN_KEY_PROVENANCE", "environment-variable"),
                           "production",
                           os.environ.get("HORSEMEN_KEY_ROTATION", "unspecified-must-set")),
                       production=True)
        return cls(production=False)
