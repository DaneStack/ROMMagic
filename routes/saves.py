import os
import io
import shutil
import zipfile
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory, jsonify, send_file
from flask_login import login_required
from models import Platform, Device
from extensions import db

saves_bp = Blueprint('saves', __name__)

def format_datetime(ts):
    """Formats a UNIX timestamp into a string matching configured TIMEZONE."""
    tz_name = current_app.config.get('TIMEZONE', 'Europe/Budapest')
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')

def make_safe_save_path(filename):
    """
    Sanitizes file/relative path to prevent path traversal while preserving
    valid subfolder structure (e.g., ULUS10563/PARAM.SFO -> ULUS10563/PARAM.SFO).
    """
    if not filename:
        return ""
    filename = filename.replace('\\', '/')
    parts = [p for p in filename.split('/') if p and p != '.']
    safe_parts = []
    for p in parts:
        if p == '..':
            continue
        cleaned = re.sub(r'[\\/*?:"<>|]', '', p).strip('. ')
        if cleaned:
            safe_parts.append(cleaned)
    return os.path.join(*safe_parts) if safe_parts else ""

def format_size(size_bytes):
    """Formats file size into human-readable string."""
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(units) - 1:
        size_bytes /= 1024.0
        i += 1
    return f"{size_bytes:.2f} {units[i]}"

def get_platform_saves_dir(platform):
    """Returns the absolute path to the saves directory for a platform."""
    folder_name = platform.get_folder_name
    saves_dir = os.path.join(current_app.config['ROM_UPLOAD_PATH'], folder_name, 'saves')
    os.makedirs(saves_dir, exist_ok=True)
    return saves_dir

def get_saves_for_platform(platform):
    """Scans and returns all native save files and save folders for a given platform."""
    saves_dir = get_platform_saves_dir(platform)
    saves = []
    if not os.path.exists(saves_dir):
        return saves

    try:
        for entry in os.scandir(saves_dir):
            if entry.is_file():
                stat = entry.stat()
                filename = entry.name
                ext = os.path.splitext(filename)[1].lstrip('.').lower() or 'save'
                saves.append({
                    'filename': filename,
                    'is_directory': False,
                    'file_count': 1,
                    'size': stat.st_size,
                    'size_human': format_size(stat.st_size),
                    'modified_at': format_datetime(stat.st_mtime),
                    'extension': ext,
                    'platform_id': platform.id,
                    'platform_name': platform.name,
                    'device_name': platform.device.name if platform.device else ''
                })
            elif entry.is_dir():
                folder_size = 0
                file_count = 0
                latest_mtime = entry.stat().st_mtime
                for root, dirs, files in os.walk(entry.path):
                    for f in files:
                        file_path = os.path.join(root, f)
                        try:
                            st = os.stat(file_path)
                            folder_size += st.st_size
                            file_count += 1
                            if st.st_mtime > latest_mtime:
                                latest_mtime = st.st_mtime
                        except OSError:
                            pass
                saves.append({
                    'filename': entry.name,
                    'is_directory': True,
                    'file_count': file_count,
                    'size': folder_size,
                    'size_human': format_size(folder_size),
                    'modified_at': format_datetime(latest_mtime),
                    'extension': 'folder',
                    'platform_id': platform.id,
                    'platform_name': platform.name,
                    'device_name': platform.device.name if platform.device else ''
                })

    except OSError as e:
        current_app.logger.error(f"Error scanning saves directory for platform {platform.name}: {e}")

    saves.sort(key=lambda s: s['filename'].lower())
    return saves

@saves_bp.route('/')
@login_required
def index():
    devices = Device.query.all()
    platforms = Platform.query.all()

    device_id = request.args.get('device_id', type=int)
    platform_id = request.args.get('platform_id', type=int)

    filtered_platforms = platforms
    if device_id:
        filtered_platforms = [p for p in filtered_platforms if p.device_id == device_id]
    if platform_id:
        filtered_platforms = [p for p in filtered_platforms if p.id == platform_id]

    saves_by_platform = []
    total_saves_count = 0

    for platform in filtered_platforms:
        saves = get_saves_for_platform(platform)
        total_saves_count += len(saves)
        saves_by_platform.append({
            'platform': platform,
            'saves': saves
        })

    return render_template(
        'saves/index.html',
        devices=devices,
        platforms=platforms,
        saves_by_platform=saves_by_platform,
        total_saves_count=total_saves_count,
        selected_device_id=device_id,
        selected_platform_id=platform_id
    )

@saves_bp.route('/upload', methods=['POST'])
@login_required
def upload():
    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json
    platform_id = request.form.get('platform_id', type=int)
    if not platform_id:
        msg = 'Platform is required for uploading saves.'
        if is_xhr:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('saves.index'))

    platform = db.session.get(Platform, platform_id)
    if not platform:
        msg = 'Selected platform was not found.'
        if is_xhr:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('saves.index'))

    # Collect files from all input names ('save_files', 'save_folder_files', 'files')
    files = request.files.getlist('save_files')
    folder_files = request.files.getlist('save_folder_files')
    generic_files = request.files.getlist('files')

    all_files = []
    if files and any(f.filename != '' for f in files):
        all_files.extend(files)
    if folder_files and any(f.filename != '' for f in folder_files):
        all_files.extend(folder_files)
    if generic_files and any(f.filename != '' for f in generic_files):
        all_files.extend(generic_files)

    if not all_files:
        msg = 'No save files or save folders selected for upload.'
        if is_xhr:
            return jsonify({'success': False, 'message': msg}), 400
        flash(msg, 'error')
        return redirect(url_for('saves.index', platform_id=platform.id))

    saves_dir = get_platform_saves_dir(platform)
    saved_count = 0
    skipped_count = 0

    for file in all_files:
        if not file or not file.filename:
            continue
        rel_path = make_safe_save_path(file.filename)
        if not rel_path:
            skipped_count += 1
            continue

        file_path = os.path.join(saves_dir, rel_path)
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            file.save(file_path)
            saved_count += 1
        except Exception as e:
            current_app.logger.error(f"Error saving save file {file.filename}: {e}")
            skipped_count += 1

    if saved_count > 0:
        msg = f'Successfully uploaded {saved_count} save file(s)/item(s) for {platform.name}.'
        if is_xhr:
            return jsonify({'success': True, 'message': msg, 'redirect_url': url_for('saves.index', platform_id=platform.id)})
        flash(msg, 'success')
    else:
        msg = 'Failed to upload save files.'
        if is_xhr:
            return jsonify({'success': False, 'message': msg}), 500
        flash(msg, 'error')

    return redirect(url_for('saves.index', platform_id=platform.id))

@saves_bp.route('/download/<int:platform_id>/<path:filename>')
@login_required
def download(platform_id, filename):
    platform = db.session.get(Platform, platform_id)
    if not platform:
        flash('Platform not found.', 'error')
        return redirect(url_for('saves.index'))

    saves_dir = get_platform_saves_dir(platform)
    file_path = os.path.join(saves_dir, filename)

    if not os.path.exists(file_path):
        flash('Save item not found on disk.', 'error')
        return redirect(url_for('saves.index', platform_id=platform.id))

    if os.path.isdir(file_path):
        # Package directory as zip
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(file_path):
                for f in files:
                    fp = os.path.join(root, f)
                    arcname = os.path.relpath(fp, saves_dir)
                    zf.write(fp, arcname=arcname)
        memory_file.seek(0)
        zip_name = f"{os.path.basename(filename)}.zip"
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_name
        )
    else:
        return send_from_directory(saves_dir, filename, as_attachment=True)

@saves_bp.route('/delete/<int:platform_id>/<path:filename>', methods=['POST'])
@login_required
def delete(platform_id, filename):
    platform = db.session.get(Platform, platform_id)
    if not platform:
        flash('Platform not found.', 'error')
        return redirect(url_for('saves.index'))

    saves_dir = get_platform_saves_dir(platform)
    file_path = os.path.join(saves_dir, filename)

    if os.path.exists(file_path):
        try:
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)
            flash(f'Save item "{filename}" deleted successfully.', 'success')
        except OSError as e:
            flash(f'Error deleting save item: {e}', 'error')
    else:
        flash('Save item not found.', 'error')

    return redirect(url_for('saves.index', platform_id=platform.id))

@saves_bp.route('/download_all/<int:platform_id>')
@login_required
def download_all(platform_id):
    platform = db.session.get(Platform, platform_id)
    if not platform:
        flash('Platform not found.', 'error')
        return redirect(url_for('saves.index'))

    saves = get_saves_for_platform(platform)
    if not saves:
        flash('No save files found for this platform.', 'info')
        return redirect(url_for('saves.index', platform_id=platform.id))

    saves_dir = get_platform_saves_dir(platform)
    memory_file = io.BytesIO()

    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(saves_dir):
            for f in files:
                file_path = os.path.join(root, f)
                arcname = os.path.relpath(file_path, saves_dir)
                zf.write(file_path, arcname=arcname)

    memory_file.seek(0)
    zip_name = f"{platform.get_folder_name}_saves.zip"

    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_name
    )

@saves_bp.route('/batch_delete', methods=['POST'])
@login_required
def batch_delete():
    items = request.form.getlist('save_items')
    if not items:
        flash('No save items selected for deletion.', 'error')
        return redirect(url_for('saves.index'))

    deleted_count = 0
    for item in items:
        if ':' not in item:
            continue
        platform_id_str, filename = item.split(':', 1)
        try:
            platform_id = int(platform_id_str)
            platform = db.session.get(Platform, platform_id)
            if platform:
                saves_dir = get_platform_saves_dir(platform)
                file_path = os.path.join(saves_dir, filename)
                if os.path.exists(file_path):
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)
                    deleted_count += 1
        except Exception as e:
            current_app.logger.error(f"Error deleting save item {item}: {e}")

    flash(f'Successfully deleted {deleted_count} save item(s).', 'success')
    return redirect(url_for('saves.index'))

@saves_bp.route('/batch_download', methods=['POST'])
@login_required
def batch_download():
    items = request.form.getlist('save_items')
    if not items:
        flash('No save items selected for download.', 'error')
        return redirect(url_for('saves.index'))

    memory_file = io.BytesIO()
    added_count = 0

    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if ':' not in item:
                continue
            platform_id_str, filename = item.split(':', 1)
            try:
                platform_id = int(platform_id_str)
                platform = db.session.get(Platform, platform_id)
                if platform:
                    saves_dir = get_platform_saves_dir(platform)
                    file_path = os.path.join(saves_dir, filename)
                    if os.path.exists(file_path):
                        prefix = platform.get_folder_name
                        if os.path.isdir(file_path):
                            for root, dirs, files in os.walk(file_path):
                                for f in files:
                                    fp = os.path.join(root, f)
                                    rel = os.path.relpath(fp, saves_dir)
                                    zf.write(fp, arcname=f"{prefix}/{rel}")
                                    added_count += 1
                        else:
                            zf.write(file_path, arcname=f"{prefix}/{filename}")
                            added_count += 1
            except Exception as e:
                current_app.logger.error(f"Error packing save item {item}: {e}")

    if added_count == 0:
        flash('Selected save items could not be found on disk.', 'error')
        return redirect(url_for('saves.index'))

    memory_file.seek(0)
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name='selected_game_saves.zip'
    )

@saves_bp.route('/api/<int:platform_id>')
@saves_bp.route('/api/list/<int:platform_id>')
@login_required
def api_list(platform_id):
    platform = db.session.get(Platform, platform_id)
    if not platform:
        return jsonify({'error': 'Platform not found'}), 404

    saves = get_saves_for_platform(platform)
    for s in saves:
        s['download_url'] = url_for('saves.download', platform_id=platform.id, filename=s['filename'], _external=True)

    return jsonify({
        'platform_id': platform.id,
        'platform_name': platform.name,
        'folder_name': platform.get_folder_name,
        'saves_count': len(saves),
        'saves': saves
    })
