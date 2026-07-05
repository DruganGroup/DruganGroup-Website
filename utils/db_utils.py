import traceback
from contextlib import contextmanager
from flask import flash, current_app
from db import get_db

@contextmanager
def db_transaction(flash_error=True, error_msg="Error: {e}", log_error=True):
    """
    A safe context manager for database transactions.
    
    Usage:
        with db_transaction() as cur:
            cur.execute("INSERT INTO ...")
            # No need to commit, it happens automatically.
    
    If an exception occurs inside the block:
        - The transaction is rolled back automatically.
        - The error is logged to the system logger (if log_error is True).
        - A flash message is shown to the user (if flash_error is True).
        - Execution CONTINUES safely after the block, preventing 500 crashes
          and allowing templates to re-render.
    """
    conn = get_db()
    if not conn:
        if flash_error:
            flash("System Error: Could not connect to the database.", "error")
        # Yield None so the inner block can handle it or fail fast
        yield None
        return

    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        if log_error:
            current_app.logger.error(f"Database Transaction Error: {e}\n{traceback.format_exc()}")
        if flash_error:
            # Format the error message with the exception string
            formatted_msg = error_msg.replace("{e}", str(e))
            flash(formatted_msg, "error")
        # We DO NOT re-raise the exception, allowing the route to fall through
        # and render the template gracefully.
