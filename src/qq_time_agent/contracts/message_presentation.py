"""Safe, deterministic formatting of untrusted message bodies."""


def escape_origin_markers(value: str) -> str:
    """Prevent untrusted content from impersonating a system source label."""
    return value.strip().replace("[", "\N{FULLWIDTH LEFT SQUARE BRACKET}").replace(
        "]", "\N{FULLWIDTH RIGHT SQUARE BRACKET}"
    )


def format_direct_reply(display_name: str, content: str) -> str:
    """Render a direct QQ reply with its trusted, configured display name."""
    name = display_name.strip()
    if not name:
        raise ValueError("QQ display name is required")
    return f"{name}\N{FULLWIDTH COLON}{escape_origin_markers(content)}"
