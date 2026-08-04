from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required
from models import Device, Platform, Rom
import migration

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def index():
    devices_count = Device.query.count()
    platforms_count = Platform.query.count()
    roms_count = Rom.query.count()
    
    from routes.saves import get_saves_for_platform
    platforms = Platform.query.all()
    saves_count = sum(len(get_saves_for_platform(p)) for p in platforms)

    return render_template('main/dashboard.html', 
                           devices_count=devices_count, 
                           platforms_count=platforms_count, 
                           roms_count=roms_count,
                           saves_count=saves_count)

@main_bp.route('/migration', methods=['GET', 'POST'])
def trigger_migration():
    """
    Endpoint to trigger database migrations.
    Protected by checking the MIGRATION_SECRET_KEY config variable.
    Can be accessed via:
      - GET /migration?key=secret
      - POST /migration with X-Migration-Key header
    """
    expected_key = current_app.config.get('MIGRATION_SECRET_KEY', 'dev_migration_key')
    provided_key = request.headers.get('X-Migration-Key') or request.args.get('key')
    
    if not provided_key or provided_key != expected_key:
        return jsonify({
            "status": "failed",
            "applied_migrations": [],
            "message": "Unauthorized: Invalid or missing migration secret key."
        }), 401

    result = migration.run_migrations()
    status_code = 200 if result.get("status") == "success" else 500
    return jsonify(result), status_code
