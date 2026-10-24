"""A software passkey for tests: produces the exact JSON the browser's
``navigator.credentials.create`` / ``.get`` hand back (none attestation,
ES256), so registration and login run through the real verification path."""

from __future__ import annotations

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url


class SoftPasskey:
    def __init__(self, rp_id: str, origin: str) -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(32)
        self.sign_count = 0
        self.user_handle: bytes | None = None

    # -- registration -------------------------------------------------------

    def create(self, options: dict) -> dict:
        self.user_handle = base64url_to_bytes(options["user"]["id"])
        client_data = json.dumps({
            "type": "webauthn.create", "challenge": options["challenge"],
            "origin": self.origin, "crossOrigin": False,
        }).encode()
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([0x45])  # UP | UV | AT
            + struct.pack(">I", self.sign_count)
            + bytes(16) + struct.pack(">H", len(self.cred_id)) + self.cred_id + cose
        )
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": bytes_to_base64url(self.cred_id), "rawId": bytes_to_base64url(self.cred_id),
            "type": "public-key", "authenticatorAttachment": "platform", "clientExtensionResults": {},
            "response": {"clientDataJSON": bytes_to_base64url(client_data),
                         "attestationObject": bytes_to_base64url(att), "transports": ["internal"]},
        }

    # -- authentication -----------------------------------------------------

    def get(self, options: dict) -> dict:
        self.sign_count += 1
        client_data = json.dumps({
            "type": "webauthn.get", "challenge": options["challenge"],
            "origin": self.origin, "crossOrigin": False,
        }).encode()
        auth_data = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + struct.pack(">I", self.sign_count)
        sig = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": bytes_to_base64url(self.cred_id), "rawId": bytes_to_base64url(self.cred_id),
            "type": "public-key", "authenticatorAttachment": "platform", "clientExtensionResults": {},
            "response": {"clientDataJSON": bytes_to_base64url(client_data),
                         "authenticatorData": bytes_to_base64url(auth_data),
                         "signature": bytes_to_base64url(sig),
                         "userHandle": bytes_to_base64url(self.user_handle or b"")},
        }

    def public_pem(self) -> bytes:
        return self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
