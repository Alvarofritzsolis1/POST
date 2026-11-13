"""The API container is the single source of the displayed release and revision."""
VERSION = "20.2.3-rc1"
try:
    from .build_revision import SOURCE_COMMIT
except ImportError:  # Local development has no container build revision.
    SOURCE_COMMIT = "unbuilt"
