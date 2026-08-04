from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_file, jsonify, after_this_request
import os
import io
import zipfile
import threading
from werkzeug.utils import secure_filename
from flask_login import login_required
from models import Platform, Device, Task
from models.platform import PREDEFINED_PLATFORMS
from extensions import db
from utils.cache import invalidate_platform_cache

platforms_bp = Blueprint('platforms', __name__)

@platforms_bp.route('/')
@login_required
def index():
    platforms = Platform.query.all()
    # Determine which predefined platforms have not been added yet
    used_names = {p.name for p in platforms}
    available_platforms = [name for name in PREDEFINED_PLATFORMS if name not in used_names]
    return render_template('platforms/index.html', platforms=platforms, available_platforms=available_platforms)

@platforms_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    devices = Device.query.all()
    # Find which predefined platforms haven't been added yet
    used_names = {p.name for p in Platform.query.all()}
    available_platforms = [name for name in PREDEFINED_PLATFORMS if name not in used_names]

    if not available_platforms:
        flash('All predefined platforms have already been added.', 'info')
        return redirect(url_for('platforms.index'))

    if request.method == 'POST':
        name = request.form.get('name')
        device_id = request.form.get('device_id')
        allowed_extensions_raw = request.form.get('allowed_extensions', '')
        
        # Validate: name must be one of the predefined platforms
        if name not in PREDEFINED_PLATFORMS:
            flash('Please select a valid predefined platform.', 'error')
            return render_template('platforms/form.html', title="Add Platform", platform=None,
                                   devices=devices, available_platforms=available_platforms,
                                   predefined_extensions=PREDEFINED_PLATFORMS)

        # Validate: platform must not already exist
        if name in used_names:
            flash(f'Platform "{name}" has already been added.', 'error')
            return render_template('platforms/form.html', title="Add Platform", platform=None,
                                   devices=devices, available_platforms=available_platforms,
                                   predefined_extensions=PREDEFINED_PLATFORMS)

        # Normalize allowed extensions list
        ext_list = []
        for ext in allowed_extensions_raw.split(','):
            cleaned = ext.strip().lower()
            if cleaned.startswith('.'):
                cleaned = cleaned[1:]
            if cleaned:
                ext_list.append(cleaned)
        allowed_extensions = ', '.join(ext_list) if ext_list else None
        
        scraper = request.form.get('scraper', 'thegamesdb')
        if scraper not in ['thegamesdb', 'screenscraper']:
            scraper = 'thegamesdb'
            
        if not name or not device_id:
            flash('Platform and Device are required.', 'error')
        else:
            folder_name_val = request.form.get('folder_name', '').strip()
            platform = Platform(
                name=name, device_id=device_id, allowed_extensions=allowed_extensions,
                folder_name=folder_name_val if folder_name_val else None,
                scraper=scraper
            )
            db.session.add(platform)
            db.session.commit()
            
            # Create folder for platform
            platform_dir = platform.get_folder_name
            upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
            os.makedirs(upload_path, exist_ok=True)
            
            flash('Platform added successfully.', 'success')
            return redirect(url_for('platforms.index'))
            
    return render_template('platforms/form.html', title="Add Platform", platform=None,
                           devices=devices, available_platforms=available_platforms,
                           predefined_extensions=PREDEFINED_PLATFORMS)

@platforms_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    platform = db.session.get(Platform, id)
    if not platform:
        flash('Platform not found.', 'error')
        return redirect(url_for('platforms.index'))
        
    devices = Device.query.all()
    if request.method == 'POST':
        device_id = request.form.get('device_id')
        allowed_extensions_raw = request.form.get('allowed_extensions', '')
        
        # Normalize allowed extensions list
        ext_list = []
        for ext in allowed_extensions_raw.split(','):
            cleaned = ext.strip().lower()
            if cleaned.startswith('.'):
                cleaned = cleaned[1:]
            if cleaned:
                ext_list.append(cleaned)
        allowed_extensions = ', '.join(ext_list) if ext_list else None
        
        scraper = request.form.get('scraper', 'thegamesdb')
        if scraper not in ['thegamesdb', 'screenscraper']:
            scraper = 'thegamesdb'

        if not device_id:
            flash('Device is required.', 'error')
        else:
            old_folder = platform.get_folder_name
            
            platform.device_id = device_id
            platform.allowed_extensions = allowed_extensions
            platform.scraper = scraper
            
            folder_name_val = request.form.get('folder_name', '').strip()
            platform.folder_name = folder_name_val if folder_name_val else None
            
            db.session.commit()
            
            new_folder = platform.get_folder_name
            
            if old_folder != new_folder:
                invalidate_platform_cache(current_app._get_current_object(), old_folder)
                old_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], old_folder)
                new_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], new_folder)
                if os.path.exists(old_path):
                    try:
                        os.rename(old_path, new_path)
                    except OSError as e:
                        flash(f'Failed to rename directory: {e}', 'error')
                else:
                    os.makedirs(new_path, exist_ok=True)
            else:
                # Ensure directory exists
                platform_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], new_folder)
                os.makedirs(platform_path, exist_ok=True)
                
            flash('Platform updated successfully.', 'success')
            return redirect(url_for('platforms.index'))
            
    return render_template('platforms/form.html', title="Edit Platform", platform=platform,
                           devices=devices, available_platforms=[], predefined_extensions=PREDEFINED_PLATFORMS)

@platforms_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    platform = db.session.get(Platform, id)
    if platform:
        platform_dir = platform.get_folder_name
        platform_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
        db.session.delete(platform)
        db.session.commit()
        try:
            if os.path.exists(platform_path):
                import shutil
                shutil.rmtree(platform_path)
        except Exception as e:
            current_app.logger.error(f'Error deleting platform folder {platform_path}: {e}')
        flash('Platform deleted successfully.', 'success')
    else:
        flash('Platform not found.', 'error')
    return redirect(url_for('platforms.index'))

@platforms_bp.route('/download_metadata/<int:id>')
@platforms_bp.route('/api/<int:id>/download_metadata')
@login_required
def download_metadata(id):
    platform = db.session.get(Platform, id)
    if not platform:
        if request.path.startswith('/platforms/api/') or request.headers.get('Accept') == 'application/json':
            return jsonify({'error': 'Platform not found.'}), 404
        flash('Platform not found.', 'error')
        return redirect(url_for('platforms.index'))
        
    platform_dir = platform.get_folder_name
    platform_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
    
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Check for gamelist.xml
        gamelist_path = os.path.join(platform_path, 'gamelist.xml')
        if os.path.exists(gamelist_path):
            zf.write(gamelist_path, arcname='gamelist.xml')
            
        # Check for images directory
        images_path = os.path.join(platform_path, 'images')
        if os.path.exists(images_path) and os.path.isdir(images_path):
            for root, dirs, files in os.walk(images_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Create relative path inside zip
                    arcname = os.path.join('images', os.path.relpath(file_path, images_path))
                    zf.write(file_path, arcname=arcname)
                    
    memory_file.seek(0)
    
    # Check if empty zip
    with zipfile.ZipFile(memory_file, 'r') as check_zf:
        if not check_zf.namelist():
            if request.path.startswith('/platforms/api/') or request.headers.get('Accept') == 'application/json':
                return jsonify({'error': 'No metadata or images found for this platform.'}), 404
            flash('No metadata or images found for this platform.', 'info')
            return redirect(url_for('platforms.index'))
            
    memory_file.seek(0)
    
    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{platform_dir}_metadata.zip'
    )

def background_zip_task(app, task_id, platform_id):
    with app.app_context():
        task = db.session.get(Task, task_id)
        if not task:
            return
            
        try:
            platform = db.session.get(Platform, platform_id)
            roms = platform.roms.all()
            
            platform_dir = platform.get_folder_name
            platform_path = os.path.join(app.config['ROM_UPLOAD_PATH'], platform_dir)
            temp_dir = os.path.join(app.config['ROM_UPLOAD_PATH'], 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            
            temp_zip_filename = f'{platform_dir}_roms_{task_id}.zip'
            temp_zip_path = os.path.join(temp_dir, temp_zip_filename)
            cached_zip_filename = f'{platform_dir}_roms_cached.zip'
            cached_zip_path = os.path.join(temp_dir, cached_zip_filename)
            
            task.status = 'processing'
            db.session.commit()
            
            total_roms = len(roms)
            
            with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for i, rom in enumerate(roms):
                    file_path = os.path.join(platform_path, rom.filename)
                    if os.path.exists(file_path):
                        zf.write(file_path, arcname=rom.filename)
                    
                    # Update progress
                    task.progress = int(((i + 1) / total_roms) * 100)
                    db.session.commit()
            
            # Move to cache path
            if os.path.exists(cached_zip_path):
                try:
                    os.remove(cached_zip_path)
                except:
                    pass
            os.rename(temp_zip_path, cached_zip_path)
            
            task.status = 'completed'
            task.result_path = cached_zip_path
            db.session.commit()
            
        except Exception as e:
            task.status = 'error'
            task.error_message = str(e)
            db.session.commit()

@platforms_bp.route('/download_roms/<int:id>', methods=['POST'])
@login_required
def download_roms(id):
    platform = db.session.get(Platform, id)
    if not platform:
        return jsonify({'error': 'Platform not found.'}), 404
        
    roms = platform.roms.all()
    if not roms:
        return jsonify({'error': 'No ROMs found for this platform.'}), 404
        
    app = current_app._get_current_object()
    platform_dir = platform.get_folder_name
    cached_zip_path = os.path.join(app.config['ROM_UPLOAD_PATH'], 'temp', f'{platform_dir}_roms_cached.zip')
    
    if os.path.exists(cached_zip_path):
        task = Task(task_type='download_roms', status='completed', progress=100, result_path=cached_zip_path)
        db.session.add(task)
        db.session.commit()
        return jsonify({'task_id': task.id})
        
    task = Task(task_type='download_roms', status='pending', progress=0)
    db.session.add(task)
    db.session.commit()
    
    app = current_app._get_current_object()
    thread = threading.Thread(target=background_zip_task, args=(app, task.id, platform.id))
    thread.daemon = True
    thread.start()
    
    return jsonify({'task_id': task.id})

@platforms_bp.route('/download_roms_status/<int:task_id>')
@login_required
def download_roms_status(task_id):
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify({'error': 'Task not found.'}), 404
        
    return jsonify({
        'status': task.status,
        'progress': task.progress,
        'error_message': task.error_message
    })

@platforms_bp.route('/download_roms_file/<int:task_id>')
@login_required
def download_roms_file(task_id):
    task = db.session.get(Task, task_id)
    if not task or task.status != 'completed' or not task.result_path:
        flash('Download not ready or failed.', 'error')
        return redirect(url_for('platforms.index'))
        
    result_path = task.result_path
    
    @after_this_request
    def remove_task(response):
        try:
            db.session.delete(task)
            db.session.commit()
        except Exception as e:
            current_app.logger.error(f"Error removing task record {task_id}: {e}")
        return response
        
    return send_file(
        result_path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=os.path.basename(result_path).replace(f"_{task_id}", "")
    )

@platforms_bp.route('/clear_cache/<int:id>', methods=['POST'])
@login_required
def clear_cache(id):
    platform = db.session.get(Platform, id)
    if not platform:
        flash('Platform not found.', 'error')
        return redirect(url_for('platforms.index'))
        
    app = current_app._get_current_object()
    platform_dir = platform.get_folder_name
    invalidate_platform_cache(app, platform_dir)
    
    flash('Platform cache cleared successfully.', 'success')
    return redirect(url_for('platforms.index'))

@platforms_bp.route('/api/<int:id>/roms')
@platforms_bp.route('/<int:id>/roms')
@login_required
def api_roms(id):
    platform = db.session.get(Platform, id)
    if not platform:
        return jsonify({'error': 'Platform not found'}), 404
        
    platform_dir = platform.get_folder_name
    upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
    
    roms = platform.roms.all()
    res = []
    orphans = []
    
    for r in roms:
        file_path = os.path.join(upload_path, r.filename)
        file_exists = os.path.exists(file_path)
        file_size = os.path.getsize(file_path) if file_exists else 0
        
        if not file_exists or file_size == 0:
            orphans.append(r)
        else:
            res.append({
                'id': r.id,
                'filename': r.filename,
                'original_filename': r.original_filename,
                'platform_id': r.platform_id,
                'game_title': r.game_title,
                'cover_image_url': r.cover_image_url,
                'file_size': file_size
            })

    if orphans:
        from utils.es_xml import delete_rom_files
        for orphan in orphans:
            delete_rom_files(current_app._get_current_object(), orphan)
            db.session.delete(orphan)
        db.session.commit()

    return jsonify(res)

