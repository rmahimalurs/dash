"""1Password reads and writes for credentials the dashboard uses.

Covers the AD service-account password upsert, plus reading and replacing a
single field on a named item, which is how a provider-rotated credential is
kept in one place instead of copied into a secret that then has to be applied.

Finds an accessible Login item whose ``username`` field equals the account name
and updates its password; if none is found, creates a new Login item in the
DevOps vault (title "<account> (AD)"). Passwords are never logged.
"""
import asyncio
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)
_INTEGRATION = ("devops-dashboard", "1.0")


async def _authenticate():
    from onepassword.client import Client
    s = get_settings()
    if not s.OP_SERVICE_ACCOUNT_TOKEN:
        raise RuntimeError("OP_SERVICE_ACCOUNT_TOKEN is not configured")
    return await Client.authenticate(
        auth=s.OP_SERVICE_ACCOUNT_TOKEN,
        integration_name=_INTEGRATION[0],
        integration_version=_INTEGRATION[1],
    )


def _field(item, name: str):
    name = name.lower()
    for f in (item.fields or []):
        if (f.id or "").lower() == name or (f.title or "").lower() == name:
            return f
    return None


async def upsert_ad_password(account: str, new_password: str) -> dict:
    """Update (or create) the 1Password entry for an AD account.

    Returns {action: 'updated'|'created', title, vault}.
    """
    from onepassword import ItemCreateParams, ItemCategory, ItemField, ItemFieldType

    account = (account or "").strip()
    account_l = account.lower()
    client = await _authenticate()
    s = get_settings()

    vaults = await client.vaults.list()
    vault_title = {v.id: v.title for v in vaults}
    devops_vault_id = next((v.id for v in vaults if v.title == s.OP_VAULT), None)

    # Collect Login item ids across every accessible vault.
    candidates: list[tuple[str, str]] = []
    for v in vaults:
        for ov in await client.items.list(v.id):
            if getattr(ov, "category", None) == ItemCategory.LOGIN:
                candidates.append((v.id, ov.id))

    async def _get(vid, iid):
        try:
            return vid, await client.items.get(vid, iid)
        except Exception:
            return vid, None

    fetched = await asyncio.gather(*[_get(vid, iid) for vid, iid in candidates])

    # Match by username field.
    for vid, item in fetched:
        if item is None:
            continue
        uf = _field(item, "username")
        if uf and (uf.value or "").strip().lower() == account_l:
            pf = _field(item, "password")
            if pf is not None:
                pf.value = new_password
            else:
                item.fields = list(item.fields or []) + [
                    ItemField(id="password", title="password", field_type=ItemFieldType.CONCEALED, value=new_password)
                ]
            await client.items.put(item)
            logger.info("1Password: updated password for account %s (item '%s')", account, item.title)
            return {"action": "updated", "title": item.title, "vault": vault_title.get(vid, "")}

    # No match — create in the DevOps vault.
    if not devops_vault_id:
        raise RuntimeError(
            f"1Password vault '{s.OP_VAULT}' is not visible to the service account; cannot create the entry."
        )
    title = f"{account} (AD)"
    await client.items.create(
        ItemCreateParams(
            title=title,
            category=ItemCategory.LOGIN,
            vault_id=devops_vault_id,
            fields=[
                ItemField(id="username", title="username", field_type=ItemFieldType.TEXT, value=account),
                ItemField(id="password", title="password", field_type=ItemFieldType.CONCEALED, value=new_password),
            ],
        )
    )
    logger.info("1Password: created entry '%s' in vault %s for account %s", title, s.OP_VAULT, account)
    return {"action": "created", "title": title, "vault": s.OP_VAULT}

async def _find_item(client, vault_name: str, item_title: str):
    """An item by title in one named vault, or None."""
    vaults = await client.vaults.list()
    vault = next((v for v in vaults if v.title == vault_name), None)
    if vault is None:
        raise RuntimeError(
            f"1Password vault '{vault_name}' is not visible to the service account."
        )
    for overview in await client.items.list(vault.id):
        if (overview.title or "").strip() == item_title:
            return await client.items.get(vault.id, overview.id)
    return None


async def read_field(vault_name: str, item_title: str, field_name: str) -> str:
    """One field's value out of a 1Password item.

    Reading the credential at the moment it is used means there is no second
    copy to keep in step: the vault is the only place it lives.
    """
    client = await _authenticate()
    item = await _find_item(client, vault_name, item_title)
    if item is None:
        raise RuntimeError(
            f"1Password item '{item_title}' was not found in vault '{vault_name}'."
        )
    field = _field(item, field_name)
    if field is None or not field.value:
        raise RuntimeError(
            f"1Password item '{item_title}' has no '{field_name}' value."
        )
    return field.value


async def write_field(vault_name: str, item_title: str, field_name: str, value: str) -> dict:
    """Replace one field's value on an existing 1Password item.

    Never logs the value. Used where a credential is rotated by the provider and
    the vault copy would otherwise be stale the moment it is used.
    """
    client = await _authenticate()
    item = await _find_item(client, vault_name, item_title)
    if item is None:
        raise RuntimeError(
            f"1Password item '{item_title}' was not found in vault '{vault_name}'."
        )
    target = _field(item, field_name)
    if target is None:
        raise RuntimeError(
            f"1Password item '{item_title}' has no '{field_name}' field to replace."
        )
    target.value = value
    await client.items.put(item)
    logger.info("1Password: replaced '%s' on '%s' in vault %s",
                field_name, item_title, vault_name)
    return {"item": item_title, "vault": vault_name, "field": field_name, "updated": True}
