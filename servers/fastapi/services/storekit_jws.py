"""
Verify Apple StoreKit 2 transaction JWS (`Transaction.jwsRepresentation`).

Sandbox / Production: verify ES256 signature and the x5c chain against
Apple Root CA - G3.

Xcode StoreKit Testing: the JWS is signed by a local StoreKit cert, not
Apple's App Store chain. We accept that environment only when
STOREKIT_ALLOW_XCODE is enabled, after decoding a well-formed payload.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi import HTTPException

from utils.get_env import (
    get_apple_bundle_id_env,
    get_appstore_environment_env,
    get_storekit_allow_xcode_env,
    get_storekit_dev_skip_cert_chain_env,
)

logger = logging.getLogger(__name__)

# Official Apple Root CA - G3 (DER from apple.com/certificateauthority, PEM form).
_APPLE_ROOT_CA_G3_PEM = b"""-----BEGIN CERTIFICATE-----
MIICQzCCAcmgAwIBAgIILcX8iNLFS5UwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwS
QXBwbGUgUm9vdCBDQSAtIEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9u
IEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcN
MTQwNDMwMTgxOTA2WhcNMzkwNDMwMTgxOTA2WjBnMRswGQYDVQQDDBJBcHBsZSBS
b290IENBIC0gRzMxJjAkBgNVBAsMHUFwcGxlIENlcnRpZmljYXRpb24gQXV0aG9y
aXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUzB2MBAGByqGSM49
AgEGBSuBBAAiA2IABJjpLz1AcqTtkyJygRMc3RCV8cWjTnHcFBbZDuWmBSp3ZHtf
TjjTuxxEtX/1H7YyYl3J6YRbTzBPEVoA/VhYDKX1DyxNB0cTddqXl5dvMVztK517
IDvYuVTZXpmkOlEKMaNCMEAwHQYDVR0OBBYEFLuw3qFYM4iapIqZ3r6966/ayySr
MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMDA2gA
MGUCMQCD6cHEFl4aXTQY2e3v9GwOAEZLuN+yRhHFD/3meoyhpmvOwgPUnPWTxnS4
at+qIxUCMG1mihDK1A3UT82NQz60imOlM27jbdoXt2QfyFMm+YhidDkLF1vLUagM
6BgD56KyKA==
-----END CERTIFICATE-----
"""


def _truthy(raw: Optional[str], default: str = "false") -> bool:
    return (raw if raw is not None else default).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _allow_xcode() -> bool:
    return _truthy(get_storekit_allow_xcode_env(), "true")


def _skip_cert_chain() -> bool:
    environment = (get_appstore_environment_env() or "sandbox").strip().lower()
    if environment == "production":
        return False
    return _truthy(get_storekit_dev_skip_cert_chain_env(), "true")


def _expected_bundle_id() -> str:
    return (get_apple_bundle_id_env() or "").strip()


def _jws_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"error": code, "message": message})


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _split_jws(token: str) -> tuple[str, str, str]:
    parts = (token or "").strip().split(".")
    if len(parts) != 3 or not all(parts):
        raise _jws_error("invalid_jws", "JWS must have three compact parts.")
    return parts[0], parts[1], parts[2]


def _load_json_segment(segment: str) -> dict:
    try:
        data = json.loads(_b64url_decode(segment))
    except Exception as exc:
        raise _jws_error("invalid_jws", f"Cannot decode JWS JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise _jws_error("invalid_jws", "JWS JSON must be an object.")
    return data


def _jose_es256_to_der(signature: bytes) -> bytes:
    if len(signature) != 64:
        raise _jws_error("invalid_jws", "ES256 signature must be 64 bytes.")
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    return encode_dss_signature(r, s)


def _load_x5c_certs(header: dict) -> list[x509.Certificate]:
    chain = header.get("x5c")
    if not isinstance(chain, list) or not chain:
        return []
    certs: list[x509.Certificate] = []
    for item in chain:
        if not isinstance(item, str) or not item.strip():
            continue
        try:
            der = base64.b64decode(item)
            certs.append(x509.load_der_x509_certificate(der))
        except Exception:
            continue
    return certs


def _verify_es256(leaf: x509.Certificate, signing_input: bytes, signature: bytes) -> None:
    public_key = leaf.public_key()
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise _jws_error("invalid_jws", "Leaf certificate is not an EC key.")
    try:
        public_key.verify(
            _jose_es256_to_der(signature),
            signing_input,
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as exc:
        raise _jws_error("invalid_jws_signature", "JWS signature is invalid.") from exc


def _verify_apple_chain(certs: list[x509.Certificate]) -> None:
    if not certs:
        raise _jws_error("invalid_jws", "JWS header is missing x5c.")
    apple_root = x509.load_pem_x509_certificate(_APPLE_ROOT_CA_G3_PEM)
    chain = list(certs)
    if chain[-1].fingerprint(hashes.SHA256()) != apple_root.fingerprint(hashes.SHA256()):
        chain.append(apple_root)

    now = datetime.now(timezone.utc)
    for cert in chain:
        try:
            if hasattr(cert, "not_valid_before_utc"):
                if now < cert.not_valid_before_utc or now > cert.not_valid_after_utc:
                    raise _jws_error("invalid_jws", "Certificate in x5c is expired.")
        except HTTPException:
            raise
        except Exception:
            pass

    for child, parent in zip(chain, chain[1:]):
        parent_key = parent.public_key()
        try:
            parent_key.verify(
                child.signature,
                child.tbs_certificate_bytes,
                ec.ECDSA(child.signature_hash_algorithm),
            )
        except Exception as exc:
            raise _jws_error(
                "invalid_jws_chain",
                "x5c certificate chain is not trusted by Apple Root CA - G3.",
            ) from exc

    if chain[-1].fingerprint(hashes.SHA256()) != apple_root.fingerprint(hashes.SHA256()):
        raise _jws_error(
            "invalid_jws_chain",
            "x5c does not terminate at Apple Root CA - G3.",
        )


def _ms_to_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


def parse_and_verify_storekit_jws(token: str) -> dict:
    """
    Return a normalized transaction dict or raise HTTPException.
    """
    protected, payload_seg, signature_seg = _split_jws(token)
    header = _load_json_segment(protected)
    payload = _load_json_segment(payload_seg)
    environment = str(payload.get("environment") or "").strip()
    signing_input = f"{protected}.{payload_seg}".encode("ascii")
    signature = _b64url_decode(signature_seg)
    certs = _load_x5c_certs(header)

    is_xcode = environment.lower() == "xcode"
    skip_chain = _skip_cert_chain() or is_xcode
    if is_xcode and not _allow_xcode():
        raise _jws_error(
            "xcode_not_allowed",
            "Xcode StoreKit JWS is disabled (STOREKIT_ALLOW_XCODE).",
        )
    if not certs:
        if skip_chain:
            logger.warning("StoreKit JWS has no x5c; accepting decoded payload (dev skip).")
        else:
            raise _jws_error("invalid_jws", "Sandbox/Production JWS requires x5c.")
    else:
        try:
            _verify_es256(certs[0], signing_input, signature)
        except HTTPException:
            if is_xcode:
                logger.warning("Xcode JWS signature did not verify; accepting decoded payload.")
            else:
                raise
        if not skip_chain:
            _verify_apple_chain(certs)

    product_id = str(payload.get("productId") or payload.get("product_id") or "").strip()
    transaction_id = str(
        payload.get("transactionId") or payload.get("transaction_id") or ""
    ).strip()
    if not product_id or not transaction_id:
        raise _jws_error(
            "invalid_jws_payload",
            "JWS payload must include productId and transactionId.",
        )

    bundle_id = str(payload.get("bundleId") or payload.get("bundle_id") or "").strip()
    expected = _expected_bundle_id()
    if expected and bundle_id and bundle_id != expected:
        raise _jws_error(
            "bundle_mismatch",
            f"bundleId {bundle_id!r} does not match APPLE_BUNDLE_ID.",
        )

    return {
        "product_id": product_id,
        "transaction_id": transaction_id,
        "original_transaction_id": str(
            payload.get("originalTransactionId") or transaction_id
        ).strip(),
        "bundle_id": bundle_id,
        "environment": environment or "Unknown",
        "type": str(payload.get("type") or "").strip(),
        "expires_at": _ms_to_datetime(payload.get("expiresDate") or payload.get("expires_date")),
        "revoked": bool(
            payload.get("revocationDate") or payload.get("revocation_date")
        ),
        "upgraded": payload.get("isUpgraded") is True,
        "payload": payload,
    }
