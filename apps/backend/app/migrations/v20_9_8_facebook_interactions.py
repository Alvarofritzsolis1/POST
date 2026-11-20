"""Campos aditivos para moderación y seguimiento de comentarios Facebook."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20.9.8_facebook_interactions"

def upgrade(connection):
    table = "facebook_post_comments"
    columns = {item["name"] for item in inspect(connection).get_columns(table)}
    for name, definition in (
        ("author_picture_url", "VARCHAR(1000) NOT NULL DEFAULT ''"),
        ("classification", "VARCHAR(24) NOT NULL DEFAULT 'ambiguous'"),
        ("classification_source", "VARCHAR(16) NOT NULL DEFAULT 'rules'"),
        ("classification_score", "INTEGER NOT NULL DEFAULT 0"),
        ("review_state", "VARCHAR(20) NOT NULL DEFAULT 'new'"),
        ("review_by", "VARCHAR(36) NOT NULL DEFAULT ''"),
        ("reviewed_at", "TIMESTAMP WITH TIME ZONE"),
        ("is_deleted", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("user_likes", "BOOLEAN"),
        ("reply_count", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in columns:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
