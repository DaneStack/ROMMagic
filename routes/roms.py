import os
import shutil
import threading
import zipfile
import tempfile
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_from_directory, jsonify, send_file, after_this_request
from flask_login import login_required
from werkzeug.utils import secure_filename
from models import Rom, Platform, Device
from extensions import db
from utils.scraper import scrape_game_metadata
from utils.cache import invalidate_platform_cache

def _has_scraper_credentials(app, platform):
    """
    Checks if credentials for the platform's selected scraper are configured.
    """
    provider = platform.scraper if platform and platform.scraper else 'thegamesdb'
    if provider == 'screenscraper':
        return bool(app.config.get('SCREENSCRAPER_DEV_ID') and app.config.get('SCREENSCRAPER_DEV_PASSWORD'))
    else:
        return bool(app.config.get('THEGAMESDB_API_KEY'))

def _get_scraper_config_and_metadata(app, platform, query_term, is_keyword=False):
    """
    Helper to resolve the scraper choice and credentials for a platform and run scraping.
    """
    provider = platform.scraper if platform and platform.scraper else 'thegamesdb'
    if provider == 'screenscraper':
        credentials = {
            'devid': app.config.get('SCREENSCRAPER_DEV_ID'),
            'devpassword': app.config.get('SCREENSCRAPER_DEV_PASSWORD'),
            'softname': app.config.get('SCREENSCRAPER_SOFTNAME', 'rommagic'),
            'ssid': app.config.get('SCREENSCRAPER_USER'),
            'sspassword': app.config.get('SCREENSCRAPER_PASSWORD')
        }
        return scrape_game_metadata(
            query_term, is_keyword=is_keyword,
            platform_name=platform.name if platform else None,
            provider='screenscraper', credentials=credentials
        )
    else:
        api_key = app.config.get('THEGAMESDB_API_KEY')
        if not api_key:
            return None
        return scrape_game_metadata(
            query_term, api_key=api_key, is_keyword=is_keyword,
            platform_name=platform.name if platform else None,
            provider='thegamesdb'
        )

roms_bp = Blueprint('roms', __name__)

def make_safe_filename(filename):
    """
    Sanitizes a filename to prevent path traversal and filesystem issues.
    Removes brackets, parentheses, and spaces to sanitize for launchers.
    """
    if not filename:
        return ""
    # Get only the basename of the file in case a path was sent
    filename = os.path.basename(filename)
    # Remove filesystem-unsafe characters and brackets/parentheses/commas/apostrophes: \ / : * ? " < > | ( ) [ ] , '
    import re
    cleaned = re.sub(r'[\\/*?:"<>|()\[\],]', '', filename)
    cleaned = cleaned.replace("'", "")
    # Convert spaces to underscores
    cleaned = cleaned.replace(' ', '_')
    # Strip leading/trailing dots and underscores
    cleaned = cleaned.strip('. _')
    return cleaned

def is_ignored_rom_file(filename):
    """
    Checks if a file is a metadata or system file (e.g. gamelist.xml, systeminfo.txt)
    that should not be treated or scanned as a ROM.
    """
    if not filename:
        return True
    name_lower = os.path.basename(filename).strip().lower()
    if name_lower == 'gamelist.xml' or (name_lower.startswith('gamelist') and (name_lower.endswith('.xml') or name_lower.endswith('.txt'))):
        return True
    if name_lower == 'systeminfo.txt' or (name_lower.startswith('systeminfo') and name_lower.endswith('.txt')):
        return True
    return False

def _apply_metadata(app, platform, rom, metadata):
    """Helper to apply scraped metadata dict to a Rom instance."""
    from utils.es_xml import download_and_convert_cover_image
    if not metadata:
        return
    if metadata.get("game_title"):
        rom.game_title = metadata["game_title"]
    if metadata.get("esrb_rating"):
        rom.esrb_rating = metadata["esrb_rating"]
    if metadata.get("genres"):
        rom.genres = metadata["genres"]
    if metadata.get("description"):
        rom.description = metadata["description"]
        
    if metadata.get("cover_image_url"):
        # Download and convert to PNG using exact ROM filename so Daijisho matches it
        local_rel = download_and_convert_cover_image(
            app, platform.get_folder_name, rom.filename, metadata["cover_image_url"]
        )
        if local_rel:
            rom.cover_image_url = f"/roms/media/{platform.id}/{local_rel.split('/')[-1]}"
        else:
            rom.cover_image_url = metadata["cover_image_url"]

def _background_scrape(app, scrape_tasks, platform_name):
    """Background task to scrape game metadata."""
    from utils.es_xml import generate_gamelist_xml
    from utils.cache import invalidate_platform_cache
    with app.app_context():
        platforms_to_update_ids = set()
        for rom_id, filename in scrape_tasks:
            try:
                rom = db.session.get(Rom, rom_id)
                if not rom:
                    continue
                query_term = rom.original_filename or rom.filename or filename
                metadata = _get_scraper_config_and_metadata(app, rom.platform, query_term)
                if metadata:
                    _apply_metadata(app, rom.platform, rom, metadata)
                    db.session.commit()
                    if rom.platform_id:
                        platforms_to_update_ids.add(rom.platform_id)
            except Exception as e:
                app.logger.error(f"Error scraping metadata in background for {filename}: {e}")
                
        for platform_id in platforms_to_update_ids:
            try:
                platform = db.session.get(Platform, platform_id)
                if platform:
                    generate_gamelist_xml(app, platform)
                    invalidate_platform_cache(app, platform.get_folder_name)
            except Exception as e:
                app.logger.error(f"Error generating gamelist for platform ID {platform_id}: {e}")

def _batch_rescrape_task(app, rom_ids):
    from utils.es_xml import generate_gamelist_xml
    from utils.cache import invalidate_platform_cache
    with app.app_context():
        platforms_to_update_ids = set()
        roms = Rom.query.filter(Rom.id.in_(rom_ids)).all()
        for rom in roms:
            try:
                if rom.platform_id:
                    platforms_to_update_ids.add(rom.platform_id)
                    
                if rom.search_keywords:
                    metadata = _get_scraper_config_and_metadata(app, rom.platform, rom.search_keywords, is_keyword=True)
                else:
                    metadata = _get_scraper_config_and_metadata(app, rom.platform, rom.original_filename or rom.filename)
                
                if metadata and metadata.get("game_title"):
                    _apply_metadata(app, rom.platform, rom, metadata)
                    db.session.commit()
            except Exception as e:
                app.logger.error(f"Error rescraping metadata in background for {rom.filename}: {e}")
                
        for platform_id in platforms_to_update_ids:
            try:
                platform = db.session.get(Platform, platform_id)
                if platform:
                    generate_gamelist_xml(app, platform)
                    invalidate_platform_cache(app, platform.get_folder_name)
            except Exception as e:
                app.logger.error(f"Error generating gamelist for platform ID {platform_id}: {e}")

@roms_bp.route('/')
@login_required
def index():
    # Purge any existing DB records that represent metadata/system files (e.g. gamelist.xml) or orphan records with missing platforms
    all_roms = Rom.query.all()
    invalid_rom_ids = [
        rom.id for rom in all_roms 
        if not rom.platform or is_ignored_rom_file(rom.filename) or is_ignored_rom_file(rom.original_filename)
    ]
    if invalid_rom_ids:
        Rom.query.filter(Rom.id.in_(invalid_rom_ids)).delete(synchronize_session=False)
        db.session.commit()
        roms = Rom.query.all()
    else:
        roms = all_roms
    platforms = Platform.query.all()
    devices = Device.query.all()
    return render_template('roms/index.html', roms=roms, platforms=platforms, devices=devices)

@roms_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    platforms = Platform.query.all()
    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.accept_mimetypes.accept_json
    
    if request.method == 'POST':
        if 'file' not in request.files:
            error_msg = 'No file part.'
            if is_xhr:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            error_msg = 'No selected file.'
            if is_xhr:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return redirect(request.url)
            
        platform_id = request.form.get('platform_id')
        if not platform_id:
            error_msg = 'Platform is required.'
            if is_xhr:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return redirect(request.url)
            
        platform = db.session.get(Platform, platform_id)
        if not platform:
            error_msg = 'Invalid platform.'
            if is_xhr:
                return jsonify({'success': False, 'message': error_msg}), 400
            flash(error_msg, 'error')
            return redirect(request.url)
            
        if file:
            filename = make_safe_filename(file.filename)
            if not filename or is_ignored_rom_file(file.filename) or is_ignored_rom_file(filename):
                error_msg = 'Metadata/system files (e.g. gamelist.xml) cannot be uploaded as ROMs.' if (is_ignored_rom_file(file.filename) or is_ignored_rom_file(filename)) else 'Invalid filename.'
                if is_xhr:
                    return jsonify({'success': False, 'message': error_msg}), 400
                flash(error_msg, 'error')
                return redirect(request.url)
                
            # Check file extension
            _, ext = os.path.splitext(filename)
            ext_cleaned = ext.strip('.').lower()
            if platform.allowed_extensions:
                allowed_list = [e.strip().lower() for e in platform.allowed_extensions.split(',') if e.strip()]
                if ext_cleaned not in allowed_list:
                    error_msg = f"File extension .{ext_cleaned} is not allowed for {platform.name}. Allowed: {platform.allowed_extensions}"
                    if is_xhr:
                        return jsonify({'success': False, 'message': error_msg}), 400
                    flash(error_msg, 'error')
                    return redirect(request.url)
            
            platform_dir = platform.get_folder_name
            upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
            os.makedirs(upload_path, exist_ok=True)
            
            # Auto-versioning if duplicates found
            base, extension = os.path.splitext(filename)
            counter = 1
            file_path = os.path.join(upload_path, filename)
            while os.path.exists(file_path) or Rom.query.filter_by(filename=filename, platform_id=platform.id).first() is not None:
                filename = f"{base}_{counter}{extension}"
                file_path = os.path.join(upload_path, filename)
                counter += 1
            
            file.save(file_path)
            
            # Save to db first so background task can find it
            rom = Rom(filename=filename, platform_id=platform.id)
            db.session.add(rom)
            db.session.commit()
            
            invalidate_platform_cache(current_app._get_current_object(), platform_dir)
            
            # Scrape metadata in background
            api_key = current_app.config.get('THEGAMESDB_API_KEY')
            if api_key:
                app = current_app._get_current_object()
                threading.Thread(
                    target=_background_scrape,
                    args=(app, [(rom.id, filename)], api_key, platform.name)
                ).start()
            
            flash('File successfully uploaded.', 'success')
            if is_xhr:
                return jsonify({'success': True, 'redirect_url': url_for('roms.index')})
            return redirect(url_for('roms.index'))
            
    return render_template('roms/form.html', title="Upload ROM", platforms=platforms)

@roms_bp.route('/upload_multiple', methods=['POST'])
@login_required
def upload_multiple():
    """Handle batch upload of multiple ROM files for a single platform."""
    platform_id = request.form.get('platform_id')
    if not platform_id:
        return jsonify({'success': False, 'message': 'Platform is required.'}), 400

    platform = db.session.get(Platform, platform_id)
    if not platform:
        return jsonify({'success': False, 'message': 'Invalid platform.'}), 400

    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'message': 'No files selected.'}), 400

    allowed_list = []
    if platform.allowed_extensions:
        allowed_list = [e.strip().lower() for e in platform.allowed_extensions.split(',') if e.strip()]

    platform_dir = platform.get_folder_name
    upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
    has_creds = _has_scraper_credentials(current_app, platform)

    uploaded = []
    skipped = []
    failed = []
    scrape_tasks = []

    for file in files:
        original_name = file.filename
        if not original_name or original_name == '':
            continue

        filename = make_safe_filename(original_name)
        if not filename or is_ignored_rom_file(original_name) or is_ignored_rom_file(filename):
            reason_msg = 'Metadata/system file (e.g. gamelist.xml).' if (is_ignored_rom_file(original_name) or is_ignored_rom_file(filename)) else 'Invalid filename.'
            skipped.append({'filename': original_name, 'reason': reason_msg})
            continue

        # Check file extension
        _, ext = os.path.splitext(filename)
        ext_cleaned = ext.strip('.').lower()
        if allowed_list and ext_cleaned not in allowed_list:
            skipped.append({
                'filename': original_name,
                'reason': f'.{ext_cleaned} not allowed. Allowed: {platform.allowed_extensions}'
            })
            continue

        try:
            # Auto-versioning if duplicates found
            base, extension = os.path.splitext(filename)
            counter = 1
            save_filename = filename
            file_path = os.path.join(upload_path, save_filename)
            while os.path.exists(file_path) or Rom.query.filter_by(filename=save_filename, platform_id=platform.id).first() is not None:
                save_filename = f"{base}_{counter}{extension}"
                file_path = os.path.join(upload_path, save_filename)
                counter += 1

            file.save(file_path)

            rom = Rom(filename=save_filename, platform_id=platform.id, original_filename=original_name)
            db.session.add(rom)
            db.session.flush() # Get ID without committing
            
            if has_creds:
                scrape_tasks.append((rom.id, save_filename))

            uploaded.append({'filename': original_name, 'saved_as': save_filename})
        except Exception as e:
            if 'file_path' in locals() and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            failed.append({'filename': original_name, 'reason': str(e)})

    if uploaded:
        db.session.commit()
        invalidate_platform_cache(current_app._get_current_object(), platform_dir)
        
        # Start background scraping
        if scrape_tasks:
            app = current_app._get_current_object()
            threading.Thread(
                target=_background_scrape,
                args=(app, scrape_tasks, platform.name)
            ).start()

    return jsonify({
        'success': True,
        'summary': {
            'total': len(uploaded) + len(skipped) + len(failed),
            'uploaded': len(uploaded),
            'uploaded_files': uploaded,
            'skipped': skipped,
            'failed': failed
        },
        'redirect_url': url_for('roms.index')
    })

@roms_bp.route('/upload_chunk', methods=['POST'])
@login_required
def upload_chunk():
    """Handle chunked upload of a single ROM file using raw streams."""
    platform_id = request.args.get('platform_id') or request.form.get('platform_id')
    if not platform_id:
        return jsonify({'success': False, 'message': 'Platform is required.'}), 400

    platform = db.session.get(Platform, platform_id)
    if not platform:
        return jsonify({'success': False, 'message': 'Invalid platform.'}), 400

    original_name = request.args.get('filename') or request.form.get('filename')
    if not original_name:
        return jsonify({'success': False, 'message': 'Filename is required.'}), 400

    chunk_index = int(request.args.get('chunk_index', request.form.get('chunk_index', 0)))
    total_chunks = int(request.args.get('total_chunks', request.form.get('total_chunks', 1)))
    start_offset = int(request.args.get('start_offset', 0))
    upload_id = request.args.get('upload_id') or request.form.get('upload_id')
    
    if not upload_id:
        return jsonify({'success': False, 'message': 'Upload ID is required.'}), 400

    filename = make_safe_filename(original_name)
    if not filename or is_ignored_rom_file(original_name) or is_ignored_rom_file(filename):
        return jsonify({'success': False, 'message': 'Metadata/system files (e.g. gamelist.xml) cannot be uploaded as ROMs.'}), 400

    # Extension check on first chunk
    if chunk_index == 0 and platform.allowed_extensions:
        allowed_list = [e.strip().lower() for e in platform.allowed_extensions.split(',') if e.strip()]
        _, ext = os.path.splitext(filename)
        ext_cleaned = ext.strip('.').lower()
        if ext_cleaned not in allowed_list:
            return jsonify({'success': False, 'message': f'.{ext_cleaned} not allowed.'}), 400

    platform_dir = platform.get_folder_name
    upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
    os.makedirs(upload_path, exist_ok=True)

    temp_dir = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir, '.temp')
    os.makedirs(temp_dir, exist_ok=True)

    # Use a single .tmp file per upload_id
    tmp_filename = f"upload_{secure_filename(upload_id)}.tmp"
    tmp_path = os.path.join(temp_dir, tmp_filename)

    # Create the file atomically if it doesn't exist
    try:
        fd = os.open(tmp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except OSError:
        pass # File already exists

    # Write directly to the exact byte offset in the temp file
    try:
        if request.content_type == 'application/octet-stream':
            stream = request.stream
        else:
            file = request.files.get('file')
            if not file:
                return jsonify({'success': False, 'message': 'No chunk provided.'}), 400
            stream = file.stream

        with open(tmp_path, 'r+b') as f:
            f.seek(start_offset)
            shutil.copyfileobj(stream, f)
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error writing chunk: {str(e)}'}), 500

    # If it's the last chunk, we do a zero-copy assembly (just rename the file)
    if chunk_index == total_chunks - 1:
        # Determine unique save filename
        base, extension = os.path.splitext(filename)
        counter = 1
        save_filename = filename
        final_file_path = os.path.join(upload_path, save_filename)
        while os.path.exists(final_file_path) or Rom.query.filter_by(filename=save_filename, platform_id=platform.id).first() is not None:
            save_filename = f"{base}_{counter}{extension}"
            final_file_path = os.path.join(upload_path, save_filename)
            counter += 1

        # Zero-copy assembly: rename temp to final
        try:
            os.rename(tmp_path, final_file_path)
        except Exception as e:
            # Fallback if cross-device link issues
            try:
                shutil.move(tmp_path, final_file_path)
            except Exception as move_e:
                return jsonify({'success': False, 'message': f'Error finalizing file: {str(move_e)}'}), 500

        # Database insert and trigger background scrape
        rom = Rom(filename=save_filename, platform_id=platform.id, original_filename=original_name)
        db.session.add(rom)
        db.session.flush() # get ID

        if _has_scraper_credentials(current_app, platform):
            app = current_app._get_current_object()
            threading.Thread(
                target=_background_scrape,
                args=(app, [(rom.id, save_filename)], platform.name)
            ).start()

        db.session.commit()
        invalidate_platform_cache(current_app._get_current_object(), platform_dir)

        return jsonify({
            'success': True,
            'message': 'Upload complete',
            'filename': original_name,
            'saved_as': save_filename
        })

    return jsonify({'success': True, 'message': f'Chunk {chunk_index} uploaded.'})

@roms_bp.route('/download/<int:id>')
@roms_bp.route('/api/<int:id>/download')
@login_required
def download(id):
    rom = db.session.get(Rom, id)
    if not rom:
        flash('ROM not found.', 'error')
        return redirect(url_for('roms.index'))
        
    platform_dir = rom.platform.get_folder_name
    upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
    
    return send_from_directory(upload_path, rom.filename, as_attachment=True)

@roms_bp.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    rom = db.session.get(Rom, id)
    if rom:
        platform = rom.platform
        platform_dir = platform.get_folder_name if platform else None
        
        from utils.es_xml import delete_rom_files
        delete_rom_files(current_app._get_current_object(), rom)
            
        db.session.delete(rom)
        db.session.commit()
        if platform:
            invalidate_platform_cache(current_app._get_current_object(), platform_dir)
            from utils.es_xml import generate_gamelist_xml
            generate_gamelist_xml(current_app._get_current_object(), platform)
        flash('ROM deleted successfully.', 'success')
    else:
        flash('ROM not found.', 'error')
    return redirect(url_for('roms.index'))

@roms_bp.route('/scan', methods=['POST'])
@login_required
def scan():
    platforms = Platform.query.all()
    added_count = 0
    
    # Purge any existing DB records that represent metadata/system files
    all_roms = Rom.query.all()
    invalid_rom_ids = [rom.id for rom in all_roms if is_ignored_rom_file(rom.filename) or is_ignored_rom_file(rom.original_filename)]
    if invalid_rom_ids:
        Rom.query.filter(Rom.id.in_(invalid_rom_ids)).delete(synchronize_session=False)
        db.session.commit()
    
    for platform in platforms:
        platform_dir = platform.get_folder_name
        upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir)
        
        if not os.path.exists(upload_path):
            continue
            
        allowed_list = []
        if platform.allowed_extensions:
            allowed_list = [e.strip().lower() for e in platform.allowed_extensions.split(',') if e.strip()]
            
        try:
            for entry in os.scandir(upload_path):
                if entry.is_file():
                    filename = entry.name
                    if is_ignored_rom_file(filename):
                        continue
                        
                    _, ext = os.path.splitext(filename)
                    ext_cleaned = ext.strip('.').lower()
                    
                    # Validate extension if configured
                    if allowed_list and ext_cleaned not in allowed_list:
                        continue
                        
                    # Check if already exists in DB
                    exists = Rom.query.filter_by(filename=filename, platform_id=platform.id).first()
                    if not exists:
                        metadata = _get_scraper_config_and_metadata(current_app._get_current_object(), platform, filename)
                        rom = Rom(filename=filename, platform_id=platform.id)
                        _apply_metadata(current_app._get_current_object(), platform, rom, metadata)
                        db.session.add(rom)
                        added_count += 1
                    elif exists and exists.game_title is None:
                        if exists.search_keywords:
                            metadata = _get_scraper_config_and_metadata(current_app._get_current_object(), platform, exists.search_keywords, is_keyword=True)
                        else:
                            metadata = _get_scraper_config_and_metadata(current_app._get_current_object(), platform, filename)
                        _apply_metadata(current_app._get_current_object(), platform, exists, metadata)
                        if exists.game_title:
                            added_count += 1
        except Exception as e:
            flash(f"Error scanning directory for platform {platform.name}: {e}", "error")
            
    if added_count > 0:
        db.session.commit()
        from utils.es_xml import generate_gamelist_xml
        for platform in platforms:
            generate_gamelist_xml(current_app._get_current_object(), platform)
        flash(f"Scan complete. Found and added {added_count} new ROM(s) from the filesystem.", "success")
    else:
        flash("Scan complete. No new ROM files found.", "info")
        
    return redirect(url_for('roms.index'))

@roms_bp.route('/edit_keywords/<int:id>', methods=['POST'])
@login_required
def edit_keywords(id):
    rom = db.session.get(Rom, id)
    if not rom:
        flash('ROM not found.', 'error')
        return redirect(url_for('roms.index'))
        
    search_keywords = request.form.get('search_keywords', '').strip()
    # If empty, set to None
    rom.search_keywords = search_keywords if search_keywords else None
    db.session.commit()
    flash('Search keywords updated successfully.', 'success')
    return redirect(url_for('roms.index'))

@roms_bp.route('/rescan/<int:id>', methods=['POST'])
@login_required
def rescan_individual(id):
    rom = db.session.get(Rom, id)
    if not rom:
        flash('ROM not found.', 'error')
        return redirect(url_for('roms.index'))
        
    if not _has_scraper_credentials(current_app, rom.platform):
        provider = rom.platform.scraper if rom.platform and rom.platform.scraper else 'thegamesdb'
        flash(f'Scraper credentials for {provider} are not configured in .env.', 'error')
        return redirect(url_for('roms.index'))
        
    # Use search keywords if available, otherwise filename
    if rom.search_keywords:
        metadata = _get_scraper_config_and_metadata(current_app._get_current_object(), rom.platform, rom.search_keywords, is_keyword=True)
        search_term = rom.search_keywords
    else:
        metadata = _get_scraper_config_and_metadata(current_app._get_current_object(), rom.platform, rom.original_filename or rom.filename)
        search_term = rom.original_filename or rom.filename
        
    if metadata and metadata.get("game_title"):
        _apply_metadata(current_app._get_current_object(), rom.platform, rom, metadata)
        db.session.commit()
        from utils.es_xml import generate_gamelist_xml
        generate_gamelist_xml(current_app._get_current_object(), rom.platform)
        from utils.cache import invalidate_platform_cache
        invalidate_platform_cache(current_app._get_current_object(), rom.platform.get_folder_name)
        flash(f"Successfully updated metadata for '{search_term}'. Title: {metadata['game_title']}", 'success')
    else:
        provider = rom.platform.scraper if rom.platform and rom.platform.scraper else 'thegamesdb'
        flash(f"No game title found on {provider} for '{search_term}'.", 'warning')
        
    return redirect(url_for('roms.index'))

@roms_bp.route('/batch_rescrape', methods=['POST'])
@login_required
def batch_rescrape():
    data = request.get_json()
    if not data or 'rom_ids' not in data:
        return jsonify({'success': False, 'message': 'No ROMs selected.'}), 400

    rom_ids = data['rom_ids']
    if not isinstance(rom_ids, list):
        return jsonify({'success': False, 'message': 'Invalid format.'}), 400

    roms = Rom.query.filter(Rom.id.in_(rom_ids)).all()
    if not roms:
        return jsonify({'success': False, 'message': 'No matching ROMs found.'}), 404

    # Check if at least one selected ROM has scraper credentials
    has_any_creds = False
    for rom in roms:
        if _has_scraper_credentials(current_app, rom.platform):
            has_any_creds = True
            break
            
    if not has_any_creds:
        return jsonify({'success': False, 'message': 'Scraper credentials are not configured in .env for any of the selected ROM platforms.'}), 400

    app = current_app._get_current_object()
    threading.Thread(
        target=_batch_rescrape_task,
        args=(app, rom_ids)
    ).start()

    return jsonify({'success': True, 'message': f'Rescrape started for {len(rom_ids)} ROM(s) in the background.'})

@roms_bp.route('/batch_delete', methods=['POST'])
@login_required
def batch_delete():
    data = request.get_json()
    if not data or 'rom_ids' not in data:
        return jsonify({'success': False, 'message': 'No ROMs selected.'}), 400

    rom_ids = data['rom_ids']
    if not isinstance(rom_ids, list):
        return jsonify({'success': False, 'message': 'Invalid format.'}), 400

    roms = Rom.query.filter(Rom.id.in_(rom_ids)).all()
    if not roms:
        return jsonify({'success': False, 'message': 'No matching ROMs found.'}), 404

    deleted_count = 0
    platforms_to_update = set()
    from utils.es_xml import delete_rom_files
    for rom in roms:
        if rom.platform:
            platforms_to_update.add(rom.platform)
        delete_rom_files(current_app._get_current_object(), rom)
        db.session.delete(rom)
        deleted_count += 1

    db.session.commit()
    from utils.es_xml import generate_gamelist_xml
    for platform in platforms_to_update:
        invalidate_platform_cache(current_app._get_current_object(), platform.get_folder_name)
        generate_gamelist_xml(current_app._get_current_object(), platform)
    return jsonify({'success': True, 'message': f'Successfully deleted {deleted_count} ROM(s).'})

@roms_bp.route('/batch_download', methods=['POST'])
@login_required
def batch_download():
    rom_ids = request.form.getlist('rom_ids')
    if not rom_ids:
        flash('No ROMs selected for download.', 'error')
        return redirect(url_for('roms.index'))

    roms = Rom.query.filter(Rom.id.in_(rom_ids)).all()
    if not roms:
        flash('No matching ROMs found for download.', 'error')
        return redirect(url_for('roms.index'))

    # Create temporary file
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    temp_path = temp_zip.name
    temp_zip.close()

    try:
        with zipfile.ZipFile(temp_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for rom in roms:
                platform_dir = rom.platform.get_folder_name
                file_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir, rom.filename)
                if os.path.exists(file_path):
                    # Add to zip at the root, or within a folder for the platform
                    arcname = os.path.join(platform_dir, rom.filename)
                    zipf.write(file_path, arcname)

        @after_this_request
        def remove_file(response):
            try:
                os.remove(temp_path)
            except Exception as e:
                current_app.logger.error(f"Error removing temporary zip file {temp_path}: {e}")
            return response

        return send_file(temp_path, as_attachment=True, download_name="rommagic_batch.zip", mimetype='application/zip')

    except Exception as e:
        # Cleanup on failure
        if os.path.exists(temp_path):
            os.remove(temp_path)
        flash(f'An error occurred during zip creation: {e}', 'error')
        return redirect(url_for('roms.index'))

@roms_bp.route('/media/<int:platform_id>/<path:filename>')
@login_required
def serve_media(platform_id, filename):
    platform = db.session.get(Platform, platform_id)
    if not platform:
        return "Not found", 404
    platform_dir = platform.get_folder_name
    upload_path = os.path.join(current_app.config['ROM_UPLOAD_PATH'], platform_dir, 'images')
    return send_from_directory(upload_path, filename)


