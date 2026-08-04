import logging
from sqlalchemy import text

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rommagic.migration")

def table_exists(session, table_name):
    """
    Checks if a table exists in the database.
    """
    query = text("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
    """)
    try:
        result = session.execute(query, {"table_name": table_name}).scalar()
        return result > 0
    except Exception as e:
        logger.error(f"Error checking if table {table_name} exists: {e}")
        return False

def column_exists(session, table_name, column_name):
    """
    Checks if a column exists within a specific table in the database.
    """
    query = text("""
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND column_name = :column_name
    """)
    try:
        result = session.execute(query, {"table_name": table_name, "column_name": column_name}).scalar()
        return result > 0
    except Exception as e:
        logger.error(f"Error checking if column {column_name} exists in {table_name}: {e}")
        return False

def index_exists(session, table_name, index_name):
    """
    Checks if an index exists on a specific table in the database.
    """
    query = text("""
        SELECT COUNT(*)
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = :table_name
          AND index_name = :index_name
    """)
    try:
        result = session.execute(query, {"table_name": table_name, "index_name": index_name}).scalar()
        return result > 0
    except Exception as e:
        logger.error(f"Error checking if index {index_name} exists in {table_name}: {e}")
        return False

def ensure_schema_version_table(session):
    """
    Creates the schema_version table if it does not already exist.
    """
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    session.commit()

def get_current_version(session):
    """
    Retrieves the maximum schema version applied, defaulting to 0.
    """
    ensure_schema_version_table(session)
    result = session.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
    return result if result is not None else 0

# --- Migration Definitions ---

def migrate_v1(session):
    """
    Migration v1: Base schema verification.
    Verifies that the main models (users, devices, platforms, roms, tasks) exist.
    Runs db.create_all() as a fallback if any are missing.
    """
    logger.info("Running migration v1: Verifying base schema tables...")
    required_tables = ['users', 'devices', 'platforms', 'roms', 'tasks']
    missing_tables = [table for table in required_tables if not table_exists(session, table)]
    
    if missing_tables:
        logger.warning(f"Missing base tables: {missing_tables}. Triggering db.create_all() fallback.")
        from extensions import db
        db.create_all()
    else:
        logger.info("All base schema tables verified successfully.")

def migrate_v2(session):
    """
    Migration v2 (Example): Adds a safe description column to the 'devices' table.
    """
    logger.info("Running migration v2 (Example): Adding 'description' to 'devices' table...")
    if not column_exists(session, 'devices', 'description'):
        session.execute(text("ALTER TABLE devices ADD COLUMN description VARCHAR(256) NULL"))
        logger.info("Column 'description' successfully added to 'devices' table.")
    else:
        logger.info("Column 'description' already exists. Skipping ALTER.")

def migrate_v3(session):
    """
    Migration v3: Adds 'scraper' column to the 'platforms' table.
    Defaults to 'thegamesdb'.
    """
    logger.info("Running migration v3: Adding 'scraper' column to 'platforms' table...")
    if not column_exists(session, 'platforms', 'scraper'):
        session.execute(text("ALTER TABLE platforms ADD COLUMN scraper VARCHAR(64) NOT NULL DEFAULT 'thegamesdb'"))
        logger.info("Column 'scraper' successfully added to 'platforms' table.")
    else:
        logger.info("Column 'scraper' already exists. Skipping ALTER.")

def migrate_v4(session):
    """
    Migration v4: Adds 'original_filename' column to the 'roms' table.
    Defaults existing records to their current 'filename'.
    """
    logger.info("Running migration v4: Adding 'original_filename' column to 'roms' table...")
    if not column_exists(session, 'roms', 'original_filename'):
        session.execute(text("ALTER TABLE roms ADD COLUMN original_filename VARCHAR(256) NULL"))
        session.execute(text("UPDATE roms SET original_filename = filename WHERE original_filename IS NULL"))
        logger.info("Column 'original_filename' successfully added to 'roms' table.")
    else:
        logger.info("Column 'original_filename' already exists. Skipping ALTER.")

def migrate_v5(session):
    """
    Migration v5: Clean up invalid ROM records corresponding to metadata/system files (e.g., gamelist.xml, systeminfo.txt).
    """
    logger.info("Running migration v5: Deleting invalid gamelist.xml and system metadata records from 'roms' table...")
    session.execute(text("""
        DELETE FROM roms 
        WHERE LOWER(filename) = 'gamelist.xml'
           OR LOWER(filename) LIKE 'gamelist%.xml'
           OR LOWER(filename) LIKE 'gamelist%.txt'
           OR LOWER(filename) LIKE 'systeminfo%'
           OR LOWER(original_filename) = 'gamelist.xml'
           OR LOWER(original_filename) LIKE 'gamelist%.xml'
           OR LOWER(original_filename) LIKE 'gamelist%.txt'
           OR LOWER(original_filename) LIKE 'systeminfo%'
    """))
    logger.info("Invalid gamelist.xml and metadata ROM records cleaned up successfully.")

# --- Migration Registration ---
# Add new sequential migration functions to this dictionary to include them in the run.
MIGRATIONS = {
    1: migrate_v1,
    2: migrate_v2,
    3: migrate_v3,
    4: migrate_v4,
    5: migrate_v5,
}

def run_migrations():
    """
    Main entry point to execute all pending migrations sequentially.
    Must be called within an active Flask application context.
    
    Returns:
        dict: JSON-serializable status dictionary.
    """
    from extensions import db
    
    applied = []
    try:
        current_version = get_current_version(db.session)
        logger.info(f"Current schema version: v{current_version}")
        
        target_version = max(MIGRATIONS.keys()) if MIGRATIONS else 0
        if current_version >= target_version:
            logger.info("Database is already up to date.")
            return {
                "status": "success",
                "applied_migrations": [],
                "message": f"Database is up to date at version {current_version}"
            }
            
        for version in sorted(MIGRATIONS.keys()):
            if version > current_version:
                logger.info(f"Applying migration v{version}...")
                migration_func = MIGRATIONS[version]
                
                # Execute migration logic
                migration_func(db.session)
                
                # Update schema_version table
                db.session.execute(
                    text("INSERT INTO schema_version (version) VALUES (:version)"),
                    {"version": version}
                )
                db.session.commit()
                applied.append(f"v{version}")
                logger.info(f"Successfully applied migration v{version}.")
                
        return {
            "status": "success",
            "applied_migrations": applied,
            "message": f"Database successfully migrated to version {target_version}"
        }
    except Exception as e:
        db.session.rollback()
        logger.error(f"Migration execution failed: {e}")
        return {
            "status": "failed",
            "applied_migrations": applied,
            "message": str(e)
        }
