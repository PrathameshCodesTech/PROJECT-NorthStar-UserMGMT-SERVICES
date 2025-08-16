# tenant_management/validators.py
import re
from django.core.exceptions import ValidationError

RESERVED_TENANT_SLUGS = {
    "postgres", "template0", "template1", "admin", "default", "public",
    "master", "root", "system"
}

SLUG_REGEX = r'^[a-z0-9-]{3,50}$'

def validate_and_normalize_slug(raw_slug: str) -> str:
    if raw_slug is None:
        raise ValidationError("tenant_slug is required")
    slug = raw_slug.strip().lower()

    if "_" in slug or " " in slug:
        raise ValidationError("tenant_slug may not contain underscores or spaces (use hyphens)")

    if slug in RESERVED_TENANT_SLUGS:
        raise ValidationError(f'tenant_slug "{slug}" is reserved; choose another')

    if not re.fullmatch(SLUG_REGEX, slug):
        raise ValidationError(
            "tenant_slug must match ^[a-z0-9-]{3,50}$ (lowercase letters, numbers, hyphens)"
        )

    return slug
